"""Regression tests for #3212: declared visual examples are build-time obligations."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from instructional_materials_coach.content_spec import content_from_dict
from instructional_materials_coach.generation_context import (
    GenerationContextError,
    compose_generation_context,
)
from instructional_materials_coach.visual_reuse import plan_governed_visual_reuse
from instructional_materials_coach.worksheet_visual_examples import (
    VisualExampleCoverageError,
    check_visual_example_coverage,
    require_visual_example_plan_coverage,
    required_visual_example_bindings,
)

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "instructional_workflow_contracts"
# The fixture visual plan carries one required role assignment:
# role_id "visual-role-4aa06c2c6c64803a252286b2", slot "0".
FIXTURE_ROLE_ID = "visual-role-4aa06c2c6c64803a252286b2"


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


def _evidence():
    return {
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


def _content(**overrides):
    data = {
        "title": "Motion Spot — Day 3",
        "objectives": ["Choose motion that fits the feeling."],
        "slides": [],
        "worksheet_questions": ["Which motion did you choose and why?"],
    }
    data.update(overrides)
    return content_from_dict(data)


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


def _motion_spot_examples():
    return [
        {
            "section": "day-3-build",
            "role_id": "worked-example-figure",
            "slot_id": "0",
            "caption": "Before/after frames: the same panel with and without motion marks.",
        },
        {
            "section": "day-3-check",
            "role_id": "clear-vs-flashy-comparison",
            "caption": "Clear vs flashy motion choice.",
        },
    ]


def test_visual_examples_parse_from_dict():
    content = _content(visual_examples=_motion_spot_examples())
    assert len(content.visual_examples) == 2
    first = content.visual_examples[0]
    assert first.section == "day-3-build"
    assert first.role_id == "worked-example-figure"
    assert first.slot_id == "0"
    assert first.caption.startswith("Before/after frames")
    # slot_id defaults to the implicit slot "0".
    assert content.visual_examples[1].slot_id == "0"


def test_visual_examples_absent_by_default():
    content = _content()
    assert content.visual_examples == ()
    assert required_visual_example_bindings(content) == ()


def test_visual_example_captions_become_placeholder_tokens():
    tokens = _content(visual_examples=_motion_spot_examples()).placeholder_tokens()
    assert (
        tokens["visual_example_1_caption"]
        == "Before/after frames: the same panel with and without motion marks."
    )
    assert tokens["visual_example_2_caption"] == "Clear vs flashy motion choice."


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-list",
        ["not-a-mapping"],
        [{"section": "day-3-build"}],  # missing role_id
        [{"role_id": "worked-example-figure"}],  # missing section
        [{"section": "", "role_id": "worked-example-figure"}],
        [{"section": "day-3-build", "role_id": "worked-example-figure", "slot_id": ""}],
        [{"section": "day-3-build", "role_id": "worked-example-figure", "caption": 42}],
    ],
)
def test_visual_examples_malformed_fail_closed(bad):
    with pytest.raises(ValueError):
        _content(visual_examples=bad)


def test_required_bindings_are_sorted_unique_role_slot_pairs():
    content = _content(
        visual_examples=[
            {"section": "b", "role_id": "figure", "slot_id": "1"},
            {"section": "a", "role_id": "figure", "slot_id": "0"},
            {"section": "a2", "role_id": "diagram", "slot_id": "0"},
        ]
    )
    assert required_visual_example_bindings(content) == (
        ("diagram", "0"),
        ("figure", "0"),
        ("figure", "1"),
    )


def test_required_bindings_reject_duplicate_slot_across_sections():
    # #3212 repair: the same (role_id, slot_id) declared in two independent
    # sections is a conflicting obligation, not a shared one; fail closed
    # and name both sections.
    content = _content(
        visual_examples=[
            {"section": "page1", "role_id": "figure", "slot_id": "0"},
            {"section": "page2", "role_id": "figure", "slot_id": "0"},
        ]
    )
    with pytest.raises(VisualExampleCoverageError, match="page1.*page2|page2.*page1"):
        required_visual_example_bindings(content)


def test_require_coverage_passes_when_plan_covers():
    content = _content(
        visual_examples=[{"section": "day-3-build", "role_id": "worked-example-figure"}]
    )
    require_visual_example_plan_coverage(
        content, (("worked-example-figure", "0", "asset-9", True),)
    )


def test_require_coverage_fails_closed_when_covered_only_by_optional():
    # #3212 repair: an optional plan assignment cannot discharge a declared
    # required worksheet figure.
    content = _content(
        visual_examples=[{"section": "day-3-build", "role_id": "worked-example-figure"}]
    )
    with pytest.raises(VisualExampleCoverageError, match="optional"):
        require_visual_example_plan_coverage(
            content, (("worked-example-figure", "0", "asset-9", False),)
        )


def test_require_coverage_ignores_lessons_without_declarations():
    require_visual_example_plan_coverage(_content(), ())


def test_require_coverage_fails_closed_without_governed_plan():
    content = _content(visual_examples=_motion_spot_examples())
    with pytest.raises(VisualExampleCoverageError, match="no governed visual plan"):
        require_visual_example_plan_coverage(content, ())


def test_require_coverage_fails_closed_on_uncovered_slot():
    content = _content(
        visual_examples=[
            {"section": "day-3-build", "role_id": "worked-example-figure"},
            {"section": "day-3-check", "role_id": "missing-comparison"},
        ]
    )
    with pytest.raises(VisualExampleCoverageError, match="missing-comparison:0"):
        require_visual_example_plan_coverage(
            content, (("worked-example-figure", "0", "asset-9", True),)
        )


def test_check_coverage_reuses_completeness_contract():
    content = _content(visual_examples=_motion_spot_examples())
    assert (
        check_visual_example_coverage(
            content,
            verified_bindings=(
                ("worked-example-figure", "0"),
                ("clear-vs-flashy-comparison", "0"),
            ),
        ).status
        == "pass"
    )
    assert (
        check_visual_example_coverage(
            content, verified_bindings=(("worked-example-figure", "0"),)
        ).status
        == "fail"
    )


def test_generation_context_fails_closed_when_examples_have_no_plan():
    content = _content(visual_examples=_motion_spot_examples())
    with pytest.raises(GenerationContextError, match="visual examples"):
        compose_generation_context(
            content,
            material_requirement=_requirement(),
            current_curriculum_evidence=_evidence(),
        )


def test_generation_context_passes_when_plan_covers_declared_examples():
    plan = _governed_visual_plan()
    content = _content(
        visual_examples=[
            {
                "section": "day-3-build",
                "role_id": FIXTURE_ROLE_ID,
                "caption": "Worked example figure.",
            }
        ]
    )
    composed = compose_generation_context(
        content,
        material_requirement=_requirement(),
        current_curriculum_evidence=_evidence(),
        selected_asset_ids=plan.selected_asset_ids,
        governed_visual_plan=plan.cohesive_visual_plan_result,
    )
    assert composed.visual_examples == content.visual_examples
    tokens = composed.placeholder_tokens()
    assert tokens["visual_example_1_caption"] == "Worked example figure."


def test_generation_context_fails_closed_when_plan_misses_declared_role():
    plan = _governed_visual_plan()
    content = _content(
        visual_examples=[
            {"section": "day-3-build", "role_id": "undeclared-motion-figure"}
        ]
    )
    with pytest.raises(GenerationContextError, match="undeclared-motion-figure"):
        compose_generation_context(
            content,
            material_requirement=_requirement(),
            current_curriculum_evidence=_evidence(),
            selected_asset_ids=plan.selected_asset_ids,
            governed_visual_plan=plan.cohesive_visual_plan_result,
        )
