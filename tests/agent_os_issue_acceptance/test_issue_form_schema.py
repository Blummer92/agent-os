import re
from pathlib import Path

import yaml

from scripts.agent_os_issue_acceptance.path_contract import normalize_declared_path


ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"

_EXPECTED_EXISTING_FIELDS = {
    "tier": "Issue tier",
    "objective": "Objective and value",
    "owner": "Primary owner",
    "readiness": "Readiness candidate",
    "source-of-truth": "Source of truth",
    "external-write": "External write boundary",
    "scope": "Scope and non-goals",
    "files": "Allowed files, areas, or governed surfaces",
    "validation": "Required tests, validation, and documentation",
    "dependencies": "Dependencies and blockers",
    "acceptance": "Acceptance criteria and definition of done",
    "tier2-controls": "Tier 2 controls, when applicable",
    "safety": "Safety confirmation",
}

_PRIOR_SCOPE_FIELDS = {
    "prior-scope-review": (
        "Prior scope, duplicate, and supersession review",
        "textarea",
        True,
    ),
    "refactor-evidence": (
        "Refactor or consolidation evidence, when applicable",
        "textarea",
        False,
    ),
}

_DOCUMENTATION_FIELDS = {
    "documentation-impact": ("Documentation impact", "dropdown", True),
    "required-docs": (
        "Required documentation paths or bounded areas",
        "textarea",
        False,
    ),
    "documentation-expected-change": (
        "Expected documentation change",
        "textarea",
        False,
    ),
    "documentation-exemption-reason": (
        "Documentation exemption reason",
        "textarea",
        False,
    ),
}


def _load_form() -> dict:
    return yaml.safe_load(FORM.read_text(encoding="utf-8"))


def _interactive_fields(data: dict) -> dict[str, dict]:
    return {
        item["id"]: item
        for item in data["body"]
        if item.get("type") != "markdown"
    }


def _advertised_required_doc_examples(guidance: str) -> list[str]:
    match = re.search(r"such as (.+?)\. Do not use", guidance)
    assert match is not None
    return [value.strip() for value in match.group(1).split(" or ")]


def test_agent_os_issue_form_schema_is_valid_offline():
    data = _load_form()

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


def test_existing_issue_form_field_contract_is_preserved():
    fields = _interactive_fields(_load_form())

    for field_id, label in _EXPECTED_EXISTING_FIELDS.items():
        assert fields[field_id]["attributes"]["label"] == label


def test_prior_scope_and_refactor_intake_fields_are_exact():
    fields = _interactive_fields(_load_form())

    for field_id, (label, item_type, required) in _PRIOR_SCOPE_FIELDS.items():
        item = fields[field_id]
        assert item["attributes"]["label"] == label
        assert item["type"] == item_type
        assert item["validations"]["required"] is required


def test_documentation_impact_contract_is_exact():
    fields = _interactive_fields(_load_form())

    for field_id, (label, item_type, required) in _DOCUMENTATION_FIELDS.items():
        item = fields[field_id]
        assert item["attributes"]["label"] == label
        assert item["type"] == item_type
        assert item["validations"]["required"] is required

    assert fields["documentation-impact"]["attributes"]["options"] == [
        "docs-required",
        "docs-not-required",
        "docs-needs-decision",
    ]


def test_required_docs_guidance_uses_bounded_canonical_paths():
    fields = _interactive_fields(_load_form())
    guidance = fields["required-docs"]["attributes"]["description"]

    assert "01_Shared_Standards/github" in guidance
    assert ".github/workflows" in guidance
    assert "without trailing slashes" in guidance
    assert "01_Shared_Standards/github/" not in guidance
    assert ".github/workflows/" not in guidance
    for unsupported in ("**", "?", "bracket classes", "absolute paths", "./"):
        assert unsupported in guidance

    examples = _advertised_required_doc_examples(guidance)
    assert examples == ["01_Shared_Standards/github", ".github/workflows"]
    assert [normalize_declared_path(value) for value in examples] == examples
