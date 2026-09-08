from pathlib import Path

import pytest
import yaml

from scripts.agent_os_issue_labels.issue_metadata import load_issue_form_schema


def _write_form(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "issue-form.yml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _valid_field() -> dict:
    return {
        "type": "input",
        "id": "valid-field",
        "attributes": {"label": "Valid field"},
        "validations": {"required": True},
    }


def test_issue_form_schema_routes_non_string_id_and_label_to_unsupported(tmp_path):
    payload = {
        "name": "Strictness fixture",
        "body": [
            _valid_field(),
            {
                "type": "input",
                "id": 123,
                "attributes": {"label": "Malformed id"},
            },
            {
                "type": "input",
                "id": "malformed-label",
                "attributes": {"label": {"not": "text"}},
            },
        ],
    }

    schema = load_issue_form_schema(_write_form(tmp_path, payload))

    assert tuple(field.field_id for field in schema.fields) == ("valid-field",)
    assert schema.unsupported_controls == (
        "body[1] input control id and label must be strings",
        "body[2] input control id and label must be strings",
    )


def test_issue_form_schema_rejects_non_string_collection_members(tmp_path):
    payload = {
        "name": "Strictness fixture",
        "labels": ["bug", 123],
        "body": [_valid_field()],
    }

    with pytest.raises(TypeError, match="expected a list of strings"):
        load_issue_form_schema(_write_form(tmp_path, payload))
