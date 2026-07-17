from pathlib import Path

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels.checker import evaluate_issue_labels
from scripts.agent_os_issue_labels.issue_metadata import load_issue_form_fields, parse_issue_form_body
from scripts.agent_os_issue_labels.label_map import expected_labels, load_label_map
from scripts.agent_os_issue_labels.report import render_label_report

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

_NEEDS_DECISION_BODY = """
### Phase

not-applicable

### Epic

needs-decision

### Owner agent

needs-decision

### Status

status:needs-decision

### Type

- type:tooling

### Source-of-truth surface

needs-decision

### External write surface

needs-decision
"""

_EXTERNAL_WRITE_BODY = """
### Phase

not-applicable

### Epic

epic:issue-acceptance

### Owner agent

owner:qa-test-agent

### Status

status:blocked

### Type

- type:tooling

### Source-of-truth surface

GitHub

### External write surface

external-write-requested
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


def test_load_label_map_and_expected_labels():
    fields = load_issue_form_fields(FORM)
    metadata = parse_issue_form_body(_READY_BODY, fields)
    labels, unknown = expected_labels(metadata, load_label_map(MAP))
    assert unknown == []
    assert "agent-os" in labels
    assert "owner:qa-test-agent" in labels
    assert "type:validation" in labels


def test_ready_issue_labels_pass():
    report = evaluate_issue_labels(_READY_BODY, _READY_LABELS, FORM, MAP)
    assert report.overall_status == Status.PASS
    assert not report.manual_review_items


def test_missing_expected_labels_warns_without_failing():
    labels = ["agent-os", "epic:issue-acceptance", "status:ready", "type:tooling"]
    report = evaluate_issue_labels(_READY_BODY, labels, FORM, MAP)
    assert report.overall_status == Status.WARN
    assert any("missing=" in item for check in report.checks for item in check.evidence)


def test_needs_decision_routes_to_manual_review():
    labels = ["agent-os", "status:needs-decision", "type:tooling"]
    report = evaluate_issue_labels(_NEEDS_DECISION_BODY, labels, FORM, MAP)
    assert report.overall_status == Status.MANUAL_REVIEW
    assert any("needs-decision" in item for item in report.manual_review_items)


def test_external_write_routes_to_manual_review():
    labels = [
        "agent-os",
        "epic:issue-acceptance",
        "owner:qa-test-agent",
        "status:blocked",
        "status:needs-decision",
        "type:tooling",
    ]
    report = evaluate_issue_labels(_EXTERNAL_WRITE_BODY, labels, FORM, MAP)
    assert report.overall_status == Status.MANUAL_REVIEW
    assert "external-write field requests review before any automation" in report.manual_review_items


def test_report_reuses_ia_style_shape():
    report = evaluate_issue_labels(_READY_BODY, _READY_LABELS, FORM, MAP)
    rendered = render_label_report(report)
    assert "Issue Acceptance Report" in rendered
    assert "Overall result: pass" in rendered
    assert "expected labels:" in rendered
