"""Bounded, metadata-only CKR6 reviewer intake from existing Actions receipts.

No Notion or GitHub I/O. This never judges lesson applicability or changes
the trusted CKR6 result. No source text, URLs, hints or provider payloads.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping

REPOSITORY = "Blummer92/agent-os"
MAX_INPUT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 12 * 1024
MAX_CANDIDATES = 5
ID_RE = re.compile(r"LL-[1-9][0-9]{0,4}\Z")
REVISION_RE = re.compile(r"20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,9})?Z\Z")
REASONS = frozenset({
    "knowledge-sufficient", "knowledge-not-needed", "no-relevant-candidate",
    "generic-relevance-unverified", "canonical-reference-missing",
    "candidate-budget-exceeded", "stale-relevant-candidate",
    "unverifiable-relevant-candidate", "canonical-authority-conflict",
    "duplicate-identity-conflict", "required-library-uncovered",
    "upstream-ranking-order-mismatch", "lesson-read-incomplete",
    "lesson-read-timeout", "lesson-read-connection-error",
    "lesson-read-runtime-error", "ckr6-result-unavailable",
})
STATUSES = frozenset({
    "sufficient", "insufficient", "manual-review", "not-needed",
    "unavailable-safe-fallback", "rejected",
})
# Stable non-secret outcomes from the canonical Notion reader composition.
NOTION_REASONS = frozenset({
    "notion-connection-error", "notion-timeout", "notion-malformed-pagination",
    "notion-malformed-response", "notion-adapter-contract-error",
    "notion-read-failure", "notion-malformed-output",
})
CURRENTNESS = frozenset({"current", "stale", "unverifiable"})
PROVENANCE = frozenset({
    "canonical-github-ref-present", "canonical-github-ref-missing-or-rejected",
})
BASES = frozenset({
    "no-relevant-signal", "identity-scoped", "title-echo", "exact-library",
    "rule-ckr6-mutation-boundary", "generic-unique", "generic-tie-lexical-cut",
    "not-evaluated",
})
COUNTERS = (
    "read_count", "observed_rows", "normalized_rows", "skipped_rows",
    "candidate_count", "best_bucket_tied_identities",
)
# Optional complete no-match bundle from CKR6's artifact writer (#4026).
NO_MATCH_ROW_COUNTERS = (
    "miss_ecosystem_rows", "miss_capability_rows", "miss_exact_library_rows",
    "miss_target_path_rows",
)
NO_MATCH_COUNTERS = (*NO_MATCH_ROW_COUNTERS, "miss_library_hints_not_named")


def _positive_int(value: Any) -> bool:
    return type(value) is int and 0 < value <= 10**15


def _load(path: Path) -> Mapping[str, Any]:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("oversized")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if type(raw) is not dict:
        raise ValueError("invalid-json")
    return raw


def _finite_diagnostics(diagnostics: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(diagnostics, Mapping):
        return {"available": False}
    allowed = {"retrieval_reason_code", "incomplete_reason_code", "selection_basis", *COUNTERS,
               *NO_MATCH_COUNTERS,
               "terminal_query_bucket", "terminal_page_row_count_bucket",
               "terminal_page_has_more", "terminal_page_cursor_present"}
    if set(diagnostics) - allowed:
        raise ValueError("diagnostic-schema")
    basis = diagnostics.get("selection_basis")
    if basis is not None and (type(basis) is not str or basis not in BASES):
        raise ValueError("diagnostic-basis")
    reason = diagnostics.get("retrieval_reason_code")
    incomplete = diagnostics.get("incomplete_reason_code")
    if type(reason) is not str or (reason != "none" and reason not in REASONS and not re.fullmatch(r"notion-[a-z0-9-]{1,72}", reason)):
        raise ValueError("diagnostic-reason")
    if (reason != "none" and reason not in REASONS and reason not in NOTION_REASONS
            and not re.fullmatch(r"notion-http-[1-5][0-9]{2}", reason)):
        # Preserve intake compatibility without projecting unknown strings.
        reason = "unclassified-reason"
    if type(incomplete) is not str or incomplete not in {
        "none", "row-bound-exceeded", "page-bound-exceeded", "missing-cursor",
        "repeated-cursor", "read-budget-exceeded", "malformed-page",
        "malformed-pagination", "unknown-incomplete",
    }:
        raise ValueError("diagnostic-incomplete")
    has_miss_counters = any(field in diagnostics for field in NO_MATCH_COUNTERS)
    if has_miss_counters and (
        basis != "no-relevant-signal" or incomplete != "none"
        or not all(field in diagnostics for field in NO_MATCH_COUNTERS)
    ):
        raise ValueError("diagnostic-miss-counter-shape")
    count_fields = (*COUNTERS, *NO_MATCH_COUNTERS) if has_miss_counters else COUNTERS
    for field in count_fields:
        if field not in diagnostics or type(diagnostics[field]) is not int or not 0 <= diagnostics[field] <= 10_000:
            raise ValueError("diagnostic-count")
    # The retrieval owner counts each processed row as normalized or skipped.
    # Normalized duplicates still count here; selection deduplicates separately.
    if diagnostics["observed_rows"] != diagnostics["normalized_rows"] + diagnostics["skipped_rows"]:
        raise ValueError("diagnostic-row-accounting")
    # Each row metric counts at most once per distinct normalized record.
    # The final metric counts request library hints, not records.
    if has_miss_counters and any(
        diagnostics[field] > diagnostics["normalized_rows"] for field in NO_MATCH_ROW_COUNTERS
    ):
        raise ValueError("diagnostic-row-population")
    return {
        "available": True,
        "selection_basis": basis if basis is not None else "not-evaluated",
        "retrieval_reason_code": reason,
        "incomplete_reason_code": incomplete,
        **{name: diagnostics[name] for name in count_fields},
    }


def build_review_evidence(
    event: Mapping[str, Any],
    result: Mapping[str, Any],
    diagnostics: Mapping[str, Any] | None,
    *,
    run_id: int,
    run_attempt: int,
) -> dict[str, Any]:
    """Project supplied metadata without authenticating its request/run/artifact association."""
    repository = event.get("repository")
    issue = event.get("issue")
    comment = event.get("comment")
    if (
        not isinstance(repository, Mapping) or repository.get("full_name") != REPOSITORY
        or not isinstance(issue, Mapping) or not _positive_int(issue.get("number"))
        or not isinstance(comment, Mapping) or not _positive_int(comment.get("id"))
        or not _positive_int(run_id) or not _positive_int(run_attempt)
    ):
        raise ValueError("event-identity")
    if result.get("repository") != REPOSITORY or result.get("issue_number") != issue["number"]:
        raise ValueError("result-identity")
    # The raw Actions result omits this field; a copied postback may carry it.
    # A matching supplied ID is a consistency check, not provenance.
    if "request_comment_id" in result and (
        not _positive_int(result["request_comment_id"])
        or result["request_comment_id"] != comment["id"]
    ):
        raise ValueError("result-request-identity")
    if result.get("operation") not in {"issue-start", "failed-repair"}:
        raise ValueError("operation")
    status = result.get("status")
    if type(status) is not str or status not in STATUSES:
        raise ValueError("status")
    reasons = result.get("reason_codes")
    if type(reasons) is not list or len(reasons) > 8:
        raise ValueError("reasons")
    safe_reasons = [reason if type(reason) is str and reason in REASONS else "unclassified-reason"
                    for reason in reasons]
    selected = result.get("selected_lesson_ids", [])
    if type(selected) is not list or len(selected) > 3 or any(type(s) is not str or not ID_RE.fullmatch(s) for s in selected):
        raise ValueError("selected-ids")
    raw_candidates = result.get("rejected_candidate_provenance", [])
    if type(raw_candidates) is not list or len(raw_candidates) > MAX_CANDIDATES:
        raise ValueError("candidates")
    candidates = []
    for item in raw_candidates:
        if not isinstance(item, Mapping):
            raise ValueError("candidate-shape")
        identity = item.get("lesson_id")
        revision = item.get("source_revision")
        currentness = item.get("currentness")
        provenance = item.get("provenance")
        if (type(identity) is not str or not ID_RE.fullmatch(identity)
                or type(revision) is not str or not REVISION_RE.fullmatch(revision)
                or currentness not in CURRENTNESS or provenance not in PROVENANCE):
            raise ValueError("candidate-metadata")
        candidates.append({"lesson_id": identity, "source_revision": revision,
                           "currentness": currentness, "provenance": provenance,
                           "review_status": "unreviewed"})
    return {
        "schema_version": "agent-os-ckr6-review-intake/v1",
        "evidence_scope": "metadata-only",
        "review_state": "requires-independent-exact-revision-review",
        "trusted_admission_unchanged": True,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "notion_writes_authorized": False,
        "source": {
            "repository": REPOSITORY,
            "thread_number": issue["number"],
            "thread_kind": "pr" if isinstance(issue.get("pull_request"), Mapping) else "issue",
            "request_comment_id": comment["id"],
            "run_id": run_id,
            "run_attempt": run_attempt,
            "request_run_artifact_association": "supplied-unverified",
        },
        "ckr6": {"operation": result["operation"], "status": status,
                 "reason_codes": safe_reasons, "selected_lesson_ids": selected,
                 "selection_is_applicability_proof": False},
        "retrieval": _finite_diagnostics(diagnostics),
        "candidate_provenance": candidates,
        "review_requirements": [
            "qualified-independent-reviewer", "private-read-only-exact-revision",
            "independently-verify-request-run-artifact-association",
            "source-owned-guidance-polarity", "status-surface-and-archive",
            "canonical-source-provenance", "unrelated-task-hard-negatives",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--diagnostics", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-attempt", required=True, type=int)
    args = parser.parse_args()
    try:
        diagnostics = _load(args.diagnostics) if args.diagnostics and args.diagnostics.exists() else None
        evidence = build_review_evidence(
            _load(args.event), _load(args.result), diagnostics,
            run_id=args.run_id, run_attempt=args.run_attempt,
        )
        data = (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(data) > MAX_OUTPUT_BYTES:
            raise ValueError("oversized-result")
        args.output.write_bytes(data)
    except (OSError, ValueError, TypeError, UnicodeError):
        print("ckr6-review-evidence-unavailable")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
