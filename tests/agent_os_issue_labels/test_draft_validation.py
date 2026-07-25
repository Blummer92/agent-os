from __future__ import annotations

import io
import json
from pathlib import Path

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels import draft_cli
from scripts.agent_os_issue_labels.draft import IssueDraftInput, build_issue_draft
from scripts.agent_os_issue_labels.validation import (
    DraftExitCode,
    DraftReasonCode,
    render_validation_preview,
    validate_issue_draft,
    validation_exit_code,
    validation_result_to_dict,
)

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURES = ROOT / "tests/fixtures/agent_os_issue_labels"
MINIMUM = FIXTURES / "draft_minimum_valid.json"
MISSING = FIXTURES / "draft_missing_required.json"


def _payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(payload: dict[str, object], **kwargs):
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    return validate_issue_draft(draft, source, FORM, **kwargs)


def test_valid_draft_is_submission_eligible_but_never_authorized():
    result = _validate(_payload(MINIMUM))

    assert result.status == Status.PASS
    assert result.reason_codes == (DraftReasonCode.ELIGIBLE_VALID,)
    assert result.format_valid is True
    assert result.submission_eligible is True
    assert result.write_authorized is False
    assert result.mutation_performed is False
    assert validation_exit_code(result) == DraftExitCode.ELIGIBLE_SUCCESS


def test_missing_required_evidence_is_nonzero_manual_review():
    result = _validate(_payload(MISSING))

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.MISSING_REQUIRED_EVIDENCE in result.reason_codes
    assert result.submission_eligible is False
    assert result.write_authorized is False
    assert validation_exit_code(result) == DraftExitCode.MANUAL_REVIEW


def test_malformed_structured_input_fails_closed():
    source = IssueDraftInput.from_mapping({"title": 12, "fields": []})
    draft = build_issue_draft(source, FORM, MAP)
    result = validate_issue_draft(draft, source, FORM)

    assert result.status == Status.FAIL
    assert DraftReasonCode.MALFORMED_STRUCTURED_INPUT in result.reason_codes
    assert result.format_valid is False
    assert result.submission_eligible is False
    assert validation_exit_code(result) == DraftExitCode.VALIDATION_FAILURE


def test_unknown_value_has_stable_manual_review_reason():
    payload = _payload(MINIMUM)
    fields = dict(payload["fields"])
    fields["owner"] = "owner:unknown-agent"
    payload["fields"] = fields

    result = _validate(payload)

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.UNKNOWN_OR_UNSUPPORTED_VALUE in result.reason_codes
    assert result.submission_eligible is False


def test_conflicting_owner_evidence_routes_to_manual_review():
    payload = _payload(MINIMUM)
    fields = dict(payload["fields"])
    fields["owner"] = ["owner:github-service-agent", "owner:qa-test-agent"]
    payload["fields"] = fields

    result = _validate(payload)

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.CONFLICTING_OWNER in result.reason_codes
    assert result.submission_eligible is False


def test_heading_like_multiline_content_routes_to_parser_manual_review():
    payload = _payload(MINIMUM)
    fields = dict(payload["fields"])
    fields["objective"] = "Describe the outcome\n### Primary owner\nowner:qa-test-agent"
    payload["fields"] = fields

    result = _validate(payload)

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.PARSER_ROUND_TRIP_AMBIGUITY in result.reason_codes
    assert result.parser_ambiguity_evidence
    assert result.submission_eligible is False


def test_duplicate_local_candidate_is_advisory_warning():
    result = _validate(
        _payload(MINIMUM),
        local_issue_summaries=("Add deterministic issue draft preview",),
    )

    assert result.status == Status.WARN
    assert result.reason_codes == (
        DraftReasonCode.ELIGIBLE_WARNING,
        DraftReasonCode.DUPLICATE_CANDIDATE_ADVISORY,
    )
    assert result.submission_eligible is True
    assert validation_exit_code(result) == DraftExitCode.ELIGIBLE_WARNING


def test_unavailable_label_is_manual_review_for_complete_local_set():
    result = _validate(_payload(MINIMUM), available_labels=("agent-os",))

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.UNAVAILABLE_LABEL in result.reason_codes
    assert result.submission_eligible is False


