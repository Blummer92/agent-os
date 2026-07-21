from __future__ import annotations

from .models import AcceptanceReport, LinkedIssueParseStatus, Status

# Fixed compatibility line for the informational reuse-evidence section (#248 §7).
# Kept as one rendered line; states the evidence/authorization boundary plainly so
# an informational manual-review entry is never mistaken for a readiness decision.
_INFORMATIONAL_NOTICE = (
    "Reusable-capability evidence is informational only; it does not authorize "
    "implementation, repository writes, readiness changes, or merge, and matching "
    "registry provenance proves only same-snapshot identity, not correctness, "
    "compatibility, ownership, approval, or readiness."
)


def render_report(report: AcceptanceReport) -> str:
    status = _linked_issue_status(report)
    if status == LinkedIssueParseStatus.RESOLVED:
        linked_issue = f"#{report.linked_issue}"
    elif status == LinkedIssueParseStatus.MANUAL_REVIEW:
        linked_issue = "unresolved"
    else:
        linked_issue = "none detected"

    lines = [
        "Issue Acceptance Report",
        f"Linked issue: {linked_issue}",
        f"Linked issue status: {status.value}",
        f"Overall result: {report.overall_status.value}",
        "Checks:",
    ]
    for check in report.checks:
        lines.append(f"- {check.name}: {check.status.value} - {check.message}")
        for item in check.evidence:
            lines.append(f"  - evidence: {item}")
    lines.extend([
        "Manual review items:",
        *_bullets(report.manual_review_items),
        "Evidence:",
        *_bullets(report.evidence),
        "Blockers:",
        *_bullets(report.blockers),
        "Remaining risks:",
        *_bullets(report.remaining_risks),
    ])
    if report.informational_checks:
        lines.append("Reusable-capability evidence (informational):")
        lines.append(f"- notice: {_INFORMATIONAL_NOTICE}")
        for check in report.informational_checks:
            lines.append(f"- {check.name}: {check.status.value} - {check.message}")
            for item in check.evidence:
                lines.append(f"  - evidence: {item}")
    return "\n".join(lines) + "\n"


def _linked_issue_status(report: AcceptanceReport) -> LinkedIssueParseStatus:
    if report.linked_issue_result is not None:
        return report.linked_issue_result.status
    if report.linked_issue is not None:
        return LinkedIssueParseStatus.RESOLVED
    return LinkedIssueParseStatus.NONE


def _bullets(values: list[str]) -> list[str]:
    if not values:
        return ["- none"]
    return [f"- {value}" for value in values]


def exit_code_for(status: Status) -> int:
    return 1 if status == Status.FAIL else 0
