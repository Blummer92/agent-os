from __future__ import annotations

import json

from scripts.agent_os_issue_acceptance.models import AcceptanceReport
from scripts.agent_os_issue_acceptance.report import render_report


def render_label_report(report: AcceptanceReport) -> str:
    return render_report(report)


def report_to_dict(report: AcceptanceReport) -> dict:
    return {
        "linked_issue": report.linked_issue,
        "overall_status": report.overall_status.value,
        "checks": [
            {
                "name": check.name,
                "status": check.status.value,
                "message": check.message,
                "evidence": check.evidence,
            }
            for check in report.checks
        ],
        "manual_review_items": report.manual_review_items,
        "evidence": report.evidence,
        "blockers": report.blockers,
        "remaining_risks": report.remaining_risks,
    }


def render_json(report: AcceptanceReport) -> str:
    return json.dumps(report_to_dict(report), indent=2, sort_keys=True) + "\n"