def test_external_write_request_is_hard_failure():
    payload = _payload(MINIMUM)
    fields = dict(payload["fields"])
    fields["external-write"] = "external-write-requested"
    payload["fields"] = fields

    result = _validate(payload)

    assert result.status == Status.FAIL
    assert DraftReasonCode.UNSAFE_EXTERNAL_WRITE in result.reason_codes
    assert result.write_authorized is False
    assert result.mutation_performed is False


def test_duplicate_schema_labels_route_to_manual_review(tmp_path: Path):
    form = tmp_path / "duplicate-label.yml"
    form.write_text(
        """name: Test form
description: Test
title: '[Agent OS] '
labels: [agent-os]
body:
  - type: input
    id: objective
    attributes: {label: Repeated}
    validations: {required: true}
  - type: input
    id: owner
    attributes: {label: Repeated}
    validations: {required: true}
""",
        encoding="utf-8",
    )
    source = IssueDraftInput.from_mapping(
        {"title": "Example", "fields": {"objective": "A", "owner": "B"}}
    )
    draft = build_issue_draft(source, form, MAP)
    result = validate_issue_draft(draft, source, form)

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.ISSUE_FORM_SCHEMA_DRIFT in result.reason_codes
    assert "duplicate field label: Repeated" in result.schema_drift_evidence


def test_unsupported_validation_shape_routes_to_manual_review(tmp_path: Path):
    form = tmp_path / "unsupported-validation.yml"
    form.write_text(
        """name: Test form
description: Test
title: '[Agent OS] '
labels: [agent-os]
body:
  - type: input
    id: objective
    attributes: {label: Objective}
    validations: {required: true, future-rule: strict}
""",
        encoding="utf-8",
    )
    source = IssueDraftInput.from_mapping(
        {"title": "Example", "fields": {"objective": "A"}}
    )
    draft = build_issue_draft(source, form, MAP)
    result = validate_issue_draft(draft, source, form)

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.ISSUE_FORM_SCHEMA_DRIFT in result.reason_codes
    assert any("unsupported validation" in item for item in result.schema_drift_evidence)


def test_reason_order_and_serialization_are_byte_deterministic():
    payload = _payload(MINIMUM)
    fields = dict(payload["fields"])
    fields["status"] = "status:blocked"
    fields["external-write"] = "external-write-requested"
    payload["fields"] = fields

    first = _validate(payload)
    second = _validate(payload)

    assert first == second
    assert validation_result_to_dict(first) == validation_result_to_dict(second)
    assert render_validation_preview(first) == render_validation_preview(second)
    order = [code.value for code in DraftReasonCode]
    assert [code.value for code in first.reason_codes] == sorted(
        [code.value for code in first.reason_codes], key=order.index
    )


def test_cli_file_and_stdin_validation_outputs_are_equivalent(monkeypatch, capsys):
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

    assert file_code == DraftExitCode.ELIGIBLE_SUCCESS
    assert stdin_code == DraftExitCode.ELIGIBLE_SUCCESS
    assert json.loads(file_output) == json.loads(stdin_output)
    assert json.loads(file_output)["submission_eligible"] is True
    assert json.loads(file_output)["write_authorized"] is False


def test_cli_invalid_json_uses_stable_invalid_input_exit(tmp_path: Path, capsys):
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")

    code = draft_cli.main(["--input", str(malformed)])

    assert code == DraftExitCode.INVALID_INPUT_OR_USAGE
    assert "unable to read structured draft input" in capsys.readouterr().err


