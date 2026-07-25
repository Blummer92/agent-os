from __future__ import annotations

import io
import json
from pathlib import Path

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels import draft_cli
from scripts.agent_os_issue_labels.draft import (
    IssueDraftInput,
    build_issue_draft,
    draft_result_to_dict,
    render_draft_preview,
)
from scripts.agent_os_issue_labels.issue_metadata import (
    load_issue_form_fields,
    load_issue_form_schema,
    metadata_contract,
    missing_metadata_fields,
    parse_issue_form_body,
)

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURES = ROOT / "tests/fixtures/agent_os_issue_labels"
MINIMUM = FIXTURES / "draft_minimum_valid.json"
COMPLETE = FIXTURES / "draft_complete_valid.json"
MISSING = FIXTURES / "draft_missing_required.json"
UNKNOWN = FIXTURES / "draft_unknown_value.json"


def _payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build(path: Path):
    return build_issue_draft(_payload(path), FORM, MAP)


def test_schema_loader_preserves_canonical_form_order_and_metadata():
    schema = load_issue_form_schema(FORM)

    assert schema.name == "Agent OS task"
    assert schema.title_prefix == "[Agent OS] "
    assert schema.default_labels == ("agent-os", "status:needs-decision")
    assert len(schema.fields) == 19
    assert [field.field_id for field in schema.fields[:5]] == [
        "tier",
        "objective",
        "owner",
        "readiness",
        "source-of-truth",
    ]
    assert schema.fields[3].canonical_id == "status"
    assert schema.fields[-1].field_id == "safety"
    assert len(schema.fields[-1].required_options) == 3
    assert schema.unsupported_controls == ()


def test_existing_field_loader_remains_backward_compatible():
    fields = load_issue_form_fields(FORM)

    assert fields["tier"] == "Issue tier"
    assert fields["status"] == "Readiness candidate"
    assert fields["documentation_impact"] == "Documentation impact"
    assert fields["required_docs"] == "Required documentation paths or bounded areas"


def test_shared_metadata_contract_is_strict_and_reports_missing_fields():
    tiered = {
        "tier": ["tier:1-standard-implementation"],
        "owner": ["owner:qa-test-agent"],
        "status": ["status:ready"],
        "source-of-truth": ["GitHub"],
        "external-write": ["no-external-write"],
    }
    legacy = {
        "phase": ["implementation-phase-1"],
        "epic": ["epic:issue-acceptance"],
        "owner": ["owner:qa-test-agent"],
        "status": ["status:ready"],
        "type": ["type:tooling"],
        "source-of-truth": ["GitHub"],
        "external-write": ["no-external-write"],
    }

    assert metadata_contract(tiered) == "tiered"
    assert metadata_contract(legacy) == "legacy"
    assert metadata_contract({"tier": tiered["tier"]}) == "incomplete"
    missing = missing_metadata_fields({"tier": tiered["tier"]})
    assert "owner" in missing["tiered"]
    assert "phase" in missing["legacy"]


def test_minimum_valid_draft_is_byte_deterministic_and_non_authorizing():
    first = _build(MINIMUM)
    second = _build(MINIMUM)

    assert first == second
    assert first.title == "[Agent OS] Add deterministic issue draft preview"
    assert first.metadata_contract == "tiered"
    assert first.report.overall_status == Status.PASS
    assert first.proposed_labels == (
        "agent-os",
        "owner:github-service-agent",
        "status:ready",
    )
    assert first.mutation_performed is False
    assert first.write_authorized is False
    assert first.body == second.body
    assert render_draft_preview(first) == render_draft_preview(second)
    assert draft_result_to_dict(first) == draft_result_to_dict(second)


def test_renderer_uses_form_order_and_round_trips_through_existing_parser():
    result = _build(MINIMUM)
    schema = load_issue_form_schema(FORM)
    positions = [result.body.index(f"### {field.label}") for field in schema.fields]
    fields = load_issue_form_fields(FORM)
    metadata = parse_issue_form_body(result.body, fields)

    assert positions == sorted(positions)
    assert metadata["tier"] == ["tier:1-standard-implementation"]
    assert metadata["owner"] == ["owner:github-service-agent"]
    assert metadata["status"] == ["status:ready"]
    assert metadata["source-of-truth"] == ["GitHub"]
    assert metadata["external-write"] == ["no-external-write"]
    assert "_No response_" in result.body


