from pathlib import Path

from scripts.agent_os_issue_labels.issue_metadata import (
    load_issue_form_fields,
    load_issue_form_schema,
)

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"


def test_schema_adapter_preserves_form_order_and_canonical_aliases():
    schema = load_issue_form_schema(FORM)

    assert schema.title_prefix == "[Agent OS] "
    assert schema.default_labels == ("agent-os", "status:needs-decision")
    assert [field.source_id for field in schema.fields[:5]] == [
        "tier",
        "objective",
        "owner",
        "readiness",
        "source-of-truth",
    ]
    readiness = next(
        field for field in schema.fields if field.source_id == "readiness"
    )
    assert readiness.canonical_id == "status"
    assert readiness.required is True
    assert [option.label for option in readiness.options] == [
        "status:ready",
        "status:blocked",
        "status:needs-decision",
    ]


def test_checkbox_option_requirements_are_preserved():
    schema = load_issue_form_schema(FORM)
    safety = next(field for field in schema.fields if field.source_id == "safety")

    assert safety.field_type == "checkboxes"
    assert len(safety.options) == 3
    assert all(option.required for option in safety.options)


def test_legacy_fields_projection_remains_backward_compatible():
    fields = load_issue_form_fields(FORM)

    assert fields["status"] == "Readiness candidate"
    assert fields["documentation_impact"] == "Documentation impact"
