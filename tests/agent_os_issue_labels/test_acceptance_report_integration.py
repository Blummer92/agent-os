from pathlib import Path

from scripts.agent_os_issue_acceptance.models import AcceptanceReport, Status
from scripts.agent_os_issue_labels.checker import evaluate_issue_labels
from scripts.agent_os_issue_labels.report import render_label_report, report_to_dict

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"

_READY_BODY = """
### Phase

implementation-phase-1

### Epic

epic:issue-acceptance

### Owner agent

owner:qa-test-agent

### Status

status:ready

### Type

- type:tooling
- type:validation

### Source-of-truth surface

GitHub

### External write surface

no-external-write
"""

_READY_LABELS = [
    "agent-os",
    "implementation-phase-1",
    "epic:issue-acceptance",
    "owner:qa-test-agent",
    "status:ready",
    "type:tooling",
    "type:validation",
]


def test_label_checker_returns_ia2_acceptance_report_model():
    report = evaluate_issue_labels(_READY_BODY, _READY_LABELS, FORM, MAP)

    assert isinstance(report, AcceptanceReport)
    assert report.overall_status == Status.PASS
    assert any(check.name == "label governance boundary" for check in report.checks)
    assert any("AcceptanceReport" in item for item in report.evidence)


def test_label_findings_render_in_ia_acceptance_report_shape():
    report = evaluate_issue_labels(_READY_BODY, ["agent-os", "status:ready"], FORM, MAP)
    rendered = render_label_report(report)

    assert "Issue Acceptance Report" in rendered
    assert "Overall result: warn" in rendered
    assert "- expected labels: warn - expected labels are missing" in rendered
    assert "Manual review items:" in rendered
    assert "Remaining risks:" in rendered


def test_label_findings_do_not_imply_approval_or_readiness():
    report = evaluate_issue_labels(_READY_BODY, _READY_LABELS, FORM, MAP)
    data = report_to_dict(report)

    assert data["overall_status"] == "pass"
    assert any(
        "do not authorize merge, readiness, approval" in risk
        for risk in data["remaining_risks"]
    )
    assert any(
        check["name"] == "label governance boundary" and check["status"] == "pass"
        for check in data["checks"]
    )


def test_external_write_label_finding_stays_manual_review():
    body = _READY_BODY.replace("no-external-write", "external-write-requested")
    labels = _READY_LABELS + ["status:needs-decision"]
    report = evaluate_issue_labels(body, labels, FORM, MAP)

    assert report.overall_status == Status.MANUAL_REVIEW
    assert "external-write field requests review before any automation" in report.manual_review_items
    assert any("source-of-truth changes" in risk for risk in report.remaining_risks)