def test_supported_github_behavior_not_implemented_by_renderer_fails_closed(tmp_path: Path):
    form = tmp_path / "behavioral.yml"
    form.write_text(
        """name: Test form
description: Test
title: '[Agent OS] '
labels: [agent-os]
body:
  - type: textarea
    id: objective
    attributes:
      label: Objective
      value: Default text
      render: shell
    validations: {required: true}
  - type: dropdown
    id: owner
    attributes:
      label: Owner
      multiple: true
      options: [owner:github-service-agent, owner:qa-test-agent]
      default: 0
    validations: {required: true}
""",
        encoding="utf-8",
    )
    source = IssueDraftInput.from_mapping(
        {
            "title": "Example",
            "fields": {
                "objective": "A",
                "owner": "owner:github-service-agent",
            },
        }
    )
    draft = build_issue_draft(source, form, MAP)
    result = validate_issue_draft(draft, source, form)

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.ISSUE_FORM_SCHEMA_DRIFT in result.reason_codes
    assert any("unsupported renderer behavior: value" in item for item in result.schema_drift_evidence)
    assert any("unsupported renderer behavior: render" in item for item in result.schema_drift_evidence)
    assert any("multiple selection is unsupported" in item for item in result.schema_drift_evidence)
    assert any("unsupported renderer behavior: default" in item for item in result.schema_drift_evidence)


def test_schema_types_ids_options_and_falsy_mappings_fail_closed(tmp_path: Path):
    form = tmp_path / "malformed-schema.yml"
    form.write_text(
        """name: Test form
description: Test
labels: [agent-os]
body:
  - type: input
    id: objective
    attributes: {label: Objective}
    validations: []
  - type: dropdown
    id: bad.id
    attributes:
      label: Choice
      options: [None, true, valid]
    validations: {required: true}
  - type: checkboxes
    id: safety
    attributes:
      label: Safety
      options:
        - {label: Confirm, required: yes}
""",
        encoding="utf-8",
    )
    source = IssueDraftInput.from_mapping(
        {
            "title": "Example",
            "fields": {
                "objective": "A",
                "bad.id": "valid",
                "safety": ["Confirm"],
            },
        }
    )
    draft = build_issue_draft(source, form, MAP)
    result = validate_issue_draft(draft, source, form)

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.ISSUE_FORM_SCHEMA_DRIFT in result.reason_codes
    assert any("malformed attributes or validations" in item for item in result.schema_drift_evidence)
    assert any("field id is invalid: bad.id" in item for item in result.schema_drift_evidence)
    assert any("reserved value: None" in item for item in result.schema_drift_evidence)
    assert any("dropdown option 1 is invalid" in item for item in result.schema_drift_evidence)
    assert any("required must be boolean" in item for item in result.schema_drift_evidence)


def test_yaml_boolean_like_keys_become_review_evidence_not_crashes(tmp_path: Path):
    form = tmp_path / "boolean-key.yml"
    form.write_text(
        """name: Test form
description: Test
yes: forbidden
body:
  - type: input
    id: objective
    yes: forbidden
    attributes:
      label: Objective
      yes: forbidden
    validations:
      required: true
      no: forbidden
""",
        encoding="utf-8",
    )
    source = IssueDraftInput.from_mapping(
        {"title": "Example", "fields": {"objective": "A"}}
    )
    draft = build_issue_draft(source, form, MAP)
    result = validate_issue_draft(draft, source, form)

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.ISSUE_FORM_SCHEMA_DRIFT in result.reason_codes
    assert any("unsupported top-level issue-form key" in item for item in result.schema_drift_evidence)
    assert any("unsupported element key" in item for item in result.schema_drift_evidence)
    assert any("unsupported attribute" in item for item in result.schema_drift_evidence)
    assert any("unsupported validation" in item for item in result.schema_drift_evidence)


def test_upload_control_is_visible_schema_drift(tmp_path: Path):
    form = tmp_path / "upload.yml"
    form.write_text(
        """name: Test form
description: Test
body:
  - type: input
    id: objective
    attributes: {label: Objective}
  - type: upload
    id: screenshots
    attributes:
      label: Upload screenshots
      description: Attach evidence
""",
        encoding="utf-8",
    )
    source = IssueDraftInput.from_mapping(
        {"title": "Example", "fields": {"objective": "A"}}
    )
    draft = build_issue_draft(source, form, MAP)
    result = validate_issue_draft(draft, source, form)

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.ISSUE_FORM_SCHEMA_DRIFT in result.reason_codes
    assert any("unsupported control 'upload'" in item for item in result.schema_drift_evidence)
