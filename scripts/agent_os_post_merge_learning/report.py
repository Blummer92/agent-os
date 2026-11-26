"""Report grouped repair evidence from a *merged*, exact-sha GitHub PR.

This bounded, read-only producer fails closed for incomplete evidence.
It is a review aid, not a lesson writer.
Commit labels are hints, never evidence that a reusable rule was proven.
To keep the report bounded, it does not reconstruct historical CI attempts,
review threads or force-pushed heads.
CKR5 remains the sole learning-quality evaluator; Notion publication and
all merge, issue, and approval decisions are explicitly out of scope.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from agent_memory_context_manager.ci_review_learning import (
    LearningSignal,
    ProducerDisposition,
    StructuredLearningOutcome,
    normalize_learning_outcome,
)

SHA = re.compile(r"^[0-9a-fA-F]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SUBJECT = re.compile(r"^(feat|fix|test|docs|refactor|chore)(?:\(([a-zA-Z0-9_.-]{1,40})\))?!?:\s+\S")
MAX_COMMITS = 250
MAX_REFS_PER_GROUP = 20
MAX_GROUPS = 25


class EvidenceError(Exception):
    """Stable machine-readable reason for missing or inconsistent proof.

    Codes identify input, GitHub transport, PR/commit identity, validation,
    or CKR5 evidence failures. Never include provider or exception text.
    """


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise EvidenceError("invalid-sha")
    # GitHub canonicalizes hexadecimal commit identities to lowercase.
    return value.lower()


def _repo(value: str) -> str:
    if not REPOSITORY.fullmatch(value) or ".." in value:
        raise EvidenceError("invalid-repository")
    return value


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Never forward a token-bearing GitHub request to another endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubReader:
    """Narrow GET-only GitHub reader; does not expose response bodies in errors."""

    def __init__(self, repository: str, token: str = ""):
        self.repository = _repo(repository)
        self.token = token

    def get(self, path: str) -> Any:
        if not path.startswith("/") or ".." in path:
            raise EvidenceError("invalid-read-path")
        request = urllib.request.Request(
            "https://api.github.com/repos/" + self.repository + path,
            headers={
                "Accept": "application/vnd.github+json",
                **({"Authorization": "Bearer " + self.token} if self.token else {}),
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "agent-os-post-merge-learning",
            },
            method="GET",
        )
        try:
            with urllib.request.build_opener(_RejectRedirects).open(request, timeout=25) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise EvidenceError("github-response-too-large")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                reason = "github-read-redirect-rejected"
            elif exc.code == 401:
                reason = "github-read-unauthorized"
            elif exc.code == 403:
                remaining = exc.headers.get("X-RateLimit-Remaining", "") if exc.headers else ""
                reason = "github-read-rate-limited" if remaining == "0" else "github-read-forbidden"
            elif exc.code == 429:
                reason = "github-read-rate-limited"
            elif exc.code == 404:
                reason = "github-read-not-found"
            elif 500 <= exc.code < 600:
                reason = "github-read-upstream-error"
            else:
                reason = "github-read-http-error"
            raise EvidenceError(reason) from None
        except (urllib.error.URLError, ValueError, OSError):
            raise EvidenceError("github-read-unavailable") from None


def _commits(reader: GitHubReader, number: int, declared: int) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for page in range(1, MAX_COMMITS // 100 + 2):
        rows = reader.get(f"/pulls/{number}/commits?per_page=100&page={page}")
        if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(row, dict) for row in rows):
            raise EvidenceError("commit-list-malformed")
        collected.extend(rows)
        if len(collected) > MAX_COMMITS:
            raise EvidenceError("commit-list-out-of-bounds")
        if len(rows) < 100:
            break
    if len(collected) != declared:
        raise EvidenceError("commit-history-incomplete")
    try:
        canonical = [{**row, "sha": _sha(row.get("sha"))} for row in collected]
    except EvidenceError:
        raise EvidenceError("commit-history-identity-invalid") from None
    if len({row["sha"] for row in canonical}) != declared:
        raise EvidenceError("commit-history-identity-invalid")
    return canonical


def _resolve_pr(reader: GitHubReader, sha: str, explicit_number: int | None) -> dict[str, Any] | None:
    number = explicit_number
    if number is None:
        prs = reader.get(f"/commits/{sha}/pulls?per_page=100")
        if not isinstance(prs, list) or not all(isinstance(p, dict) for p in prs):
            raise EvidenceError("associated-prs-malformed")
        # A full first page cannot prove this association is unique.
        if len(prs) >= 100:
            raise EvidenceError("associated-prs-incomplete")
        candidates = [p for p in prs if p.get("merged_at") and _matches_sha(p.get("merge_commit_sha"), sha)]
        if not candidates:
            return None
        if len(candidates) != 1:
            raise EvidenceError("associated-pr-ambiguous")
        # Association rows identify the PR, but omit the authoritative count.
        number = candidates[0].get("number")
    if type(number) is not int or not 0 < number <= 2_147_483_647:
        raise EvidenceError("pr-number-invalid")
    detail = reader.get(f"/pulls/{number}")
    if not isinstance(detail, dict):
        raise EvidenceError("pr-not-merged")
    if type(detail.get("number")) is not int or detail["number"] != number:
        raise EvidenceError("requested-pr-identity-mismatch")
    return detail


def _matches_sha(value: Any, sha: str) -> bool:
    return isinstance(value, str) and value.lower() == sha


def _validate_pr(pr: dict[str, Any], repo: str, sha: str) -> tuple[int, int]:
    if not isinstance(pr.get("merged_at"), str) or not pr["merged_at"].strip() or pr.get("merged", True) is not True:
        raise EvidenceError("pr-not-merged")
    if not _matches_sha(pr.get("merge_commit_sha"), sha):
        raise EvidenceError("merge-sha-mismatch")
    base = pr.get("base")
    if not isinstance(base, dict) or base.get("ref") != "main":
        raise EvidenceError("base-not-main")
    base_repo = base.get("repo")
    if not isinstance(base_repo, dict) or base_repo.get("full_name") != repo:
        raise EvidenceError("base-repository-mismatch")
    count = pr.get("commits")
    if type(count) is not int or count <= 0:
        raise EvidenceError("pr-metadata-invalid")
    if count > MAX_COMMITS:
        raise EvidenceError("commit-count-out-of-bounds")
    # The detail number has already been bound by _resolve_pr.
    return pr["number"], count


def _validate_run(run: dict[str, Any] | None, sha: str) -> str:
    if run is None:
        return "not-observed"
    if (
        not isinstance(run, dict)
        or not _matches_sha(run.get("head_sha"), sha)
        or run.get("name") != "Agent OS Validation Gate"
        or run.get("event") != "push"
        or run.get("head_branch") != "main"
    ):
        raise EvidenceError("validation-run-identity-mismatch")
    status = run.get("status")
    conclusion = run.get("conclusion")
    if status == "completed":
        if conclusion not in ("success", "failure", "cancelled", "skipped", "timed_out",
                              "neutral", "action_required", "stale", "startup_failure"):
            raise EvidenceError("validation-run-status-invalid")
        state = conclusion
    elif status in ("queued", "in_progress", "requested", "waiting", "pending"):
        if conclusion is not None:
            raise EvidenceError("validation-run-status-conflict")
        state = "pending"
    else:
        raise EvidenceError("validation-run-status-invalid")
    return state


def _subject(entry: dict[str, Any]) -> tuple[str, str | None] | None:
    commit = entry.get("commit")
    if not isinstance(commit, dict) or not isinstance(commit.get("message"), str):
        raise EvidenceError("commit-message-invalid")
    line = re.split(r"\r\n?|\n", commit["message"], maxsplit=1)[0]
    match = SUBJECT.match(line)
    if match is None:
        return None
    kind, scope = match.groups()
    return kind, scope.casefold() if scope is not None else None


def _group_history(commits: list[dict[str, Any]], repository: str, number: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    groups: dict[str | None, dict[str, list[str]]] = {}
    kinds: dict[str, int] = {k: 0 for k in ("feat", "fix", "test", "docs", "refactor", "chore", "unclassified")}
    for entry in commits:
        parsed = _subject(entry)
        if parsed is None:
            kinds["unclassified"] += 1
            continue
        kind, scope = parsed
        kinds[kind] += 1
        if kind not in ("fix", "test"):
            continue
        group = groups.setdefault(scope, {"fix": [], "test": []})
        group[kind].append(entry["sha"])
    leads = [(scope, group) for scope, group in groups.items() if group["fix"]]
    if len(leads) > MAX_GROUPS:
        raise EvidenceError("learning-group-budget-exceeded")
    results = []
    for scope_key, group in sorted(leads, key=lambda item: item[0] or "unscoped"):
        scope = scope_key or "unscoped"
        fix_shas, test_shas = group["fix"], group["test"]
        # Interleave fix and test evidence: a fix-heavy PR must not erase
        # its regression test references at the bounded evidence limit.
        truncated = len(fix_shas) + len(test_shas) > MAX_REFS_PER_GROUP
        evidence_shas: list[str] = []
        for i in range(max(len(fix_shas), len(test_shas))):
            for group_shas in (fix_shas, test_shas):
                if i < len(group_shas) and len(evidence_shas) < MAX_REFS_PER_GROUP:
                    evidence_shas.append(group_shas[i])
            if len(evidence_shas) == MAX_REFS_PER_GROUP:
                break
        refs = [f"https://github.com/{repository}/commit/{sha}" for sha in evidence_shas]
        # The CKR5 proof bit is FALSE: commit labels cannot prove a reusable
        # guardrail or lesson novelty. Reviewers must supply independent proof.
        outcome = StructuredLearningOutcome(
            source_reference=f"https://github.com/{repository}/pull/{number}",
            signal=(LearningSignal.REPEATED_REPAIR if scope_key is not None and len(fix_shas) > 1
                    else LearningSignal.SUBSTANTIVE_REVIEW_FINDING),
            failure_signature=f"postmerge-unverified-scope:{scope}",
            ecosystem="agent-os",
            capability_kind="post-merge-learning-triage",
            lesson_summary=f"Review repair evidence for {scope}",
            what_happened=f"Commit history has {len(fix_shas)} fix and {len(test_shas)} test commits under {scope}; lesson validity is unverified.",
            severity="Medium", owner_agent="github-service-agent",
            canonical_github_refs=(f"https://github.com/{repository}/pull/{number}",),
            evidence_refs=tuple(refs),
            reusable_rule_proven=False,
        )
        ckr5 = normalize_learning_outcome(outcome)
        if ckr5.disposition is not ProducerDisposition.NOT_REUSABLE or ckr5.observation is not None:
            raise EvidenceError("unverified-ckr5-candidate-not-blocked")
        results.append({
            "scope": scope, "fix_count": len(fix_shas), "test_count": len(test_shas),
            "evidence_refs": refs, "evidence_truncated": truncated,
            "status": "review-needed", "ckr5_disposition": ckr5.disposition.value,
            "ckr5_reason_codes": list(ckr5.reason_codes),
            "reusable_rule_proven": False, "lesson_proposal": None,
        })
    return results, kinds


def build_report(reader: GitHubReader, sha: str, pr_number: int | None, validation_run_id: int | None) -> dict[str, Any]:
    sha = _sha(sha)
    if validation_run_id is not None and (type(validation_run_id) is not int or validation_run_id < 1):
        raise EvidenceError("validation-run-id-invalid")
    repo = reader.repository
    pr = _resolve_pr(reader, sha, pr_number)
    if pr is None:
        return _no_evidence_receipt("not-applicable", "push-without-merged-pr", sha)
    number, expected_count = _validate_pr(pr, repo, sha)
    commits = _commits(reader, number, expected_count)
    run = reader.get(f"/actions/runs/{validation_run_id}") if validation_run_id is not None else None
    if validation_run_id is not None and run is None:
        raise EvidenceError("validation-run-evidence-missing")
    if validation_run_id is not None and (
        not isinstance(run, dict) or type(run.get("id")) is not int or run["id"] != validation_run_id
    ):
        raise EvidenceError("validation-run-identity-mismatch")
    validation = {
        "state": _validate_run(run, sha),
        "run_url": (
            f"https://github.com/{repo}/actions/runs/{validation_run_id}"
            if validation_run_id is not None else None
        ),
    }
    groups, kinds = _group_history(commits, repo, number)
    analyzer_sha = os.environ.get("GITHUB_SHA")
    return {
        "schema_version": 1, "repository": repo, "pr_number": number,
        "merge_sha": sha, "pr_url": f"https://github.com/{repo}/pull/{number}",
        "listed_commits_complete": True, "historical_head_coverage_complete": False,
        "analyzer_sha": _sha(analyzer_sha) if analyzer_sha and SHA.fullmatch(analyzer_sha) else None,
        "analyzer_workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF") or None,
        "commit_count": expected_count,
        "all_commit_shas": [entry["sha"] for entry in commits],
        "commit_kind_counts": kinds, "validation": validation,
        # No historical CI, review-comment or force-push reconstruction:
        # this small, bounded report never certifies those unobserved surfaces.
        "historical_ci_or_review_examined": False,
        "review_leads": groups,
        "status": ("review-needed" if groups or validation["state"] != "success"
                   else "no-repair-leads-observed"),
        "lesson_proposal": None, "existing_lesson_duplicate_review": "not-run",
        "notion_write_performed": False, "github_write_performed": False,
        "publication_authorized": False, "merge_authorized": False,
        "closure_authorized": False, "authority_created": False,
    }


def _markdown_cell(value: Any) -> str:
    """Escape Markdown syntax and flatten line breaks in dynamic fields."""
    flattened = " ".join(str(value).splitlines())
    return re.sub(r"([\\|`*_{}\[\]()<>!~&])", r"\\\1", flattened)


def render_summary(report: dict[str, Any]) -> str:
    """Render the receipt without mutating it or requesting more evidence."""
    if report["status"] == "manual-review":
        reason = _markdown_cell(report["reason_code"])
        return (
            "## Post-merge learning: manual review required\n"
            f"Evidence is incomplete or invalid: {reason}. No lesson created.\n"
        )
    if report["status"] == "not-applicable":
        return "## Post-merge learning\nNo uniquely linked merged PR was found for this push. No lesson created.\n"
    lines = ["## Read-only post-merge learning analysis", "",
             f"- PR: {_markdown_cell(report['pr_url'])}", f"- Merge SHA: {_markdown_cell(report['merge_sha'])}",
             f"- Listed PR commits: **{_markdown_cell(report['commit_count'])}** (historical removed heads not certified)",
             f"- Exact merge validation: **{_markdown_cell(report['validation']['state'])}**",
             f"- Repair review leads: **{len(report['review_leads'])}**",
             f"- Analyzer revision: **{_markdown_cell(report.get('analyzer_sha') or 'unavailable')}**",
             "- Evidence scope: current merged PR commit list and supplied validation run only.",
             "- Historical CI attempts, code reviews, and removed heads: **not examined**.", "",
             "| Commit scope | Fix commits | Test commits | Disposition |",
             "| --- | ---: | ---: | --- |"]
    for lead in report["review_leads"]:
        lines.append(f"| {_markdown_cell(lead['scope'])} | {_markdown_cell(lead['fix_count'])} | {_markdown_cell(lead['test_count'])} | Review needed (CKR5: not proven) |")
    if report["review_leads"]:
        lines.extend([
            "", "### Draft review checklist", "",
            "For each lead, verify the underlying evidence and check for an existing lesson "
            "before proposing a new one. If the evidence does not support a reusable rule, stop.",
            "",
            "- **One reusable action:** state what to do and how to check it.",
            "- **When it applies:** describe the condition that makes the action necessary.",
            "- **When it does not apply:** give a similar case that should be excluded.",
            "- **One source-linked example:** keep PR-specific details here, not in the rule. "
            "Use the PR and the fix/test references in the report artifact.",
        ])
    lines.extend(["", "**No lesson candidate, Notion write, activation, merge authority, or closure authority was produced.**",
                  "Commit message patterns only identify possible review leads. They do not prove the fix's semantics, test success, existing lesson novelty, or reusable rule.", ""])
    return "\n".join(lines)


def _no_evidence_receipt(status: str, reason: str, sha: str) -> dict[str, Any]:
    return {
        "status": status, "reason_code": reason,
        "merge_sha": sha.lower() if SHA.fullmatch(sha) else None,
        "authority_created": False, "publication_authorized": False,
        "notion_write_performed": False, "github_write_performed": False,
        "lesson_proposal": None, "listed_commits_complete": False,
        "historical_head_coverage_complete": False, "historical_ci_or_review_examined": False,
    }


def _receipt_json(result: dict[str, Any]) -> str:
    return json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--merge-sha", required=True)
    parser.add_argument("--pr-number")
    parser.add_argument("--validation-run-id")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        number = _optional_decimal(args.pr_number, "pr-number-invalid")
        run_id = _optional_decimal(args.validation_run_id, "validation-run-id-invalid")
        reader = GitHubReader(args.repository, os.getenv("GITHUB_TOKEN", ""))
        result = build_report(reader, args.merge_sha, number, run_id)
        summary, payload = render_summary(result), _receipt_json(result)
    except Exception as exc:
        # At the CLI boundary only: never expose unexpected exception text.
        code = str(exc) if isinstance(exc, EvidenceError) else "report-generation-failed"
        result = _no_evidence_receipt("manual-review", code, args.merge_sha)
        summary, payload = render_summary(result), _receipt_json(result)
    path = Path(args.output)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    except OSError:
        # An unwritable output path cannot contain a receipt; emit it to stderr.
        print(_receipt_json(_no_evidence_receipt("manual-review", "receipt-write-failed", args.merge_sha)), file=sys.stderr, end="")
        return 2
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    try:
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(summary)
        else:
            print(summary)
    except OSError:
        result = _no_evidence_receipt("manual-review", "summary-write-failed", args.merge_sha)
        try:
            path.write_text(_receipt_json(result), encoding="utf-8")
        except OSError:
            print(_receipt_json(result), file=sys.stderr, end="")
        return 2
    return 2 if result["status"] == "manual-review" else 0


def _optional_decimal(value: str | None, reason: str) -> int | None:
    if value is None:
        return None
    if not re.fullmatch(r"[1-9][0-9]{0,18}", value):
        raise EvidenceError(reason)
    return int(value)


if __name__ == "__main__":
    sys.exit(main())
