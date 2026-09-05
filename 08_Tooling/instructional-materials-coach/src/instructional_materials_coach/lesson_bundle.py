"""Pure Source -> Lesson Bundle planning over existing governed curriculum contracts.

This module performs no retrieval, provider execution, generation, or persistence.
It coordinates validated current-curriculum state and MaterialRequirement records,
and delegates targeted revision advice to the existing artifact reuse planner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from instructional_workflow_contracts import ValidationResult, ValidationStatus
from instructional_workflow_contracts.current_curriculum_state import (
    CONTRACT_ID as CURRENT_STATE_CONTRACT_ID,
    resolve_current_curriculum_state,
)
from instructional_workflow_contracts.material_requirement import (
    validate_material_requirement,
)
from instructional_workflow_contracts.reuse_planner import (
    plan_instructional_artifact_reuse,
)

MAX_BUNDLE_MEMBERS = 12


class LessonBundleError(ValueError):
    """Fail-closed error for invalid or drifting lesson-bundle evidence."""


@dataclass(frozen=True, slots=True)
class LessonBundleMember:
    artifact_type: str
    requirement_id: str
    requirement_fingerprint: str
    required: bool
    selection_reason: str


@dataclass(frozen=True, slots=True)
class LessonBundlePlan:
    current_state_id: str
    current_state_fingerprint: str
    course_ref: str
    unit_ref: str
    lesson_ref: str
    handoff_id: str
    handoff_fingerprint: str
    members: tuple[LessonBundleMember, ...]
    authority: Mapping[str, bool]


@dataclass(frozen=True, slots=True)
class LessonBundleRevisionPlan:
    target_artifact_type: str
    reuse_plan: ValidationResult
    unchanged_artifact_types: tuple[str, ...]


def plan_lesson_bundle(
    *,
    current_curriculum_evidence: object,
    material_requirements: Sequence[object],
    required_artifact_types: Sequence[str],
    optional_artifact_types: Sequence[str] = (),
) -> LessonBundlePlan:
    """Plan the smallest requested bundle from supplied governed evidence."""
    state = _validated_current_state(current_curriculum_evidence)
    requirements = _validated_requirements(material_requirements)
    required = _artifact_intent(required_artifact_types, "required artifact types")
    optional = _artifact_intent(optional_artifact_types, "optional artifact types")
    if set(required) & set(optional):
        raise LessonBundleError("An artifact type cannot be both required and optional")
    if not required:
        raise LessonBundleError("At least one required artifact type is needed")

    by_type: dict[str, dict[str, Any]] = {}
    for item in requirements:
        artifact_type = item["payload"]["artifact"]["artifact_type"]
        if artifact_type in by_type:
            raise LessonBundleError(f"Duplicate MaterialRequirement artifact type: {artifact_type}")
        by_type[artifact_type] = item

    missing = [artifact_type for artifact_type in required if artifact_type not in by_type]
    if missing:
        raise LessonBundleError("Missing required MaterialRequirement: " + ", ".join(missing))

    selected_types = [*required, *(item for item in optional if item in by_type)]
    selected = [by_type[item] for item in selected_types]
    _validate_shared_context(state, selected)

    members = tuple(
        LessonBundleMember(
            artifact_type=artifact_type,
            requirement_id=by_type[artifact_type]["payload"]["identity"]["requirement_id"],
            requirement_fingerprint=by_type[artifact_type]["fingerprint"],
            required=artifact_type in required,
            selection_reason=(
                "teacher-required" if artifact_type in required else "teacher-optional-and-available"
            ),
        )
        for artifact_type in selected_types
    )
    first = selected[0]["payload"]
    state_payload = state.record.to_dict()
    handoff = first["handoff_reference"]
    return LessonBundlePlan(
        current_state_id=state.record.record_id,
        current_state_fingerprint=state.record.fingerprint,
        course_ref=first["identity"]["course_ref"],
        unit_ref=first["identity"]["unit_ref"],
        lesson_ref=first["identity"]["lesson_ref"],
        handoff_id=handoff["handoff_id"],
        handoff_fingerprint=handoff["fingerprint"],
        members=members,
        authority=_false_authority(),
    )


def plan_bundle_member_revision(
    bundle: LessonBundlePlan,
    *,
    target_artifact_type: str,
    material_requirement: object,
    artifact_manifests: object,
    changed_dependency_keys: object,
    impact_map: object,
    supported_executor: object = True,
) -> LessonBundleRevisionPlan:
    """Delegate revision advice for one member without touching unrelated members."""
    selected = {member.artifact_type: member for member in bundle.members}
    if target_artifact_type not in selected:
        raise LessonBundleError("Target artifact type is not a selected bundle member")
    requirement = _validated_requirements([material_requirement])[0]
    payload = requirement["payload"]
    member = selected[target_artifact_type]
    if payload["artifact"]["artifact_type"] != target_artifact_type:
        raise LessonBundleError("Target MaterialRequirement artifact type does not match bundle member")
    if payload["identity"]["requirement_id"] != member.requirement_id:
        raise LessonBundleError("Target MaterialRequirement identity does not match bundle member")
    if requirement["fingerprint"] != member.requirement_fingerprint:
        raise LessonBundleError("Target MaterialRequirement fingerprint does not match bundle member")

    reuse_plan = plan_instructional_artifact_reuse(
        material_requirement,
        artifact_manifests,
        changed_dependency_keys=changed_dependency_keys,
        impact_map=impact_map,
        supported_executor=supported_executor,
    )
    return LessonBundleRevisionPlan(
        target_artifact_type=target_artifact_type,
        reuse_plan=reuse_plan,
        unchanged_artifact_types=tuple(
            item.artifact_type for item in bundle.members if item.artifact_type != target_artifact_type
        ),
    )


def _validated_current_state(value: object) -> ValidationResult:
    if type(value) is ValidationResult:
        result = value
        if result.record is None or result.record.contract_version != CURRENT_STATE_CONTRACT_ID:
            raise LessonBundleError("Current curriculum state contract is incompatible")
    else:
        result = resolve_current_curriculum_state(value)
    if result.status is not ValidationStatus.VALID or result.record is None:
        raise LessonBundleError("Current curriculum evidence is not supported for bundle planning")
    payload = result.record.to_dict()
    if payload.get("disposition") != "supported":
        raise LessonBundleError("Current curriculum state requires resolution before bundle planning")
    _require_false_authority(payload.get("authority"), "current curriculum state")
    return result


def _validated_requirements(values: Sequence[object]) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise LessonBundleError("MaterialRequirements must be a bounded sequence")
    if not values or len(values) > MAX_BUNDLE_MEMBERS:
        raise LessonBundleError("MaterialRequirements must contain 1 to 12 items")
    result: list[dict[str, Any]] = []
    for value in values:
        validation = validate_material_requirement(value)
        if validation.status is not ValidationStatus.VALID or validation.record is None:
            raise LessonBundleError("MaterialRequirement is not valid for bundle planning")
        payload = validation.record.to_dict()
        _require_false_authority(payload.get("authority"), "MaterialRequirement")
        result.append({"payload": payload, "fingerprint": validation.record.fingerprint})
    return result


def _artifact_intent(values: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise LessonBundleError(f"{label} must be a sequence")
    if len(values) > MAX_BUNDLE_MEMBERS:
        raise LessonBundleError(f"{label} exceeds the 12-item bound")
    normalized: list[str] = []
    for value in values:
        if type(value) is not str or not value.strip():
            raise LessonBundleError(f"{label} must contain non-empty strings")
        token = value.strip()
        if token in normalized:
            raise LessonBundleError(f"{label} contains duplicate artifact types")
        normalized.append(token)
    return tuple(normalized)


def _validate_shared_context(state: ValidationResult, selected: list[dict[str, Any]]) -> None:
    state_payload = state.record.to_dict()
    state_unit = state_payload["canonical_unit"]["stable_id"]
    first = selected[0]["payload"]
    baseline_identity = _identity_tuple(first)
    baseline_handoff = _reference_tuple(first["handoff_reference"])
    baseline_learning = tuple(
        _reference_tuple(first["learning_evidence"][key])
        for key in ("learning_objective_ref", "success_criteria_ref", "evidence_target_ref")
    )
    baseline_modeling = tuple(
        _reference_tuple(first["modeling"][key])
        for key in ("modeling_readiness_ref", "materials_extract_ref")
    )
    vocabulary: dict[str, tuple[object, ...]] = {}

    for item in selected:
        payload = item["payload"]
        if _identity_tuple(payload) != baseline_identity:
            raise LessonBundleError("Cross-artifact course/unit/lesson drift detected")
        if payload["identity"]["unit_ref"] != state_unit:
            raise LessonBundleError("Current curriculum unit and MaterialRequirement unit drift detected")
        if _reference_tuple(payload["handoff_reference"]) != baseline_handoff:
            raise LessonBundleError("Cross-artifact handoff provenance drift detected")
        learning = tuple(
            _reference_tuple(payload["learning_evidence"][key])
            for key in ("learning_objective_ref", "success_criteria_ref", "evidence_target_ref")
        )
        if learning != baseline_learning:
            raise LessonBundleError("Cross-artifact learning evidence drift detected")
        modeling = tuple(
            _reference_tuple(payload["modeling"][key])
            for key in ("modeling_readiness_ref", "materials_extract_ref")
        )
        if modeling != baseline_modeling:
            raise LessonBundleError("Cross-artifact Teacher Modeling drift detected")
        for ref in payload["requirements"]["vocabulary_references"]:
            stable_id = ref["stable_id"]
            identity = _reference_tuple(ref)
            if stable_id in vocabulary and vocabulary[stable_id] != identity:
                raise LessonBundleError("Cross-artifact vocabulary identity drift detected")
            vocabulary[stable_id] = identity


def _identity_tuple(payload: dict[str, Any]) -> tuple[str, str, str]:
    identity = payload["identity"]
    return identity["course_ref"], identity["unit_ref"], identity["lesson_ref"]


def _reference_tuple(value: dict[str, Any]) -> tuple[object, ...]:
    if "handoff_id" in value:
        return (
            value["handoff_id"],
            value["contract_version"],
            value["record_revision"],
            value["fingerprint"],
        )
    return (
        value["stable_id"],
        value["owner"],
        value["contract_version"],
        value["record_revision"],
        value["fingerprint"],
    )


def _require_false_authority(value: object, label: str) -> None:
    if type(value) is not dict or any(type(item) is not bool or item for item in value.values()):
        raise LessonBundleError(f"{label} authority must remain false")


def _false_authority() -> Mapping[str, bool]:
    return {
        "execution_authorized": False,
        "external_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
        "side_effects_performed": False,
    }
