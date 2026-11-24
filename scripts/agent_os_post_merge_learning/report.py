"""Report grouped repair evidence from a *merged*, exact-sha GitHub PR.

This is a deterministic, read-only producer for review, not a lesson writer.
Commit labels are hints, never evidence that a reusable rule was proven.
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
SUBJECT = re.compile(r"^(feat|fix|test|docs|refactor|chore)(?:\(([a-zA-Z0-9_.-]{1,40})\))?!?:\s+(.{1,200})$")
MAX_COMMITS = 250
MAX_REFS_PER_GROUP = 20
MAX_GROUPS = 25
MAX_DISCUSSION_ITEMS = 200
MAX_CHECKS_PER_COMMIT = 100
MAX_FAILED_CHECK_REFS = 30


class EvidenceError(Exception):
    """Missing or inconsistent GitHub proof: never turn into a lesson."""


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

    def __init__(self, repository: str, token: str):
        self.repository = _repo(repository)
        if not token:
            raise EvidenceError("github-read-token-missing")
        self.token = token

    def get(self, path: str) -> Any:
        if not path.startswith("/") or ".." in path:
            raise EvidenceError("invalid-read-path")
        request = urllib.request.Request(
            "https://api.github.com/repos/" + self.repository + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.token,
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
    if not isinstance(declared, int) or isinstance(declared, bool) or not (0 < declared <= MAX_COMMITS):
        raise EvidenceError("commit-count-out-of-bounds")
    collected: list[dict[str, Any]] = []
    for page in range(1, 5):
        rows = reader.get(f"/pulls/{number}/commits?per_page=100&page={page}")
        if not isinstance(rows, list):
            raise EvidenceError("commit-list-malformed")
        collected.extend(rows)
        if len(collected) > MAX_COMMITS:
            raise EvidenceError("commit-list-out-of-bounds")
        if len(rows) < 100:
            break
    if len(collected) != declared:
        raise EvidenceError("commit-history-incomplete")
    ids = [_sha(row.get("sha")) for row in collected if isinstance(row, dict)]
    if len(ids) != declared or len(set(ids)) != declared:
        raise EvidenceError("commit-history-identity-invalid")
    return collected


def _paged_discussion(reader: GitHubReader, path: str) -> tuple[list[dict[str, Any]], bool]:
    """Return at most 200 items, explicitly indicating incomplete history."""
    values: list[dict[str, Any]] = []
    for page in range(1, 4):
        records = reader.get(f"{path}?per_page=100&page={page}")
        if not isinstance(records, list) or len(records) > 100 or any(not isinstance(x, dict) for x in records):
            raise EvidenceError("discussion-evidence-malformed")
        values.extend(records)
        if len(values) > MAX_DISCUSSION_ITEMS:
            return values[:MAX_DISCUSSION_ITEMS], True
        if len(records) < 100:
            return values, False
    return values[:MAX_DISCUSSION_ITEMS], True


def _check_history(reader: GitHubReader, sha: str) -> list[dict[str, Any]]:
    """Fetch all historical check runs, including reruns hidden by filter=latest."""
    values: list[dict[str, Any]] = []
    for page in range(1, 5):
        response = reader.get(f"/commits/{sha}/check-runs?filter=all&per_page=100&page={page}")
        if not isinstance(response, dict) or type(response.get("total_count")) is not int:
            raise EvidenceError("check-run-evidence-malformed")
        rows = response.get("check_runs")
        if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(row, dict) for row in rows):
            raise EvidenceError("check-run-evidence-malformed")
        values.extend(rows)
        if len(values) > 300:
            raise EvidenceError("check-run-evidence-incomplete")
        if len(rows) < 100:
            if len(values) != response["total_count"]:
                raise EvidenceError("check-run-evidence-incomplete")
            return values
    raise EvidenceError("check-run-evidence-incomplete")


def _legacy_statuses(reader: GitHubReader, sha: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for page in range(1, 4):
        rows = reader.get(f"/commits/{sha}/statuses?per_page=100&page={page}")
        if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(row, dict) for row in rows):
            raise EvidenceError("legacy-status-evidence-malformed")
        values.extend(rows)
        if len(rows) < 100:
            return values
    raise EvidenceError("legacy-status-evidence-incomplete")


def _review_and_ci_evidence(reader: GitHubReader, number: int, commits: list[dict[str, Any]]) -> dict[str, Any]:
    reviews, reviews_truncated = _paged_discussion(reader, f"/pulls/{number}/reviews")
    comments, comments_truncated = _paged_discussion(reader, f"/issues/{number}/comments")
    inline, inline_truncated = _paged_discussion(reader, f"/pulls/{number}/comments")
    timeline, timeline_truncated = _paged_discussion(reader, f"/issues/{number}/timeline")
    force_push = any(item.get("event") == "head_ref_force_pushed" for item in timeline)
    review_changes_requested = [item["html_url"] for item in reviews if item.get("state") == "CHANGES_REQUESTED" and isinstance(item.get("html_url"), str)]
    inline_refs = [item["html_url"] for item in inline if isinstance(item.get("html_url"), str) and item["html_url"].startswith(f"https://github.com/{reader.repository}/")]
    check_totals = {"success": 0, "failure": 0, "other": 0, "missing": 0, "attention": 0}
    legacy_totals = {"success": 0, "failure": 0, "pending": 0, "error": 0, "other": 0}
    failed_checks: list[dict[str, str]] = []
    valid_failed_refs_seen = missing_failed_refs = 0
    for entry in commits:
        sha = entry["sha"]
        checks = _check_history(reader, sha)
        statuses = _legacy_statuses(reader, sha)
        if not checks:
            check_totals["missing"] += 1
        for check in checks:
            outcome = check.get("conclusion")
            if outcome == "success":
                check_totals["success"] += 1
            elif outcome == "failure":
                check_totals["failure"] += 1
            else:
                check_totals["other"] += 1
            if outcome not in ("success", "neutral", "skipped"):
                check_totals["attention"] += 1
                url = check.get("html_url")
                if isinstance(url, str) and url.startswith(f"https://github.com/{reader.repository}/"):
                    valid_failed_refs_seen += 1
                    if len(failed_checks) < MAX_FAILED_CHECK_REFS:
                        failed_checks.append({"commit_sha": sha, "check_url": url})
                else:
                    missing_failed_refs += 1
        for status in statuses:
            state = status.get("state")
            legacy_totals[state if state in legacy_totals else "other"] += 1
    return {
        "review_count_observed": len(reviews), "issue_comment_count_observed": len(comments),
        "inline_comment_count_observed": len(inline), "inline_comment_refs": inline_refs,
        "review_history_truncated": reviews_truncated,
        "issue_comment_history_truncated": comments_truncated,
        "inline_comment_history_truncated": inline_truncated,
        "timeline_history_truncated": timeline_truncated,
        "rewritten_history_observed": force_push,
        "change_request_refs": review_changes_requested,
        "check_run_counts": check_totals, "legacy_status_counts": legacy_totals,
        "failed_check_refs": failed_checks,
        "failed_check_refs_unavailable": missing_failed_refs,
        "failed_check_refs_truncated": valid_failed_refs_seen > MAX_FAILED_CHECK_REFS,
        "independent_review_verified": False,
    }


def _resolve_pr(reader: GitHubReader, sha: str, explicit_number: int | None) -> dict[str, Any] | None:
    if explicit_number is not None:
        if not isinstance(explicit_number, int) or not (0 < explicit_number <= 2_147_483_647):
            raise EvidenceError("pr-number-invalid")
        return reader.get(f"/pulls/{explicit_number}")
    prs = reader.get(f"/commits/{sha}/pulls?per_page=100")
    if not isinstance(prs, list):
        raise EvidenceError("associated-prs-malformed")
    candidates = [p for p in prs if isinstance(p, dict) and p.get("merged_at") and p.get("merge_commit_sha") == sha]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise EvidenceError("associated-pr-ambiguous")
    return candidates[0]


def _validate_pr(pr: dict[str, Any], repo: str, sha: str) -> tuple[int, int]:
    if not isinstance(pr, dict) or not pr.get("merged_at") or pr.get("merged") is False:
        raise EvidenceError("pr-not-merged")
    if pr.get("merge_commit_sha") != sha:
        raise EvidenceError("merge-sha-mismatch")
    if pr.get("base", {}).get("ref") != "main":
        raise EvidenceError("base-not-main")
    if pr.get("base", {}).get("repo", {}).get("full_name") != repo:
        raise EvidenceError("base-repository-mismatch")
    number, count = pr.get("number"), pr.get("commits")
    # Exact type checks already reject bool; zero is invalid metadata.
    if (type(number) is not int or number < 1 or type(count) is not int
            or count <= 0):
        raise EvidenceError("pr-metadata-invalid")
    return number, count


def _validate_run(run: dict[str, Any] | None, sha: str) -> dict[str, Any]:
    if run is None:
        return {"state": "not-observed", "run_url": None}
    if not isinstance(run, dict) or run.get("head_sha") != sha or run.get("name") != "Agent OS Validation Gate" or run.get("event") != "push" or run.get("head_branch") != "main":
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
    return {"state": state, "run_url": run.get("html_url")}


def _subject(entry: dict[str, Any]) -> tuple[str, str] | None:
    commit = entry.get("commit")
    if not isinstance(commit, dict) or not isinstance(commit.get("message"), str):
        raise EvidenceError("commit-message-invalid")
    line = commit["message"].split("\n", 1)[0]
    match = SUBJECT.fullmatch(line)
    if match is None:
        return None
    kind, scope, _description = match.groups()
    return kind, (scope or "unscoped").casefold()


def _group_history(commits: list[dict[str, Any]], repository: str, number: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    groups: dict[str, dict[str, Any]] = {}
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
        group = groups.setdefault(scope, {"scope": scope, "fix_shas": [], "test_shas": []})
        group[f"{kind}_shas"].append(entry["sha"])
    if len(groups) > MAX_GROUPS:
        raise EvidenceError("learning-group-budget-exceeded")
    results = []
    for scope, group in sorted(groups.items()):
        if not group["fix_shas"]:
            continue
        fix_shas = group["fix_shas"]
        test_shas = group["test_shas"]
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
            signal=LearningSignal.REPEATED_REPAIR if len(fix_shas) > 1 else LearningSignal.SUBSTANTIVE_REVIEW_FINDING,
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
    repo = reader.repository
    pr = _resolve_pr(reader, sha, pr_number)
    if pr is None:
        return {"status": "not-applicable", "reason_code": "push-without-merged-pr", "merge_sha": sha, "authority_created": False}
    number, expected_count = _validate_pr(pr, repo, sha)
    if pr_number is not None and pr_number != number:
        raise EvidenceError("requested-pr-identity-mismatch")
    commits = _commits(reader, number, expected_count)
    if validation_run_id is not None and (type(validation_run_id) is not int or validation_run_id < 1):
        raise EvidenceError("validation-run-id-invalid")
    run = reader.get(f"/actions/runs/{validation_run_id}") if validation_run_id is not None else None
    if validation_run_id is not None and run is None:
        raise EvidenceError("validation-run-evidence-missing")
    validation = _validate_run(run, sha)
    groups, kinds = _group_history(commits, repo, number)
    supporting = _review_and_ci_evidence(reader, number, commits)
    return {
        "schema_version": 1, "repository": repo, "pr_number": number,
        "merge_sha": sha, "pr_url": f"https://github.com/{repo}/pull/{number}",
        "listed_commits_complete": True, "historical_head_coverage_complete": False,
        "analyzer_sha": os.environ.get("GITHUB_SHA") or None,
        "analyzer_workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF") or None,
        "commit_count": expected_count,
        "all_commit_shas": [entry["sha"] for entry in commits],
        "commit_kind_counts": kinds, "validation": validation,
        "supporting_evidence": supporting,
        "review_leads": groups, "status": ("review-needed" if (groups or validation["state"] != "success"
            or supporting["check_run_counts"]["attention"] or supporting["change_request_refs"]
            or supporting["inline_comment_count_observed"] or supporting["rewritten_history_observed"]
            or supporting["legacy_status_counts"]["failure"] or supporting["legacy_status_counts"]["error"]
            or supporting["legacy_status_counts"]["pending"]
            or supporting["review_history_truncated"] or supporting["issue_comment_history_truncated"]
            or supporting["inline_comment_history_truncated"] or supporting["timeline_history_truncated"]
            or supporting["failed_check_refs_unavailable"] or supporting["failed_check_refs_truncated"])
            else "no-repair-leads-observed"),
        "lesson_proposal": None, "existing_lesson_duplicate_review": "not-run",
        "notion_write_performed": False, "github_write_performed": False,
        "publication_authorized": False, "merge_authorized": False,
        "closure_authorized": False, "authority_created": False,
    }


def _markdown_cell(value: str) -> str:
    """Escape untrusted identifiers in Markdown rows and notes."""
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_summary(report: dict[str, Any]) -> str:
    if report["status"] == "not-applicable":
        return "## Post-merge learning\nNo uniquely linked merged PR was found for this push. No lesson created.\n"
    lines = ["## Read-only post-merge learning analysis", "",
             f"- PR: {report['pr_url']}", f"- Merge SHA: {report['merge_sha']}",
             f"- Complete PR commit list: **{report['commit_count']}**",
             f"- Exact merge validation: **{report['validation']['state']}**",
             f"- Repair review leads: **{len(report['review_leads'])}**",
             f"- Historical failed CI checks: **{report['supporting_evidence']['check_run_counts']['failure']}** (review-only)",
             f"- Prior change-request reviews: **{len(report['supporting_evidence']['change_request_refs'])}** (review-only)",
             f"- Discussion history truncated: **{report['supporting_evidence']['review_history_truncated'] or report['supporting_evidence']['issue_comment_history_truncated']}**",
             f"- Failed check links unavailable: **{report['supporting_evidence']['failed_check_refs_unavailable']}**", "",
             "| Commit scope | Fix commits | Test commits | Disposition |",
             "| --- | ---: | ---: | --- |"]
    for lead in report["review_leads"]:
        lines.append(f"| {_markdown_cell(lead['scope'])} | {lead['fix_count']} | {lead['test_count']} | Review needed (CKR5: not proven) |")
    lines.extend(["", "**No lesson candidate, Notion write, activation, merge authority, or closure authority was produced.**",
                  "Commit message patterns only identify possible review leads. They do not prove the fix's semantics, test success, existing lesson novelty, or reusable rule.", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--merge-sha", required=True)
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--validation-run-id", type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        reader = GitHubReader(args.repository, os.getenv("GITHUB_TOKEN", ""))
        result = build_report(reader, args.merge_sha, args.pr_number, args.validation_run_id)
    except EvidenceError as exc:
        result = {"status": "manual-review", "reason_code": str(exc), "merge_sha": args.merge_sha,
                  "authority_created": False, "publication_authorized": False,
                  "notion_write_performed": False, "github_write_performed": False}
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    summary = render_summary(result) if result["status"] != "manual-review" else (
        "## Post-merge learning: manual review required\nEvidence is incomplete or invalid: " + _markdown_cell(result["reason_code"]) + ". No lesson created.\n"
    )
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(summary)
    else:
        print(summary)
    return 0 if result["status"] != "manual-review" else 2


if __name__ == "__main__":
    sys.exit(main())
