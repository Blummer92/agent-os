from pathlib import Path

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels.checker import evaluate_issue_labels
from scripts.agent_os_issue_labels.issue_metadata import load_issue_form_fields, parse_issue_form_body
from scripts.agent_os_issue_labels.label_map import expected_labels, load_label_map
from scripts.agent_os_issue_labels.report import render_label_report

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"

_LEGACY_READY_BODY = """
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

_TIERED_READY_BODY = """
### Issue tier

tier:1-standard-implementation

### Primary owner

owner:qa-test-agent

### Readiness candidate

status:ready

### Source of truth

GitHub

### External write boundary

no-external-write
"""

_NEEDS_DECISION_BODY = """
### Issue tier

tier:2-governed-cross-system

### Primary owner

needs-decision

### Readiness candidate

status:needs-decision

### Source of truth

needs-decision

### External write boundary

needs-decision
"""

_EXTERNAL_WRITE_BODY = """
### Issue tier

tier:2-governed-cross-system

### Primary owner

owner:qa-test-agent

### Readiness candidate

status:blocked

### Source of truth

GitHub

### External write boundary

external-write-requested
"""

_LEGACY_READY_LABELS = [
    "agent-os",
    "implementation-phase-1",
    "epic:issue-acceptance",
    "owner:qa-test-agent",
    "status:ready",
    "type:tooling",
    "type:validation",
]

_TIERED_READY_LABELS = [
    "agent-os",
    "owner:qa-test-agent",
    "status:ready",
]


def test_legacy_form_still_maps_expected_labels():
    fields = load_issue_form_fields(FORM)
    metadata = parse_issue_form_body(_LEGACY_READY_BODY, fields)
    labels, unknown = expected_labels(metadata, load_label_map(MAP))

    assert unknown == []
    assert metadata["status"] == ["status:ready"]
    assert "implementation-phase-1" in labels
    assert "epic:issue-acceptance" in labels
    assert "owner:qa-test-agent" in labels
    assert "type:validation" in labels


def test_tiered_form_maps_aliases_without_new_tier_labels():
    fields = load_issue_form_fields(FORM)
    metadata = parse_issue_form_body(_TIERED_READY_BODY, fields)
    labels, unknown = expected_labels(metadata, load_label_map(MAP))

    assert unknown == []
    assert metadata["tier"] == ["tier:1-standard-implementation"]
    assert metadata["status"] == ["status:ready"]
    assert labels == set(_TIERED_READY_LABELS)


def test_documentation_fields_map_without_changing_label_contract():
    body = _TIERED_READY_BODY + """
### Documentation impact

docs-needs-decision

### Required documentation paths or bounded areas

01_Shared_Standards/github
bad//path

### Expected documentation change

Document the parser contract.

### Documentation exemption reason

_No response_

### Unrelated heading

ignored
"""
    fields = load_issue_form_fields(FORM)
    metadata = parse_issue_form_body(body, fields)
    labels, unknown = expected_labels(metadata, load_label_map(MAP))
    report = evaluate_issue_labels(body, _TIERED_READY_LABELS, FORM, MAP)

    assert metadata["documentation_impact"] == ["docs-needs-decision"]
    assert metadata["required_docs"] == ["01_Shared_Standards/github", "bad//path"]
    assert metadata["documentation_expected_change"] == ["Document the parser contract."]
    assert "documentation_exemption_reason" not in metadata
    assert "Unrelated heading" not in metadata
    assert labels == set(_TIERED_READY_LABELS)
    assert unknown == []
    assert report.overall_status == Status.PASS
    assert not report.manual_review_items
    assert "metadata contract: tiered" in report.evidence


def test_legacy_ready_issue_labels_pass():
    report = evaluate_issue_labels(_LEGACY_READY_BODY, _LEGACY_READY_LABELS, FORM, MAP)

    assert report.overall_status == Status.PASS
    assert not report.manual_review_items
    assert "metadata contract: legacy" in report.evidence


def test_tiered_ready_issue_labels_pass():
    report = evaluate_issue_labels(_TIERED_READY_BODY, _TIERED_READY_LABELS, FORM, MAP)

    assert report.overall_status == Status.PASS
    assert not report.manual_review_items
    assert "metadata contract: tiered" in report.evidence


def test_missing_expected_labels_warns_without_failing():
    labels = ["agent-os", "status:ready"]
    report = evaluate_issue_labels(_TIERED_READY_BODY, labels, FORM, MAP)

    assert report.overall_status == Status.WARN
    assert any("missing=" in item for check in report.checks for item in check.evidence)


def test_needs_decision_routes_to_manual_review():
    labels = ["agent-os", "status:needs-decision"]
    report = evaluate_issue_labels(_NEEDS_DECISION_BODY, labels, FORM, MAP)

    assert report.overall_status == Status.MANUAL_REVIEW
    assert any("needs-decision" in item for item in report.manual_review_items)


def test_external_write_routes_to_manual_review():
    labels = [
        "agent-os",
        "owner:qa-test-agent",
        "status:blocked",
        "status:needs-decision",
    ]
    report = evaluate_issue_labels(_EXTERNAL_WRITE_BODY, labels, FORM, MAP)

    assert report.overall_status == Status.MANUAL_REVIEW
    assert "external-write field requests review before any automation" in report.manual_review_items


def test_incomplete_contract_routes_to_manual_review():
    body = """
### Primary owner

owner:qa-test-agent

### Readiness candidate

status:ready
"""
    report = evaluate_issue_labels(body, ["agent-os", "owner:qa-test-agent", "status:ready"], FORM, MAP)

    assert report.overall_status == Status.MANUAL_REVIEW
    assert "metadata contract: incomplete" in report.evidence


def test_report_reuses_ia_style_shape():
    report = evaluate_issue_labels(_TIERED_READY_BODY, _TIERED_READY_LABELS, FORM, MAP)
    rendered = render_label_report(report)

    assert "Issue Acceptance Report" in rendered
    assert "Overall result: pass" in rendered
    assert "expected labels:" in rendered
