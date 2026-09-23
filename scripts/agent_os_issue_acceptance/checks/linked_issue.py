from __future__ import annotations

from ..models import CheckResult, LinkedIssueParseResult, LinkedIssueParseStatus, Status
from ..parse_pr import parse_linked_issue_result


def check(
    pr_body: str = "",
    pr_title: str = "",
    parse_result: LinkedIssueParseResult | None = None,
) -> CheckResult:
    result = parse_result or parse_linked_issue_result(pr_body, pr_title)
    evidence = _evidence(result)

    if result.status == LinkedIssueParseStatus.NONE:
        return CheckResult(
            "linked issue",
            Status.FAIL,
            "No linked issue reference was detected.",
            evidence,
        )
    if result.status == LinkedIssueParseStatus.MANUAL_REVIEW:
        message = result.reasons[0] if result.reasons else "Linked issue evidence requires manual review."
        return CheckResult("linked issue", Status.MANUAL_REVIEW, message, evidence)
    return CheckResult(
        "linked issue",
        Status.PASS,
        f"Detected one authoritative linked issue: #{result.issue_number}.",
        evidence,
    )


def _evidence(result: LinkedIssueParseResult) -> list[str]:
    evidence = [f"parser_status={result.status.value}"]
    for candidate in result.explicit_candidates:
        evidence.append(
            f"explicit source={candidate.source} keyword={candidate.keyword} "
            f"target={candidate.normalized_target}"
        )
    for candidate in result.bare_references:
        label = candidate.keyword or "bare"
        evidence.append(
            f"non_authoritative source={candidate.source} kind={label} "
            f"target={candidate.normalized_target}"
        )
    evidence.extend(f"reason={reason}" for reason in result.reasons)
    return evidence
