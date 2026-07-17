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
from .models import AcceptanceInput, AcceptanceReport, CheckResult, Status, strongest_status
from .parse_issue import parse_issue_metadata
from .parse_pr import parse_linked_issue


def evaluate_acceptance(data: AcceptanceInput, pr_title: str = "") -> AcceptanceReport:
    """Run IA2 v1 checks against offline issue, PR, file-list, and diff inputs."""
    metadata = parse_issue_metadata(data.issue_body)
    checks: list[CheckResult] = [
        linked_issue.check(data.pr_body, pr_title),
        final_report_fields.check(data.pr_body),
        required_files.check(metadata, data.changed_files),
        forbidden_paths.check(metadata, data.changed_files),
        required_docs.check(metadata, data.changed_files),
        required_tests.check(metadata, data.changed_files, data.pr_body),
        banned_patterns.check(metadata, data.diff_text),
        validation_commands.check(data.pr_body),
    ]

    manual_review_items = list(metadata.manual_review)
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
    ]
    blockers = [check.message for check in checks if check.status == Status.FAIL]
    risks = [check.message for check in checks if check.status in {Status.WARN, Status.MANUAL_REVIEW}]

    return AcceptanceReport(
        linked_issue=parse_linked_issue(data.pr_body, pr_title),
        overall_status=overall,
        checks=checks,
        manual_review_items=manual_review_items,
        evidence=evidence,
        blockers=blockers,
        remaining_risks=risks,
    )
