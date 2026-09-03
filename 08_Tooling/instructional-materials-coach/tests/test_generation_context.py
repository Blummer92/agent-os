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
from instructional_materials_coach.slides_requests import build_slides_replace_requests
from instructional_materials_coach.teacher_reference import (
    build_unit_vocabulary_reference,
    build_worked_examples_reference,
    render_teacher_reference_markdown,
)
from instructional_materials_coach.visual_reuse import plan_governed_visual_reuse

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


def _owner(evidence_id: str, decision_key: str, value: str, *, classification="owner-governed"):
    return {
        "evidence_id": evidence_id,
        "owner": "instructional-materials-coach",
        "decision_key": decision_key,
        "value": value,
        "classification": classification,
        "source_revision": 1,
        "observed_at": "2026-08-28T12:00:00Z",
        "currentness": "current",
        "material": True,
        "relation_resolved": True,
        "reference": _ref(evidence_id),
    }


def _photography_evidence():
    gate_keys = (
        "unit-generation-approval",
        "packet-generation-gate",
        "instructional-materials-readiness",
        "source-control-gate",
        "production-authorized",
    )
    owners = [_owner(f"gate-{i}", key, "ready") for i, key in enumerate(gate_keys)]
    owners.extend(
        [
            _owner("unit-purpose", "unit-purpose", "Use composition to make intentional visual decisions."),
            _owner("lesson-position", "lesson-position", "Photography Foundations — Elements & Composition"),
            _owner("warmup", "warm-up", "Notice what changes when the photographer moves closer."),
            _owner("vocab", "vocabulary", "framing | focal point | negative space"),
            _owner("exit", "exit-ticket", "Explain one framing decision you made today."),
            _owner("crop", "teacher-confirmed-cropping", "Compose with the camera first; teach cropping explicitly.", classification="teacher-entered"),
        ]
    )
    return {
        "contract_version": "curriculum-current-state-evidence-v1",
        "canonical_unit": {"stable_id": "photography-foundations", "status": "active"},
        "request": {
            "action": "make",
            "artifact_type": "worksheet",
            "relative_time": "none",
            "requires_reusable_assets": False,
        },
        "required_decision_keys": list(gate_keys),
        "owner_evidence": owners,
        "asset_evidence": [],
    }


def _content():
    return content_from_dict(
        {
            "title": "Elements & Composition",
            "objectives": ["Make intentional composition choices."],
            "slides": [],
            "worksheet_questions": ["What did you change and why?"],
        }
    )


def _governed_visual_plan():
    plan = plan_governed_visual_reuse(
        _requirement(),
        artifact_manifests=[_fixture("valid_artifact_manifest.json")],
        visual_candidates=[_fixture("valid_visual_asset_compatibility_v2.json")],
        source_revision="visual-library-snapshot-v2",
        changed_dependency_keys=[],
        impact_map={},
    )
    assert plan.outcome == "visuals-ready"
    assert plan.cohesive_visual_plan_result is not None
    return plan


def test_photography_context_augments_instead_of_replacing_authored_content():
    visual_plan = _governed_visual_plan()
    content = compose_generation_context(
        _content(),
        material_requirement=_requirement(),
        current_curriculum_evidence=_photography_evidence(),
        selected_asset_ids=visual_plan.selected_asset_ids,
        governed_visual_plan=visual_plan.cohesive_visual_plan_result,
    )
    tokens = content.placeholder_tokens()
    assert tokens["title"] == "Elements & Composition"
    assert tokens["objective_1"] == "Make intentional composition choices."
    assert tokens["curriculum_unit_purpose"] == "Use composition to make intentional visual decisions."
    assert "Photography Foundations" in tokens["curriculum_lesson_position"]
    assert "moves closer" in tokens["curriculum_warm_up"]
    assert "focal point" in tokens["curriculum_vocabulary"]
    assert "framing decision" in tokens["curriculum_exit_ticket"]
    assert "cropping explicitly" in tokens["curriculum_teacher_confirmed_cropping"]
    assert tokens["context_learning_objective_ref"] == "objective-1"
    assert tokens["context_success_criteria_ref"] == "criteria-1"
    assert tokens["context_evidence_target_ref"] == "evidence-1"
    assert tokens["context_selected_asset_ids"] == "asset-1"
    assert tokens["context_production_authorized"] == "false"

    assignments = json.loads(tokens["context_selected_visual_assignments"])
    assert assignments[0]["role_type"] == "worked-example"
    assert assignments[0]["intended_placement"]
    assert assignments[0]["selected_candidate"]["asset_reference"]["asset_id"] == "asset-1"
    assert assignments[0]["selected_candidate"]["manifest_reference"]["external_file_id"] == "file-1"
    assert assignments[0]["compatibility_evidence"]["approved_use"]["material_types"] == ["worksheet"]
    assert assignments[0]["compatibility_evidence"]["approved_use"]["role_types"] == ["worked-example"]


