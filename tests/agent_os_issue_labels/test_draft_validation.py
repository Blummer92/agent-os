from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

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


def _payload(path: Path = MINIMUM) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(payload: dict[str, object], *, form: Path = FORM, **kwargs):
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, form, MAP)
    return validate_issue_draft(draft, source, form, **kwargs)


def _form(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "form.yml"
    path.write_text(body, encoding="utf-8")
    return path


def test_valid_result_is_deterministic_eligible_and_never_authorized():
    first = _validate(_payload())
    second = _validate(_payload())

    assert first == second
    assert first.status == Status.PASS
    assert first.reason_codes == (DraftReasonCode.ELIGIBLE_VALID,)
    assert first.format_valid is True
    assert first.submission_eligible is True
    assert first.write_authorized is False
    assert first.mutation_performed is False
    assert validation_exit_code(first) == DraftExitCode.ELIGIBLE_SUCCESS
    assert validation_result_to_dict(first) == validation_result_to_dict(second)
    assert render_validation_preview(first) == render_validation_preview(second)


def test_missing_required_evidence_is_nonzero_manual_review():
    result = _validate(_payload(MISSING))

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.MISSING_REQUIRED_EVIDENCE in result.reason_codes
    assert result.submission_eligible is False
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


@pytest.mark.parametrize(
    ("mutate", "reason", "status"),
    [
        (
            lambda fields: fields.update(owner="owner:unknown-agent"),
            DraftReasonCode.UNKNOWN_OR_UNSUPPORTED_VALUE,
            Status.MANUAL_REVIEW,
        ),
        (
            lambda fields: fields.update(status="status:blocked"),
            DraftReasonCode.DUPLICATE_CANONICAL_FIELD,
            Status.MANUAL_REVIEW,
        ),
        (
            lambda fields: fields.update(
                owner=["owner:github-service-agent", "owner:qa-test-agent"]
            ),
            DraftReasonCode.CONFLICTING_OWNER,
            Status.MANUAL_REVIEW,
        ),
        (
            lambda fields: fields.update(
                **{"external-write": "external-write-requested"}
            ),
            DraftReasonCode.UNSAFE_EXTERNAL_WRITE,
            Status.FAIL,
        ),
    ],
)
def test_input_risks_have_stable_fail_closed_reasons(mutate, reason, status):
    payload = _payload()
    fields = dict(payload["fields"])
    mutate(fields)
    payload["fields"] = fields

    result = _validate(payload)

    assert result.status == status
    assert reason in result.reason_codes
    assert result.submission_eligible is False
    assert result.write_authorized is False
    assert result.mutation_performed is False


@pytest.mark.parametrize("heading", ["Primary owner", "Status"])
def test_parser_recognized_headings_route_to_manual_review(heading: str):
    payload = _payload()
    fields = dict(payload["fields"])
    fields["objective"] = (
        f"Describe the outcome\n### {heading}\nowner:qa-test-agent"
    )
    payload["fields"] = fields

    result = _validate(payload)

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.PARSER_ROUND_TRIP_AMBIGUITY in result.reason_codes
    assert any(heading in item for item in result.parser_ambiguity_evidence)
    assert result.submission_eligible is False


def test_local_duplicate_is_advisory_and_unavailable_labels_fail_closed():
    warning = _validate(
        _payload(),
        local_issue_summaries=("Add deterministic issue draft preview",),
    )
    unavailable = _validate(_payload(), available_labels=("agent-os",))

    assert warning.status == Status.WARN
    assert warning.reason_codes == (
        DraftReasonCode.ELIGIBLE_WARNING,
        DraftReasonCode.DUPLICATE_CANDIDATE_ADVISORY,
    )
    assert warning.submission_eligible is True
    assert validation_exit_code(warning) == DraftExitCode.ELIGIBLE_WARNING
    assert unavailable.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.UNAVAILABLE_LABEL in unavailable.reason_codes


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            """name: Test form
description: Test
body:
  - type: input
    id: objective
    attributes: {label: Repeated}
  - type: input
    id: owner
    attributes: {label: Repeated}
""",
            "duplicate field label: Repeated",
        ),
        (
            """name: Test form
description: Test
body:
  - type: input
    id: objective
    attributes: {label: Objective}
    validations: {required: true, future-rule: strict}
""",
            "unsupported validation",
        ),
        (
            """name: Test form
description: Test
body:
  - type: textarea
    id: objective
    attributes: {label: Objective, value: Default, render: shell}
  - type: dropdown
    id: owner
    attributes:
      label: Owner
      multiple: true
      options: [owner:github-service-agent, owner:qa-test-agent]
      default: 0
""",
            "unsupported renderer behavior",
        ),
        (
            """name: Test form
description: Test
body:
  - type: input
    id: objective
    attributes: {label: Objective}
    validations: []
  - type: dropdown
    id: bad.id
    attributes: {label: Choice, options: [None, true, valid]}
""",
            "malformed attributes or validations",
        ),
        (
            """name: Test form
description: Test
yes: forbidden
body:
  - type: input
    id: objective
    yes: forbidden
    attributes: {label: Objective, yes: forbidden}
    validations: {required: true, no: forbidden}
""",
            "unsupported top-level issue-form key",
        ),
        (
            """name: Test form
description: Test
body:
  - type: input
    id: objective
    attributes: {label: Objective}
  - type: upload
    id: screenshots
    attributes: {label: Upload screenshots}
""",
            "unsupported control 'upload'",
        ),
    ],
)
def test_schema_drift_cases_are_visible_and_not_eligible(
    tmp_path: Path, body: str, expected: str
):
    form = _form(tmp_path, body)
    source_fields = {
        "objective": "A",
        "owner": "owner:github-service-agent",
        "bad.id": "valid",
    }
    source = IssueDraftInput.from_mapping(
        {"title": "Example", "fields": source_fields}
    )
    draft = build_issue_draft(source, form, MAP)
    result = validate_issue_draft(draft, source, form)

    assert result.status == Status.MANUAL_REVIEW
    assert DraftReasonCode.ISSUE_FORM_SCHEMA_DRIFT in result.reason_codes
    assert any(expected in item for item in result.schema_drift_evidence)
    assert result.submission_eligible is False


def test_reason_order_is_stable():
    payload = _payload()
    fields = dict(payload["fields"])
    fields["status"] = "status:blocked"
    fields["external-write"] = "external-write-requested"
    payload["fields"] = fields

    result = _validate(payload)
    order = [code.value for code in DraftReasonCode]

    assert [code.value for code in result.reason_codes] == sorted(
        [code.value for code in result.reason_codes], key=order.index
    )


def test_cli_file_and_stdin_are_equivalent(monkeypatch, capsys):
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
    assert json.loads(file_output)["write_authorized"] is False


def test_cli_invalid_json_uses_stable_usage_exit(tmp_path: Path, capsys):
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")

    code = draft_cli.main(["--input", str(malformed)])

    assert code == DraftExitCode.INVALID_INPUT_OR_USAGE
    assert "unable to read structured draft input" in capsys.readouterr().err
