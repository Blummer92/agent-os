"""Read-only Lessons Learned lifecycle metrics from durable GitHub evidence (#3418).

Sources are only the existing bounded marker comments on issues: CKR6 result
comments (`<!-- agent-os-ckr6-result:v1 -->`, posted by the ingress workflow)
and lesson application receipts (`<!-- agent-os-lesson-receipt:v1 -->`).
Output schema v2.0 explicitly retires the v1 snapshot-backed
``accountability`` field; CKR6 evidence remains the lesson eligibility source.
No database, telemetry store, Notion read or write, score, or promotion
authority is created. Unknown stays unknown; causality is never inferred.

Run: ``python -m agent_os_execution_service.lesson_learning_metrics
--repository Blummer92/agent-os --issues 3417,3418`` (HTTP GET only;
``GITHUB_TOKEN`` optional).
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import re
from typing import Iterable, Mapping
from urllib.parse import quote

from .ckr6_github_bridge import parse_ckr6_result_comment
from .lesson_learning_loop import (
    LESSON_ID,
    REFINEMENT_SIGNAL_REASONS,
    parse_receipt_comment,
    receipt_key,
    verify_receipt_against_result,
)

# v1 was the unversioned snapshot-backed JSON output. v2 explicitly removes
# the static CKR12 accountability field.
METRICS_OUTPUT_SCHEMA_VERSION = "2.0"

# Notion-facing "Applied in PRs" projection schema version (offline only;
# persisting it inside Notion needs its own owner authorization).
APPLIED_PRS_PROJECTION_SCHEMA_VERSION = "1.0"
MAX_APPLIED_PRS_DISPLAYED = 5
_PR_URL = re.compile(r"https://github\.com/Blummer92/agent-os/pull/([1-9][0-9]{0,6})")

MAX_ISSUES = 50
MAX_PAGES_PER_ISSUE = 10


def _collect_results_and_receipts(
    comments_by_issue: Mapping[int, Iterable[Mapping[str, object]]],
) -> tuple[dict[int, dict[str, object]], list[dict[str, object]], Counter]:
    """Parse CKR6 result comments and lesson receipts from acquired comments.

    Pure; shared by the metrics derivation and the applied-PRs projection so
    both agree on what counts as a verified receipt. Malformed markers are
    counted, never silently dropped.
    """
    results: dict[int, dict[str, object]] = {}
    receipts: list[dict[str, object]] = []
    malformed = Counter()
    for issue, comments in comments_by_issue.items():
        for comment in comments:
            body, comment_id = comment.get("body"), comment.get("id")
            if type(body) is not str or type(comment_id) is not int:
                continue
            if body.startswith("<!-- agent-os-ckr6-result:v1 -->"):
                try:
                    results[comment_id] = parse_ckr6_result_comment(body)
                except (TypeError, ValueError):
                    malformed["ckr6-result"] += 1
            elif body.startswith("<!-- agent-os-lesson-receipt:v1 -->"):
                try:
                    receipts.append(parse_receipt_comment(body))
                except (TypeError, ValueError):
                    malformed["receipt"] += 1
    return results, receipts, malformed


def _verify_receipts(
    results: Mapping[int, Mapping[str, object]], receipts: Iterable[dict[str, object]]
) -> tuple[dict[tuple[object, ...], dict[str, object]], Counter, int, int]:
    """Bind each parsed receipt to its trusted CKR6 result.

    Returns (valid-by-receipt-key, invalid reason counts, duplicates ignored,
    conflicting). A receipt is valid only when the referenced result exists,
    is sufficient, and actually selected the exact (lesson_id,
    source_revision) the receipt claims. Forged, missing-result, wrong-lesson,
    wrong-revision, and stale-head receipts land in ``invalid`` and never
    count as applied. The first valid receipt for a receipt key stands;
    a repeat of the same key is an idempotent duplicate, never a double count.
    """
    valid: dict[tuple[object, ...], dict[str, object]] = {}
    invalid = Counter()
    duplicates = 0
    conflicting = 0
    for receipt in receipts:
        result = results.get(receipt["ckr6_result_comment_id"])
        if result is None:
            invalid["receipt-result-not-found"] += 1
            continue
        reason = verify_receipt_against_result(
            receipt, result, result_comment_id=receipt["ckr6_result_comment_id"]
        )
        if reason is not None:
            invalid[reason] += 1
            continue
        key = receipt_key(receipt)
        prior = valid.get(key)
        if prior is None:
            valid[key] = receipt
        elif (prior["disposition"], prior["reason_code"]) == (receipt["disposition"], receipt["reason_code"]):
            duplicates += 1  # idempotent: never double-counted
        else:
            conflicting += 1  # first valid receipt stands; conflict is reported
    return valid, invalid, duplicates, conflicting


def project_applied_prs(
    lesson_id: str,
    source_revision: str,
    comments_by_issue: Mapping[int, Iterable[Mapping[str, object]]],
    *,
    max_displayed: int = MAX_APPLIED_PRS_DISPLAYED,
) -> dict[str, object]:
    """Notion-facing "Applied in PRs" projection for one lesson revision.

    Pure and offline: consumes only already-acquired GitHub comments and the
    existing receipt verifier. Output is a display projection, not evidence
    and not a write: a PR appears here only when an independently verified
    lesson-use receipt (disposition ``applied``) binds this exact
    (lesson_id, source_revision) to that PR through a trusted CKR6 result
    that selected the same pair. A merged PR with no receipt, a skipped
    receipt, and any forged / wrong-PR / wrong-lesson / wrong-revision /
    stale-head / unknown-result / malformed receipt never appear.

    Applied PRs are NEVER merged into Source Link or Supporting Source Links;
    this projection carries no provenance fields and derives no counts for
    any Notion counter field. When there are no verified applications the
    projection says so explicitly (``display_text``), never "not applied".

    ``applied_prs`` is bounded (``max_displayed``, default 5) and ordered by
    PR number ascending; ``drill_through_url`` is the canonical GitHub
    search for the lesson id, the only route to the full history.
    ``notion_rich_text`` is the display form: one plain-text item per
    displayed PR URL, plus a trailing drill-through item only when more
    verified applications exist than are displayed, or a single
    "No verified applications" item when there are none.
    """
    if type(lesson_id) is not str or LESSON_ID.fullmatch(lesson_id) is None:
        raise ValueError("lesson_id must be a canonical Lesson ID")
    if type(source_revision) is not str or not source_revision:
        raise ValueError("source_revision must be a non-empty string")
    if type(max_displayed) is not int or not 1 <= max_displayed <= MAX_APPLIED_PRS_DISPLAYED:
        raise ValueError("max_displayed must be between 1 and 5")

    results, receipts, malformed = _collect_results_and_receipts(comments_by_issue)
    valid, invalid, _duplicates, _conflicting = _verify_receipts(results, receipts)

    # Exact-revision contract: a receipt verified for an OLDER revision of
    # the same lesson is evidence for that revision's projection only, never
    # for this one. lesson_id alone is not enough.
    lesson_receipts = [
        r
        for r in valid.values()
        if r["lesson_id"] == lesson_id and r["source_revision"] == source_revision
    ]
    rejected_for_this_lesson = Counter()
    for receipt in receipts:
        if receipt.get("lesson_id") != lesson_id:
            continue
        result = results.get(receipt["ckr6_result_comment_id"])
        if result is None:
            rejected_for_this_lesson["receipt-result-not-found"] += 1
        else:
            reason = verify_receipt_against_result(
                receipt, result, result_comment_id=receipt["ckr6_result_comment_id"]
            )
            if reason is not None:
                rejected_for_this_lesson[reason] += 1

    applied_prs: list[dict[str, object]] = []
    skipped_not_counted = 0
    verified_applied_non_pr = 0
    duplicates_for_this_lesson = 0
    seen_keys: set[tuple[object, ...]] = set()
    for receipt in lesson_receipts:
        key = receipt_key(receipt)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if receipt["disposition"] == "skipped":
            skipped_not_counted += 1
            continue
        if receipt["disposition"] != "applied":
            continue
        match = _PR_URL.fullmatch(str(receipt["task_ref"]))
        if match is None:
            verified_applied_non_pr += 1  # verified use, but not a PR link
            continue
        applied_prs.append(
            {
                "pr_url": str(receipt["task_ref"]),
                "pr_number": int(match.group(1)),
                "reason_code": str(receipt["reason_code"]),
                # The binding evidence is the trusted CKR6 RESULT comment the
                # receipt was verified against; name the key after what it holds.
                "ckr6_result_comment_id": receipt["ckr6_result_comment_id"],
            }
        )
    applied_prs.sort(key=lambda item: item["pr_number"])
    # Duplicate receipt ids for this lesson/revision never double-count:
    # count repeats of an already-seen receipt key among the parsed receipts
    # naming this exact (lesson_id, source_revision).
    seen_dup_keys: set[tuple[object, ...]] = set()
    duplicates_for_this_lesson = 0
    for receipt in receipts:
        if receipt.get("lesson_id") != lesson_id or receipt.get("source_revision") != source_revision:
            continue
        key = receipt_key(receipt)
        if key in seen_dup_keys:
            duplicates_for_this_lesson += 1
        else:
            seen_dup_keys.add(key)

    total = len(applied_prs)
    displayed = applied_prs[:max_displayed]
    additional = total - len(displayed)
    drill_through_url = (
        "https://github.com/search?q="
        + quote(f"repo:Blummer92/agent-os {lesson_id}", safe="")
        + "&type=issues"
    )
    if total == 0:
        display_text = "No verified applications"
        notion_rich_text: list[dict[str, object]] = [
            {"type": "text", "text": {"content": "No verified applications"}}
        ]
    else:
        display_text = (
            f"Applied in {total} verified PR{'s' if total != 1 else ''}"
            + (f" (showing {len(displayed)})" if additional else "")
        )
        notion_rich_text = [
            {"type": "text", "text": {"content": str(item["pr_url"])}}
            for item in displayed
        ]
        if additional:
            notion_rich_text.append(
                {
                    "type": "text",
                    "text": {
                        "content": (
                            f"+{additional} more verified application"
                            f"{'s' if additional != 1 else ''} — full history: "
                            f"{drill_through_url}"
                        )
                    },
                }
            )
    return {
        "schema_version": APPLIED_PRS_PROJECTION_SCHEMA_VERSION,
        "projection": "applied-in-prs",
        "lesson_id": lesson_id,
        "source_revision": source_revision,
        "applied_prs": displayed,
        "verified_total": total,
        "displayed": len(displayed),
        "additional_count": additional,
        "drill_through_url": drill_through_url,
        "drill_through_label": f"Full GitHub-backed history for {lesson_id}",
        "display_text": display_text,
        "has_verified_applications": total > 0,
        "notion_rich_text": notion_rich_text,
        "rejected_for_this_lesson": dict(sorted(rejected_for_this_lesson.items())),
        "duplicates_ignored": duplicates_for_this_lesson,
        "skipped_not_counted": skipped_not_counted,
        "verified_applied_non_pr": verified_applied_non_pr,
        "malformed_receipt_markers": malformed.get("receipt", 0),
    }


def derive_lesson_metrics(comments_by_issue: Mapping[int, Iterable[Mapping[str, object]]]) -> dict[str, object]:
    """Pure derivation over already-acquired issue comments."""
    results, receipts, malformed = _collect_results_and_receipts(comments_by_issue)
    by_status = Counter()
    materiality = Counter()
    rejections = Counter()
    eligibility_blocks = Counter()
    candidates = Counter()
    candidate_core = Counter()
    refinements = Counter()
    selected: dict[tuple[str, str], int] = {}
    reads = 0
    for result in results.values():
        operation, status = result.get("operation"), result.get("status")
        by_status[f"{operation}:{status}"] += 1
        if result.get("materiality_source"):
            materiality[str(result["materiality_source"])] += 1
        if result.get("notion_read_performed") or status in {"sufficient", "insufficient"}:
            reads += 1
        if status == "rejected":
            for code in result.get("reason_codes", []):
                rejections[str(code)] += 1
        for item in result.get("rejected_candidate_provenance", []) or []:
            eligibility_blocks[f"{item.get('currentness')}:{item.get('provenance')}"] += 1
        for item in result.get("selected_lessons", []) or []:
            key = (item.get("lesson_id"), item.get("source_revision"))
            selected[key] = selected.get(key, 0) + 1
        if operation == "lesson-candidate":
            candidates[str(status)] += 1
            proposal = result.get("lesson_proposal") or {}
            if proposal.get("core_identity"):
                candidate_core[proposal["core_identity"]] += 1
        if operation == "lesson-refinement":
            refinements[str(status)] += 1

    valid, invalid, duplicates, conflicting = _verify_receipts(results, receipts)

    applied = Counter(r["reason_code"] for r in valid.values() if r["disposition"] == "applied")
    skipped = Counter(r["reason_code"] for r in valid.values() if r["disposition"] == "skipped")
    used = {(r["lesson_id"], r["source_revision"]) for r in valid.values()}
    refinement_signals = sorted({
        r["lesson_id"] for r in valid.values()
        if r["disposition"] == "skipped" and r["reason_code"] in REFINEMENT_SIGNAL_REASONS
    })
    return {
        "schema_version": METRICS_OUTPUT_SCHEMA_VERSION,
        "ckr6_results": dict(sorted(by_status.items())),
        "materiality_source": dict(sorted(materiality.items())),
        "notion_retrievals": reads,
        "rejected_requests": dict(sorted(rejections.items())),
        "eligibility_blocks": dict(sorted(eligibility_blocks.items())),
        "lessons_selected": len(selected),
        "selection_events": sum(selected.values()),
        "receipts": {
            "valid": len(valid),
            "applied": dict(sorted(applied.items())),
            "skipped": dict(sorted(skipped.items())),
            "invalid": dict(sorted(invalid.items())),
            "duplicates_ignored": duplicates,
            "conflicting": conflicting,
        },
        "selected_without_receipt": sorted(
            f"{lesson_id}@{revision}" for (lesson_id, revision) in selected if (lesson_id, revision) not in used
        ),
        "lesson_candidates": dict(sorted(candidates.items())),
        "candidate_recurrences": sum(1 for count in candidate_core.values() if count > 1),
        "refinement_proposals": dict(sorted(refinements.items())),
        "refinement_signals": refinement_signals,
        "malformed_markers": dict(sorted(malformed.items())),
        "causality_inferred": False,
        "authority_created": False,
    }


def acquire_issue_comments(repository: str, issues: Iterable[int], *, token: str = "") -> dict[int, list[dict]]:
    """Bounded read-only GET of issue comments. Never writes."""
    import urllib.request

    numbers = list(issues)
    if len(numbers) > MAX_ISSUES or any(type(n) is not int or n < 1 for n in numbers):
        raise ValueError("issues must be a bounded list of positive integers")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "agent-os-lesson-metrics"}
    if token:
        headers["Authorization"] = "Bearer " + token
    acquired: dict[int, list[dict]] = {}
    for number in numbers:
        comments: list[dict] = []
        for page in range(1, MAX_PAGES_PER_ISSUE + 1):
            url = f"https://api.github.com/repos/{repository}/issues/{number}/comments?per_page=100&page={page}"
            request = urllib.request.Request(url, method="GET", headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                batch = json.loads(response.read().decode("utf-8"))
            if type(batch) is not list:
                raise ValueError("unexpected comments payload")
            comments.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < 100:
                break
        acquired[number] = comments
    return acquired


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="Blummer92/agent-os")
    parser.add_argument("--issues", required=True)
    args = parser.parse_args()
    issues = [int(value) for value in args.issues.split(",") if value.strip()]
    comments = acquire_issue_comments(args.repository, issues, token=os.environ.get("GITHUB_TOKEN", ""))
    print(json.dumps(derive_lesson_metrics(comments), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