def test_student_assessment_criteria_reach_docs_without_teacher_scoring_leakage():
    evidence = _photography_evidence()
    evidence["owner_evidence"].extend(
        [
            _owner("criteria", "success-criteria", "I use hierarchy to make the most important information stand out."),
            _owner("rubric", "student-facing-rubric", "Hierarchy — 4 points | Legibility — 4 points | Purpose — 4 points"),
            _owner("teacher-notes", "teacher-scoring-notes", "Teacher calibration: allow equivalent hierarchy solutions."),
        ]
    )
    content = compose_generation_context(
        _content(),
        material_requirement=_requirement(),
        current_curriculum_evidence=evidence,
    )
    tokens = content.placeholder_tokens()
    assert tokens["context_success_criteria_ref"] == "criteria-1"
    assert tokens["context_student_success_criteria"] == (
        "I use hierarchy to make the most important information stand out."
    )
    assert tokens["context_student_rubric"] == (
        "Hierarchy — 4 points | Legibility — 4 points | Purpose — 4 points"
    )
    assert "curriculum_teacher_scoring_notes" not in tokens
    assert "Teacher calibration" not in "\n".join(tokens.values())

    by_token = {
        request["replaceAllText"]["containsText"]["text"]: request["replaceAllText"]["replaceText"]
        for request in build_docs_replace_requests(content)
    }
    assert by_token["{{context_student_success_criteria}}"] == tokens["context_student_success_criteria"]
    assert by_token["{{context_student_rubric}}"] == tokens["context_student_rubric"]
    assert "{{curriculum_teacher_scoring_notes}}" not in by_token


@pytest.mark.parametrize(
    ("decision_key", "token", "value"),
    [
        ("student-facing-checklist", "context_student_checklist", "[ ] I completed the taught setup. | [ ] I checked my result."),
        ("observation-criteria", "context_student_observation_criteria", "I can explain what changed and why."),
        ("self-check-criteria", "context_student_self_check_criteria", "I checked readability before submitting."),
        ("completion-criteria", "context_student_completion_criteria", "My file is named correctly and submitted."),
    ],
)
def test_student_criteria_forms_preserve_exact_governed_language(decision_key, token, value):
    evidence = _photography_evidence()
    evidence["owner_evidence"].append(_owner(f"evidence-{decision_key}", decision_key, value))
    content = compose_generation_context(
        _content(),
        material_requirement=_requirement(),
        current_curriculum_evidence=evidence,
    )
    assert content.placeholder_tokens()[token] == value


def test_formative_without_assessment_criteria_does_not_invent_rubric():
    content = compose_generation_context(
        _content(),
        material_requirement=_requirement(),
        current_curriculum_evidence=_photography_evidence(),
    )
    tokens = content.placeholder_tokens()
    assert "context_student_rubric" not in tokens
    assert "context_student_success_criteria" not in tokens
    assert "context_student_checklist" not in tokens


def test_governed_visual_assignment_tokens_reach_docs_and_slides_request_builders():
    visual_plan = _governed_visual_plan()
    content = compose_generation_context(
        _content(),
        material_requirement=_requirement(),
        current_curriculum_evidence=_photography_evidence(),
        selected_asset_ids=visual_plan.selected_asset_ids,
        governed_visual_plan=visual_plan.cohesive_visual_plan_result,
    )
    expected = content.context_tokens["context_selected_visual_assignments"]
    for requests in (build_docs_replace_requests(content), build_slides_replace_requests(content)):
        by_token = {
            request["replaceAllText"]["containsText"]["text"]: request["replaceAllText"]["replaceText"]
            for request in requests
        }
        assert by_token["{{context_selected_visual_assignments}}"] == expected
        assert by_token["{{context_selected_asset_ids}}"] == "asset-1"


def test_selected_asset_ids_without_governed_visual_plan_fail_closed():
    with pytest.raises(GenerationContextError, match="require governed #944 visual-plan evidence"):
        compose_generation_context(
            _content(),
            material_requirement=_requirement(),
            current_curriculum_evidence=_photography_evidence(),
            selected_asset_ids=("asset-1",),
        )


