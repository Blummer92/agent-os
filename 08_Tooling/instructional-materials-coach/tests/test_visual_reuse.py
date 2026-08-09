from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import instructional_materials_coach.visual_reuse as visual_reuse
from instructional_workflow_contracts import ValidationStatus
from instructional_workflow_contracts.material_requirement import (
    material_requirement_source_fingerprint,
)


ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "instructional_workflow_contracts"
RUNTIME_MODULE = (
    ROOT
    / "08_Tooling"
    / "instructional-materials-coach"
    / "src"
    / "instructional_materials_coach"
    / "visual_reuse.py"
)


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _no_visual_requirement() -> dict[str, object]:
    requirement = _fixture("valid_material_requirement_v2.json")
    requirement["visual_direction"] = {  # type: ignore[index]
        "decision": "no-visuals",
        "maximum_visual_count": 0,
        "roles": [],
    }
    requirement["identity"]["source_fingerprint"] = (  # type: ignore[index]
        material_requirement_source_fingerprint(requirement)
    )
    return requirement


def _assert_authority_false(result) -> None:
    assert result is not None
    assert result.record is not None
    authority = result.record.to_dict()["authority"]
    assert authority
    assert set(authority.values()) == {False}


def test_no_visual_needed_bypasses_all_asset_planning(monkeypatch) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("asset planning must not run for no-visual-needed")

    monkeypatch.setattr(visual_reuse, "plan_instructional_artifact_reuse", unexpected)
    monkeypatch.setattr(visual_reuse, "filter_approved_visual_candidates", unexpected)
    monkeypatch.setattr(visual_reuse, "plan_cohesive_visual_set", unexpected)

    plan = visual_reuse.plan_governed_visual_reuse(
        _no_visual_requirement(),
        artifact_manifests=object(),
        visual_candidates=object(),
        source_revision=object(),
        changed_dependency_keys=object(),
        impact_map=object(),
    )

    assert plan.outcome == "no-visual-needed"
    assert plan.final_production_blocked is False
    assert plan.selected_asset_ids == ()
    assert plan.image_gap_briefs == ()
    _assert_authority_false(plan.visual_needs_result)


def test_v2_reuses_approved_asset_through_existing_public_planners() -> None:
    plan = visual_reuse.plan_governed_visual_reuse(
        _fixture("valid_material_requirement_v2.json"),
        artifact_manifests=[_fixture("valid_artifact_manifest.json")],
        visual_candidates=[_fixture("valid_visual_asset_compatibility_v2.json")],
        source_revision="visual-library-snapshot-v2",
        changed_dependency_keys=[],
        impact_map={},
    )

    assert plan.outcome == "visuals-ready"
    assert plan.final_production_blocked is False
    assert plan.selected_asset_ids == ("asset-1",)
    assert plan.image_gap_briefs == ()
    assert plan.material_requirement_result.record is not None
    assert (
        plan.material_requirement_result.record.contract_version
        == "curriculum-material-requirement-v2"
    )
    _assert_authority_false(plan.visual_needs_result)
    _assert_authority_false(plan.artifact_reuse_result)
    _assert_authority_false(plan.candidate_filter_result)
    _assert_authority_false(plan.cohesive_visual_plan_result)


def test_unfilled_required_role_preserves_gap_brief_and_blocks_production() -> None:
    plan = visual_reuse.plan_governed_visual_reuse(
        _fixture("valid_material_requirement_v2.json"),
        artifact_manifests=[_fixture("valid_artifact_manifest.json")],
        visual_candidates=[],
        source_revision="visual-library-snapshot-v2",
        changed_dependency_keys=[],
        impact_map={},
    )

    assert plan.outcome == "visual-gap-blocked"
    assert plan.final_production_blocked is True
    assert plan.selected_asset_ids == ()
    assert plan.cohesive_visual_plan_result is not None
    assert plan.cohesive_visual_plan_result.record is not None
    cohesive_payload = plan.cohesive_visual_plan_result.record.to_dict()
    assert cohesive_payload["unfilled_required_roles"]
    assert plan.image_gap_briefs == tuple(cohesive_payload["image_gap_briefs"])
    assert plan.image_gap_briefs

    repeated = visual_reuse.plan_governed_visual_reuse(
        _fixture("valid_material_requirement_v2.json"),
        artifact_manifests=[_fixture("valid_artifact_manifest.json")],
        visual_candidates=[],
        source_revision="visual-library-snapshot-v2",
        changed_dependency_keys=[],
        impact_map={},
    )
    assert repeated.image_gap_briefs == plan.image_gap_briefs


def test_v1_and_invalid_requirements_fail_closed_before_asset_planning(monkeypatch) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("asset planning must not run before governed visual direction")

    monkeypatch.setattr(visual_reuse, "plan_instructional_artifact_reuse", unexpected)
    monkeypatch.setattr(visual_reuse, "filter_approved_visual_candidates", unexpected)
    monkeypatch.setattr(visual_reuse, "plan_cohesive_visual_set", unexpected)

    v1 = visual_reuse.plan_governed_visual_reuse(
        _fixture("valid_material_requirement.json")
    )
    assert v1.outcome == "manual-review-required"
    assert v1.final_production_blocked is True
    assert v1.visual_needs_result is not None
    assert v1.visual_needs_result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED

    invalid_requirement = copy.deepcopy(_fixture("valid_material_requirement_v2.json"))
    invalid_requirement["unexpected"] = True
    invalid = visual_reuse.plan_governed_visual_reuse(invalid_requirement)
    assert invalid.outcome == "invalid-material-requirement"
    assert invalid.final_production_blocked is True
    assert invalid.material_requirement_result.status is ValidationStatus.INVALID
    assert invalid.visual_needs_result is None


def test_runtime_module_uses_public_contract_boundaries_without_policy_copies() -> None:
    source = RUNTIME_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert {
        "validate_material_requirement",
        "plan_visual_needs",
        "filter_approved_visual_candidates",
        "plan_cohesive_visual_set",
        "plan_instructional_artifact_reuse",
    }.issubset(imported)
    assert not any(name.startswith("_") for name in imported)

    for duplicated_policy_field in (
        "rights_classification",
        "privacy_observations",
        "teacher_approval",
        "classroom_readiness",
        "cohesion_profile",
    ):
        assert duplicated_policy_field not in source
