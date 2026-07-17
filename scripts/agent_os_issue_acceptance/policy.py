from __future__ import annotations

from .checks import (
    banned_patterns,
    final_report_fields,
    forbidden_paths,
    linked_issue,
    required_docs,
    required_files,
    required_tests,
    validation_commands,
)
from .models import (
    AcceptanceInput,
    AcceptanceReport,
    CheckResult,
    LinkedIssueParseStatus,
    Status,
    strongest_status,
)
from .parse_issue import parse_issue_metadata
from .parse_pr import parse_linked_issue_result


def evaluate_acceptance(data: AcceptanceInput, pr_title: str = "") -> AcceptanceReport:
    """Run IA2 v1 checks against offline issue, PR, file-list, and diff inputs."""
    metadata = parse_issue_metadata(data.issue_body)
    linked_issue_result = parse_linked_issue_result(data.pr_body, pr_title)
    checks: list[CheckResult] = [
        linked_issue.check(parse_result=linked_issue_result),
        final_report_fields.check(data.pr_body),
        required_files.check(metadata, data.changed_files),
        forbidden_paths.check(metadata, data.changed_files),
        required_docs.check(metadata, data.changed_files),
        required_tests.check(metadata, data.changed_files, data.pr_body),
        banned_patterns.check(metadata, data.diff_text),
        validation_commands.check(data.pr_body),
    ]

    manual_review_items = list(metadata.manual_review)
    if linked_issue_result.status == LinkedIssueParseStatus.MANUAL_REVIEW:
        manual_review_items.extend(
            f"Linked issue: {reason}" for reason in linked_issue_result.reasons
        )
    if not metadata.present:
        manual_review_items.append("Issue metadata block is missing or ambiguous.")
    if metadata.external_writes and metadata.external_writes != "none":
        manual_review_items.append(f"External writes declared: {metadata.external_writes}")

    overall = strongest_status(checks)
    if manual_review_items and overall not in {Status.FAIL, Status.MANUAL_REVIEW}:
        overall = Status.MANUAL_REVIEW

    evidence = [
        f"changed_files={len(data.changed_files)}",
        f"metadata_present={metadata.present}",
        f"linked_issue_status={linked_issue_result.status.value}",
    ]
    evidence.extend(
        f"linked_issue_reason={reason}" for reason in linked_issue_result.reasons
    )
    blockers = [check.message for check in checks if check.status == Status.FAIL]
    risks = [
        check.message
        for check in checks
        if check.status in {Status.WARN, Status.MANUAL_REVIEW}
    ]

    return AcceptanceReport(
        linked_issue=(
            linked_issue_result.issue_number
            if linked_issue_result.status == LinkedIssueParseStatus.RESOLVED
            else None
        ),
        linked_issue_result=linked_issue_result,
        overall_status=overall,
        checks=checks,
        manual_review_items=manual_review_items,
        evidence=evidence,
        blockers=blockers,
        remaining_risks=risks,
    )