def test_complete_draft_preserves_unicode_multiline_and_existing_prefix():
    result = _build(COMPLETE)
    payload = draft_result_to_dict(result)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)

    assert result.title == "[Agent OS] Preserve Unicode and multiline issue evidence"
    assert "café — 東京" in result.body
    assert "Scope:\n- Preserve multiline text." in result.body
    assert "café — 東京" in encoded
    assert result.report.overall_status == Status.PASS
    assert result.proposed_labels == (
        "agent-os",
        "owner:github-service-agent",
        "status:blocked",
    )


def test_missing_required_fields_route_to_manual_review():
    result = _build(MISSING)

    assert result.report.overall_status == Status.MANUAL_REVIEW
    assert any("required field is missing: objective" in reason for reason in result.manual_review_reasons)
    assert any("required checkbox is not selected" in reason for reason in result.manual_review_reasons)
    assert result.write_authorized is False


def test_unknown_field_and_option_route_to_manual_review():
    result = _build(UNKNOWN)

    assert result.report.overall_status == Status.MANUAL_REVIEW
    assert "unknown input field: mystery-field" in result.manual_review_reasons
    assert any("unsupported option: owner:unknown-agent" in reason for reason in result.manual_review_reasons)
    assert any("unmapped value requires review" in reason for reason in result.manual_review_reasons)
    assert "owner:unknown-agent" not in result.proposed_labels


def test_duplicate_raw_and_canonical_field_inputs_route_to_manual_review():
    payload = _payload(MINIMUM)
    fields = dict(payload["fields"])
    fields["status"] = "status:blocked"
    payload["fields"] = fields

    result = build_issue_draft(payload, FORM, MAP)

    assert result.report.overall_status == Status.MANUAL_REVIEW
    assert any("multiple input fields map to status" in reason for reason in result.manual_review_reasons)
    assert "status:ready" in result.proposed_labels
    assert "status:blocked" not in result.proposed_labels


def test_unsupported_form_control_routes_to_manual_review(tmp_path: Path):
    form = tmp_path / "unsupported.yml"
    form.write_text(
        """name: Test form
description: Test
title: '[Agent OS] '
labels: [agent-os]
body:
  - type: dropdown
    id: tier
    attributes:
      label: Issue tier
      options: [tier:1-standard-implementation]
    validations: {required: true}
  - type: custom-control
    id: custom
    attributes:
      label: Custom
""",
        encoding="utf-8",
    )

    result = build_issue_draft(
        {"title": "Unsupported", "fields": {"tier": "tier:1-standard-implementation"}},
        form,
        MAP,
    )

    assert result.report.overall_status == Status.MANUAL_REVIEW
    assert any("unsupported control" in reason for reason in result.manual_review_reasons)


def test_issue_draft_input_is_immutable_normalized_evidence():
    draft_input = IssueDraftInput.from_mapping(
        {
            "title": "  Example\r\nTitle  ",
            "fields": {"objective": "  Line one\r\nLine two  "},
        }
    )

    assert draft_input.title == "Example\nTitle"
    assert draft_input.fields == (("objective", ("Line one\nLine two",)),)


def test_text_and_json_preview_derive_from_same_result():
    result = _build(MINIMUM)
    text = render_draft_preview(result)
    payload = draft_result_to_dict(result)

    assert payload["title"] in text
    assert payload["body"].rstrip("\n") in text
    assert payload["metadata_contract"] in text
    assert payload["write_authorized"] is False
    assert "Write authorized: no" in text
    assert "Preview evidence does not authorize issue creation" in text


def test_cli_file_and_stdin_inputs_are_equivalent(monkeypatch, capsys):
    common = [
        "--issue-form",
        str(FORM),
        "--label-map",
        str(MAP),
        "--format",
        "json",
    ]

    file_code = draft_cli.main(["--input", str(MINIMUM), *common])
    file_output = capsys.readouterr().out

    monkeypatch.setattr(
        draft_cli.sys,
        "stdin",
        io.StringIO(MINIMUM.read_text(encoding="utf-8")),
    )
    stdin_code = draft_cli.main(["--input", "-", *common])
    stdin_output = capsys.readouterr().out

    assert file_code == 0
    assert stdin_code == 0
    assert json.loads(file_output) == json.loads(stdin_output)
    assert json.loads(file_output)["write_authorized"] is False
