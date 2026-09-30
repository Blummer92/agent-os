from __future__ import annotations

from ..models import CheckResult, LinkedIssueParseResult, LinkedIssueParseStatus, Status
from ..parse_pr import (
    GitHubEffectiveClosingReference,
    detect_github_effective_closing_references,
    parse_linked_issue_result,
)


def check(
    pr_body: str = "",
    pr_title: str = "",
    parse_result: LinkedIssueParseResult | None = None,
) -> CheckResult:
    result = parse_result or parse_linked_issue_result(pr_body, pr_title)
    # The canonical GitHub-closing-semantics detector (#3157): GitHub treats a
    # closing keyword anywhere in the title/body as a closing reference — even
    # negated prose such as "does not close #123" — while the authoritative
    # parser above keeps stricter #2160 routing semantics. Both are reported.
    closing = detect_github_effective_closing_references(pr_body, pr_title)
    evidence = _evidence(result, closing)

    if result.status == LinkedIssueParseStatus.NONE:
        return CheckResult(
            "linked issue",
            Status.FAIL,
            "No linked issue reference was detected.",
            evidence,
        )
    if result.status == LinkedIssueParseStatus.MANUAL_REVIEW:
        message = result.reasons[0] if result.reasons else "Linked issue evidence requires manual review."
        if closing:
            names = ", ".join(f"{reference.keyword} {reference.target}" for reference in closing)
            message = (
                f"{message} GitHub-effective closing references detected ({names}); "
                "merge admission rejects any closing reference whose target is not authorized."
            )
        return CheckResult("linked issue", Status.MANUAL_REVIEW, message, evidence)
    return CheckResult(
        "linked issue",
        Status.PASS,
        f"Detected one authoritative linked issue: #{result.issue_number}.",
        evidence,
    )


def _evidence(
    result: LinkedIssueParseResult,
    closing: tuple[GitHubEffectiveClosingReference, ...] = (),
) -> list[str]:
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
    for reference in closing:
        evidence.append(
            f"github_effective_closing keyword={reference.keyword} "
            f"target={reference.target} source={reference.source}"
        )
    evidence.extend(f"reason={reason}" for reason in result.reasons)
    return evidence
