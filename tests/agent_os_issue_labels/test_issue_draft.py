from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels.issue_draft import (
    IssueDraftInputError,
    build_issue_draft,
    load_issue_draft_input,
    render_issue_draft_json,
    render_issue_draft_text,
)

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURE = ROOT / "tests/agent_os_issue_labels/fixtures/issue_draft/valid_tier0.yml"


def valid_input(extra: str = "") -> str:
    return FIXTURE.read_text(encoding="utf-8") + extra


def test_valid_input_renders_deterministically_and_reuses_label_contract():
    draft_input = load_issue_draft_input(valid_input())

    first = build_issue_draft(
        draft_input,
        issue_form_path=FORM,
        label_map_path=MAP,
    )
    second = build_issue_draft(
        draft_input,
        issue_form_path=FORM,
        label_map_path=MAP,
    )

    assert first == second
    assert first.overall_status == Status.PASS
    assert first.title == "[Agent OS] Deterministic preview"
    assert first.proposed_labels == (
        "agent-os",
        "owner:github-service-agent",
        "status:ready",
    )
    assert first.mutation_performed is False
    assert first.write_authorized is False
    assert first.body.startswith("### Issue tier\n\ntier:0-small-maintenance")
    assert "### Safety confirmation" in first.body
    assert render_issue_draft_text(first) == render_issue_draft_text(second)
    assert render_issue_draft_json(first) == render_issue_draft_json(second)


def test_missing_required_field_routes_to_manual_review():
    text = valid_input().replace("  dependencies: none\n", "")

    result = build_issue_draft(
        load_issue_draft_input(text),
        issue_form_path=FORM,
        label_map_path=MAP,
    )

    assert result.overall_status == Status.MANUAL_REVIEW
    assert "required field is missing: dependencies" in result.manual_review_items


def test_unknown_field_and_option_route_to_manual_review_without_submission():
    text = valid_input("  unexpected-field: value\n").replace(
        "status:ready",
        "status:impossible",
    )

    result = build_issue_draft(
        load_issue_draft_input(text),
        issue_form_path=FORM,
        label_map_path=MAP,
    )

    assert result.overall_status == Status.MANUAL_REVIEW
    assert any("unexpected-field" in item for item in result.manual_review_items)
    assert any("status:impossible" in item for item in result.manual_review_items)
    assert result.write_authorized is False


def test_unicode_and_multiline_content_are_preserved():
    text = valid_input().replace(
        "Build a deterministic preview.",
        "Build a café-ready preview — safely.",
    )

    result = build_issue_draft(
        load_issue_draft_input(text),
        issue_form_path=FORM,
        label_map_path=MAP,
    )

    assert "café-ready preview — safely" in result.body


def test_duplicate_mapping_key_fails_closed():
    with pytest.raises(IssueDraftInputError, match="duplicate mapping key: title"):
        load_issue_draft_input("title: one\ntitle: two\nfields: {}\n")


def test_unsupported_form_element_routes_to_manual_review(tmp_path):
    custom = tmp_path / "form.yml"
    original = FORM.read_text(encoding="utf-8")
    data = original.replace(
        "  - type: textarea\n    id: tier2-controls",
        "  - type: date\n"
        "    id: due-date\n"
        "    attributes: {label: Due date}\n"
        "    validations: {required: false}\n"
        "  - type: textarea\n"
        "    id: tier2-controls",
    )
    custom.write_text(data, encoding="utf-8")

    result = build_issue_draft(
        load_issue_draft_input(valid_input()),
        issue_form_path=custom,
        label_map_path=MAP,
    )

    assert result.overall_status == Status.MANUAL_REVIEW
    assert any("unsupported type date" in item for item in result.manual_review_items)
