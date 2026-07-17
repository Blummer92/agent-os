from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"


def test_agent_os_issue_form_schema_is_valid_offline():
    data = yaml.safe_load(FORM.read_text(encoding="utf-8"))

    assert isinstance(data, dict)
    assert data.get("name")
    assert data.get("description")
    assert "about" not in data
    assert isinstance(data.get("body"), list) and data["body"]

    valid_types = {"markdown", "input", "textarea", "dropdown", "checkboxes"}
    interactive_types = valid_types - {"markdown"}
    ids: list[str] = []

    for item in data["body"]:
        assert isinstance(item, dict)
        item_type = item.get("type")
        assert item_type in valid_types
        assert isinstance(item.get("attributes"), dict)

        if item_type in interactive_types:
            field_id = item.get("id")
            assert isinstance(field_id, str) and field_id
            ids.append(field_id)
            assert item["attributes"].get("label")

        if item_type == "dropdown":
            options = item["attributes"].get("options")
            assert isinstance(options, list) and options
            assert all(isinstance(option, str) and option.strip() for option in options)

        if item_type == "checkboxes":
            options = item["attributes"].get("options")
            assert isinstance(options, list) and options
            for option in options:
                assert isinstance(option, dict)
                assert isinstance(option.get("label"), str) and option["label"].strip()
                assert option.get("required") is True

        validations = item.get("validations")
        if validations is not None:
            assert isinstance(validations, dict)
            assert set(validations) <= {"required"}
            assert isinstance(validations.get("required"), bool)

    assert len(ids) == len(set(ids))
