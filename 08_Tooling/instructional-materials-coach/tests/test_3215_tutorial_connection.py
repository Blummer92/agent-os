"""Regression tests for #3215: the Tutorial-0 connection is typed generation evidence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from instructional_materials_coach.content_spec import content_from_dict
from instructional_materials_coach.docs_requests import build_docs_replace_requests
from instructional_materials_coach.generation_context import (
    GenerationContextError,
    compose_generation_context,
)
from instructional_materials_coach.tutorial_connection import (
    TUTORIALS,
    TutorialConnectionError,
    resolve_tutorial,
    tutorial_transfer_paragraph,
)

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "instructional_workflow_contracts"


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def _requirement():
    return _fixture("valid_material_requirement_v2.json")


def _ref(stable_id: str):
    return {
        "system": "notion",
        "stable_id": stable_id,
        "exact_location": f"collection://fixture/{stable_id}",
        "verification_evidence": "fixture-read-back",
    }


def _owner(evidence_id: str, decision_key: str, value: str):
    return {
        "evidence_id": evidence_id,
        "owner": "instructional-materials-coach",
        "decision_key": decision_key,
        "value": value,
        "classification": "owner-governed",
        "source_revision": 1,
        "observed_at": "2026-08-28T12:00:00Z",
        "currentness": "current",
        "material": True,
        "relation_resolved": True,
        "reference": _ref(evidence_id),
    }


def _evidence(**overrides):
    packet = {
        "contract_version": "curriculum-current-state-evidence-v1",
        "canonical_unit": {"stable_id": "candy-brand-motion-spot", "status": "active"},
        "request": {
            "action": "make",
            "artifact_type": "worksheet",
            "relative_time": "none",
            "requires_reusable_assets": False,
        },
        "required_decision_keys": ["unit-generation-approval"],
        "owner_evidence": [_owner("gate-0", "unit-generation-approval", "ready")],
        "asset_evidence": [],
    }
    packet.update(overrides)
    return packet


def _content(**overrides):
    data = {
        "title": "Motion Spot - Day 1",
        "objectives": ["Name the feeling your spot will change."],
        "slides": [],
        "worksheet_questions": ["What feeling will your spot change?"],
    }
    data.update(overrides)
    return content_from_dict(data)


def test_tutorial_0_registry_names_the_expected_moves():
    record = resolve_tutorial("tutorial-0")
    assert record.title.startswith("Tutorial 0")
    assert record.moves == ("Text", "Recommended fonts", "Alignment and spacing", "Export")
    assert "tutorial-0" in TUTORIALS


def test_unknown_tutorial_id_fails_closed():
    with pytest.raises(TutorialConnectionError, match="unknown prerequisite tutorial"):
        resolve_tutorial("tutorial-9")
    with pytest.raises(TutorialConnectionError, match="non-empty text"):
        resolve_tutorial("  ")


def test_transfer_paragraph_names_moves_and_catch_up():
    paragraph = tutorial_transfer_paragraph("tutorial-0")
    assert "text, recommended fonts, alignment and spacing, and export" in paragraph
    assert "Tutorial 0" in paragraph
    assert "catch-up" in paragraph


def test_prerequisite_tutorials_parse_from_dict():
    content = _content(prerequisite_tutorials=["tutorial-0"])
    assert content.prerequisite_tutorials == ("tutorial-0",)


def test_prerequisite_tutorials_absent_by_default():
    assert _content().prerequisite_tutorials == ()


@pytest.mark.parametrize("bad", ["tutorial-0", [""], ["  "], [42], [{"id": "tutorial-0"}]])
def test_prerequisite_tutorials_malformed_fail_closed(bad):
    with pytest.raises(ValueError):
        _content(prerequisite_tutorials=bad)


def test_generation_context_projects_tutorial_connection_tokens():
    composed = compose_generation_context(
        _content(prerequisite_tutorials=["tutorial-0"]),
        material_requirement=_requirement(),
        current_curriculum_evidence=_evidence(),
    )
    tokens = composed.placeholder_tokens()
    assert tokens["context_prerequisite_tutorials"] == "tutorial-0"
    assert (
        tokens["context_prerequisite_tutorial_moves"]
        == "Text | Recommended fonts | Alignment and spacing | Export"
    )
    connection = tokens["context_tutorial_connection"]
    assert "text, recommended fonts, alignment and spacing, and export" in connection
    assert "catch-up" in connection
    assert tokens["context_tutorial_connection_source"] == "tutorial-registry-default"


def test_generation_context_fails_closed_on_unknown_tutorial():
    with pytest.raises(GenerationContextError, match="unknown prerequisite tutorial"):
        compose_generation_context(
            _content(prerequisite_tutorials=["tutorial-99"]),
            material_requirement=_requirement(),
            current_curriculum_evidence=_evidence(),
        )


def test_governed_tutorial_connection_value_wins_over_registry_default():
    evidence = _evidence()
    evidence["owner_evidence"] = [
        *_evidence()["owner_evidence"],
        _owner("tut-conn", "tutorial-connection", "Governed: revisit the Tutorial 0 font moves on Day 3."),
    ]
    evidence["required_decision_keys"] = ["unit-generation-approval"]
    composed = compose_generation_context(
        _content(prerequisite_tutorials=["tutorial-0"]),
        material_requirement=_requirement(),
        current_curriculum_evidence=evidence,
    )
    tokens = composed.placeholder_tokens()
    assert tokens["context_tutorial_connection"] == "Governed: revisit the Tutorial 0 font moves on Day 3."
    assert tokens["context_tutorial_connection_source"] == "curriculum-governed"


def test_no_prerequisites_means_no_tutorial_connection_token():
    composed = compose_generation_context(
        _content(),
        material_requirement=_requirement(),
        current_curriculum_evidence=_evidence(),
    )
    tokens = composed.placeholder_tokens()
    assert "context_tutorial_connection" not in tokens
    assert "context_prerequisite_tutorials" not in tokens


def test_tutorial_connection_token_reaches_actual_docs_replace_requests():
    """#3215 production path: cli.py build feeds the composed content into
    build_docs_replace_requests, whose replaceAllText requests are what
    live_build.apply_docs_requests sends to docs.documents.batchUpdate. The
    tutorial-connection evidence must materialize there as an actual
    {{context_tutorial_connection}} replacement request, not only as an
    in-memory context token."""
    composed = compose_generation_context(
        _content(prerequisite_tutorials=["tutorial-0"]),
        material_requirement=_requirement(),
        current_curriculum_evidence=_evidence(),
    )
    requests = build_docs_replace_requests(composed)
    matches = [
        request
        for request in requests
        if request.get("replaceAllText", {}).get("containsText", {}).get("text")
        == "{{context_tutorial_connection}}"
    ]
    assert len(matches) == 1
    replace_text = matches[0]["replaceAllText"]["replaceText"]
    assert "text, recommended fonts, alignment and spacing, and export" in replace_text
    assert "catch-up" in replace_text


def test_no_prerequisites_means_no_tutorial_connection_replace_request():
    composed = compose_generation_context(
        _content(),
        material_requirement=_requirement(),
        current_curriculum_evidence=_evidence(),
    )
    requests = build_docs_replace_requests(composed)
    assert all(
        request.get("replaceAllText", {}).get("containsText", {}).get("text")
        != "{{context_tutorial_connection}}"
        for request in requests
    )
