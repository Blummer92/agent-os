from __future__ import annotations

from .models import AcceptanceReport, Status


def render_report(report: AcceptanceReport) -> str:
    lines = [
        "Issue Acceptance Report",
        f"Linked issue: {('#' + str(report.linked_issue)) if report.linked_issue else 'none detected'}",
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
    return "\n".join(lines) + "\n"


def _bullets(values: list[str]) -> list[str]:
    if not values:
        return ["- none"]
    return [f"- {value}" for value in values]


def exit_code_for(status: Status) -> int:
    return 1 if status == Status.FAIL else 0