def test_selected_asset_identity_mismatch_fails_closed():
    visual_plan = _governed_visual_plan()
    with pytest.raises(GenerationContextError, match="does not match governed visual plan"):
        compose_generation_context(
            _content(),
            material_requirement=_requirement(),
            current_curriculum_evidence=_photography_evidence(),
            selected_asset_ids=("different-asset",),
            governed_visual_plan=visual_plan.cohesive_visual_plan_result,
        )


def test_unresolved_current_curriculum_evidence_fails_closed():
    evidence = _photography_evidence()
    evidence["owner_evidence"] = [
        item for item in evidence["owner_evidence"] if item["decision_key"] != "packet-generation-gate"
    ]
    with pytest.raises(GenerationContextError, match="requires resolution"):
        compose_generation_context(
            _content(),
            material_requirement=_requirement(),
            current_curriculum_evidence=evidence,
        )


def test_context_cannot_replace_authored_tokens():
    content = _content().with_context_tokens({"title": "replacement"})
    with pytest.raises(ValueError, match="collides"):
        content.placeholder_tokens()


def test_typography_teacher_reference_projection_does_not_widen_1416_visual_approval():
    """Keep worksheet approval visible while refusing to widen it to teacher-reference use."""
    visual_plan = _governed_visual_plan()
    context = compose_generation_context(
        _content(),
        material_requirement=_requirement(),
        current_curriculum_evidence=_photography_evidence(),
        selected_asset_ids=visual_plan.selected_asset_ids,
        governed_visual_plan=visual_plan.cohesive_visual_plan_result,
    )
    assignments = json.loads(context.context_tokens["context_selected_visual_assignments"])
    role_id = assignments[0]["role_id"]

    vocabulary = build_unit_vocabulary_reference(
        unit_title="Typography & Visual Communication",
        vocabulary_rows=[
            {
                "kind": "vocabulary",
                "day_lesson": "Day 2",
                "term": "hierarchy",
                "student_friendly_definition": "Visual order that shows what to notice first, next, and last.",
                "expectation": "core",
                "icon_requirement": "required",
                "icon_role_id": role_id,
                "source_reference": "unit-alignment:hierarchy",
            },
            {
                "kind": "scaffold",
                "day_lesson": "Day 1",
                "term": "font menu",
                "student_friendly_definition": "A bounded font-choice scaffold.",
                "expectation": "unspecified",
                "icon_requirement": "not-needed",
            },
        ],
        governed_visual_assignments=context.context_tokens["context_selected_visual_assignments"],
    )
    assert vocabulary["rows"][0]["icon_status"] == "useful-but-missing"
    assert vocabulary["rows"][0]["icon_preview"] is None
    assert vocabulary["excluded_scaffolds"] == ["font menu"]

    prompt = "Create a non-UI business-card comparison showing strong and weak hierarchy."
    examples = build_worked_examples_reference(
        unit_title="Typography & Visual Communication",
        modeling_rows=[
            {
                "day_lesson": "Day 2",
                "skill_learning_purpose": "Compare strong and weak hierarchy.",
                "example_role": "comparison",
                "teacher_modeling_purpose": "Think aloud about what the eye notices first.",
                "artifact_location": "tutorial step 3",
                "tutorial_step": "Build business-card comparison",
                "visual_role_id": role_id,
                "expected_visual_description": "Strong and weak hierarchy examples.",
                "source_constraints": "Teacher reference only.",
            }
        ],
        visual_prompt_rows=[
            {
                "visual_role_id": role_id,
                "generative": True,
                "prompt": prompt,
                "source_constraints": "current-prompt-evidence",
            }
        ],
        governed_visual_assignments=context.context_tokens["context_selected_visual_assignments"],
    )
    row = examples["rows"][0]
    assert row["visual_status"] == "explicit-gap"
    assert row["visual_preview"] is None
    assert row["visual_prompt"] == prompt
    assert '"material_types":["worksheet"]' in row["source_reuse_safe_use_constraints"]
    assert '"role_types":["worked-example"]' in row["source_reuse_safe_use_constraints"]
    assert "approved_use=" in row["source_reuse_safe_use_constraints"]
    assert not any(vocabulary["authority"].values())
    assert not any(examples["authority"].values())

    rendered = render_teacher_reference_markdown(vocabulary)
    assert "Typography & Visual Communication" in rendered
    assert "hierarchy" in rendered
    assert "font menu" in rendered
    assert "useful-but-missing" in rendered
    assert "grants no readiness" in rendered
