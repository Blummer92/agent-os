from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from instructional_materials_coach.lesson_bundle import (
    LessonBundleError,
    plan_bundle_member_revision,
    plan_lesson_bundle,
)
from instructional_workflow_contracts.material_requirement import (
    material_requirement_source_fingerprint,
)

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "instructional_workflow_contracts"


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


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
        "observed_at": "2026-09-05T12:00:00Z",
        "currentness": "current",
        "material": True,
        "relation_resolved": True,
        "reference": _ref(evidence_id),
    }


def _current_evidence():
    return {
        "contract_version": "curriculum-current-state-evidence-v1",
        "canonical_unit": {"stable_id": "unit-1", "status": "active"},
        "request": {
            "action": "make-lesson-bundle",
            "artifact_type": "lesson",
            "relative_time": "none",
            "requires_reusable_assets": False,
        },
        "required_decision_keys": [],
        "owner_evidence": [_owner("lesson-position", "lesson-position", "Lesson 1")],
        "asset_evidence": [],
    }


def _requirement(artifact_type: str, requirement_id: str):
    value = copy.deepcopy(_fixture("valid_material_requirement_v2.json"))
    value["identity"]["requirement_id"] = requirement_id
    value["artifact"]["artifact_type"] = artifact_type
    value["visual_direction"] = {
        "decision": "no-visuals",
        "maximum_visual_count": 0,
        "roles": [],
    }
    value["assets"] = []
    value["templates"] = []
    value["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(value)
    return value


def test_complete_and_minimal_bundle_follow_teacher_intent():
    requirements = [
        _requirement("slide-deck", "slides-1"),
        _requirement("worksheet", "worksheet-1"),
        _requirement("exit-ticket", "exit-1"),
        _requirement("teacher-guide", "guide-1"),
    ]
    complete = plan_lesson_bundle(
        current_curriculum_evidence=_current_evidence(),
        material_requirements=requirements,
        required_artifact_types=["slide-deck", "worksheet", "exit-ticket"],
        optional_artifact_types=["teacher-guide"],
    )
    minimal = plan_lesson_bundle(
        current_curriculum_evidence=_current_evidence(),
        material_requirements=requirements,
        required_artifact_types=["slide-deck"],
        optional_artifact_types=[],
    )

    assert [item.artifact_type for item in complete.members] == [
        "slide-deck",
        "worksheet",
        "exit-ticket",
        "teacher-guide",
    ]
    assert [item.artifact_type for item in minimal.members] == ["slide-deck"]
    assert complete.members[-1].required is False
    assert complete.members[-1].selection_reason == "teacher-optional-and-available"
    assert all(value is False for value in complete.authority.values())


def test_optional_missing_member_is_not_forced_into_bundle():
    plan = plan_lesson_bundle(
        current_curriculum_evidence=_current_evidence(),
        material_requirements=[_requirement("slide-deck", "slides-1")],
        required_artifact_types=["slide-deck"],
        optional_artifact_types=["teacher-guide"],
    )
    assert [item.artifact_type for item in plan.members] == ["slide-deck"]


def test_learning_drift_fails_closed():
    slides = _requirement("slide-deck", "slides-1")
    worksheet = _requirement("worksheet", "worksheet-1")
    worksheet["learning_evidence"]["learning_objective_ref"]["stable_id"] = "objective-2"
    worksheet["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(worksheet)

    with pytest.raises(LessonBundleError, match="learning evidence drift"):
        plan_lesson_bundle(
            current_curriculum_evidence=_current_evidence(),
            material_requirements=[slides, worksheet],
            required_artifact_types=["slide-deck", "worksheet"],
        )


def test_modeling_drift_fails_closed():
    slides = _requirement("slide-deck", "slides-1")
    worksheet = _requirement("worksheet", "worksheet-1")
    worksheet["modeling"]["materials_extract_ref"]["stable_id"] = "extract-2"
    worksheet["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(worksheet)

    with pytest.raises(LessonBundleError, match="Teacher Modeling drift"):
        plan_lesson_bundle(
            current_curriculum_evidence=_current_evidence(),
            material_requirements=[slides, worksheet],
            required_artifact_types=["slide-deck", "worksheet"],
        )


def test_vocabulary_omission_allowed_but_conflicting_identity_rejected():
    slides = _requirement("slide-deck", "slides-1")
    worksheet = _requirement("worksheet", "worksheet-1")
    worksheet["requirements"]["vocabulary_references"] = []
    worksheet["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(worksheet)
    plan_lesson_bundle(
        current_curriculum_evidence=_current_evidence(),
        material_requirements=[slides, worksheet],
        required_artifact_types=["slide-deck", "worksheet"],
    )

    conflicting = _requirement("worksheet", "worksheet-2")
    conflicting["requirements"]["vocabulary_references"][0]["fingerprint"] = "b" * 64
    conflicting["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(conflicting)
    with pytest.raises(LessonBundleError, match="vocabulary identity drift"):
        plan_lesson_bundle(
            current_curriculum_evidence=_current_evidence(),
            material_requirements=[slides, conflicting],
            required_artifact_types=["slide-deck", "worksheet"],
        )


def test_targeted_revision_leaves_other_bundle_members_unchanged():
    slides = _requirement("slide-deck", "slides-1")
    worksheet = _requirement("worksheet", "worksheet-1")
    plan = plan_lesson_bundle(
        current_curriculum_evidence=_current_evidence(),
        material_requirements=[slides, worksheet],
        required_artifact_types=["slide-deck", "worksheet"],
    )
    revision = plan_bundle_member_revision(
        plan,
        target_artifact_type="worksheet",
        material_requirement=worksheet,
        artifact_manifests=[],
        changed_dependency_keys=["material.requirement"],
        impact_map={"material.requirement": ["practice"]},
    )
    assert revision.target_artifact_type == "worksheet"
    assert revision.unchanged_artifact_types == ("slide-deck",)
    assert revision.reuse_plan.record is not None
    assert revision.reuse_plan.record.to_dict()["decision"] == "create-new-required"


def test_material_requirement_source_fingerprints_need_not_match_between_members():
    slides = _requirement("slide-deck", "slides-1")
    worksheet = _requirement("worksheet", "worksheet-1")
    assert slides["identity"]["source_fingerprint"] != worksheet["identity"]["source_fingerprint"]
    plan = plan_lesson_bundle(
        current_curriculum_evidence=_current_evidence(),
        material_requirements=[slides, worksheet],
        required_artifact_types=["slide-deck", "worksheet"],
    )
    assert len(plan.members) == 2
    assert plan.handoff_id == "handoff-1"
