"""Compose governed current-curriculum evidence into existing lesson content tokens.

This module is deliberately a narrow adapter. It creates no new curriculum schema,
performs no provider reads or writes, and grants no authority. It consumes the
existing #975 evidence packet, #973 resolver, MaterialRequirement validator, and
#944 visual-plan result supplied by the caller.
"""
from __future__ import annotations

import json
from typing import Any

from instructional_workflow_contracts import ValidationResult, ValidationStatus
from instructional_workflow_contracts.cohesive_visual_plan import (
    CONTRACT_ID as COHESIVE_VISUAL_PLAN_CONTRACT_ID,
)
from instructional_workflow_contracts.current_curriculum_state import (
    resolve_current_curriculum_state,
)
from instructional_workflow_contracts.material_requirement import (
    validate_material_requirement,
)

from .content_spec import LessonContent


class GenerationContextError(ValueError):
    """Fail-closed error for unusable or unresolved generation evidence."""


_TEACHER_ONLY_DECISION_KEYS = frozenset(
    {
        "teacher-scoring-guide",
        "teacher-scoring-notes",
        "rubric-calibration-guidance",
        "calibration-guidance",
    }
)

_STUDENT_ASSESSMENT_TOKENS = {
    "success-criteria": "context_student_success_criteria",
    "student-facing-rubric": "context_student_rubric",
    "student-facing-checklist": "context_student_checklist",
    "observation-criteria": "context_student_observation_criteria",
    "self-check-criteria": "context_student_self_check_criteria",
    "completion-criteria": "context_student_completion_criteria",
}


def compose_generation_context(
    content: LessonContent,
    *,
    material_requirement: object,
    current_curriculum_evidence: object,
    selected_asset_ids: tuple[str, ...] = (),
    governed_visual_plan: object | None = None,
) -> LessonContent:
    """Augment lesson content with current governed evidence without replacing it.

    Existing authored lesson tokens always remain present. Current owner/context
    evidence is added as namespaced tokens, MaterialRequirement identity and
    requirements are preserved, and selected governed visual identities plus
    their existing #944 assignment/use evidence are carried forward. Any
    blocked/manual-review #973 state fails closed before generation.

    Student-facing success/rubric/checklist evidence is projected only from the
    current governed state and remains separate from teacher-only scoring or
    calibration guidance. MaterialRequirement learning references are preserved
    as identity tokens but never treated as student-facing copy by themselves.
    """
    requirement_result = validate_material_requirement(material_requirement)
    if requirement_result.record is None:
        reasons = ", ".join(requirement_result.reason_codes) or "invalid"
        raise GenerationContextError(f"MaterialRequirement is not usable: {reasons}")

    state_result = resolve_current_curriculum_state(current_curriculum_evidence)
    if state_result.record is None:
        reasons = ", ".join(state_result.reason_codes) or "invalid"
        raise GenerationContextError(f"Current curriculum evidence is not usable: {reasons}")
    state = state_result.record.to_dict()
    if state.get("disposition") != "supported":
        reasons = ", ".join(state.get("blockers", []) or state.get("reason_codes", []))
        raise GenerationContextError(
            "Current curriculum evidence requires resolution before generation"
            + (f": {reasons}" if reasons else "")
        )

    visual_asset_ids, visual_assignments = _visual_context(governed_visual_plan)
    supplied_asset_ids = tuple(sorted(set(selected_asset_ids)))
    if supplied_asset_ids and governed_visual_plan is None:
        raise GenerationContextError(
            "Selected visual identities require governed #944 visual-plan evidence"
        )
    if supplied_asset_ids and supplied_asset_ids != visual_asset_ids:
        raise GenerationContextError("Selected visual identity does not match governed visual plan")

    requirement = requirement_result.record.to_dict()
    tokens: dict[str, str] = {}

    identity = requirement["identity"]
    learning = requirement["learning_evidence"]
    tokens.update(
        {
            "context_course_ref": identity["course_ref"],
            "context_unit_ref": identity["unit_ref"],
            "context_lesson_ref": identity["lesson_ref"],
            "context_material_purpose": requirement["instructional"]["purpose"],
            "context_required_sections": _join(requirement["instructional"]["required_sections"]),
            "context_learning_objective_ref": learning["learning_objective_ref"]["stable_id"],
            "context_success_criteria_ref": learning["success_criteria_ref"]["stable_id"],
            "context_evidence_target_ref": learning["evidence_target_ref"]["stable_id"],
            "context_vocabulary_refs": _join(
                item["stable_id"] for item in requirement["requirements"]["vocabulary_references"]
            ),
            "context_content_requirements": _join(requirement["requirements"]["content_requirements"]),
            "context_classroom_requirements": _join(
                requirement["requirements"]["classroom_use_requirements"]
            ),
            "context_template_ids": _join(item["template_id"] for item in requirement["templates"]),
            "context_requirement_asset_ids": _join(item["asset_id"] for item in requirement["assets"]),
            "context_selected_asset_ids": _join(visual_asset_ids),
            "context_selected_visual_assignments": visual_assignments,
        }
    )

    for item in state.get("owner_states", []):
        decision_key = item["decision_key"]
        if decision_key in _TEACHER_ONLY_DECISION_KEYS:
            continue
        value = item.get("value")
        if isinstance(value, str):
            tokens[_decision_token(decision_key)] = value
            student_token = _STUDENT_ASSESSMENT_TOKENS.get(decision_key)
            if student_token is not None:
                tokens[student_token] = value
    for item in state.get("context_evidence", []):
        decision_key = item["decision_key"]
        if decision_key in _TEACHER_ONLY_DECISION_KEYS:
            continue
        if item.get("currentness") != "current":
            continue
        value = item.get("value")
        if isinstance(value, str):
            tokens.setdefault(_decision_token(decision_key), value)
            student_token = _STUDENT_ASSESSMENT_TOKENS.get(decision_key)
            if student_token is not None:
                tokens.setdefault(student_token, value)

    # Keep authority evidence visible and fixed false; never infer authorization.
    tokens["context_production_authorized"] = "false"
    tokens["context_publication_authorized"] = "false"
    tokens["context_external_write_authorized"] = "false"

    return content.with_context_tokens(tokens)


def _visual_context(value: object | None) -> tuple[tuple[str, ...], str]:
    if value is None:
        return (), "[]"
    if type(value) is not ValidationResult:
        raise GenerationContextError("Governed visual plan must be exact validated #944 evidence")
    if value.status is not ValidationStatus.VALID or value.record is None:
        raise GenerationContextError("Governed visual plan is not usable")
    if value.record.contract_version != COHESIVE_VISUAL_PLAN_CONTRACT_ID:
        raise GenerationContextError("Governed visual plan contract is incompatible")

    payload = value.record.to_dict()
    if payload.get("outcome") != "complete-set" or payload.get("manual_review_required") is not False:
        raise GenerationContextError("Governed visual plan is not complete for generation")
    authority = payload.get("authority")
    if type(authority) is not dict or any(authority.values()):
        raise GenerationContextError("Governed visual plan authority must remain false")

    assignments = [
        *payload.get("required_role_assignments", []),
        *payload.get("optional_role_assignments", []),
    ]
    asset_ids: set[str] = set()
    for assignment in assignments:
        try:
            asset_id = assignment["selected_candidate"]["asset_reference"]["asset_id"]
        except (KeyError, TypeError):
            raise GenerationContextError("Governed visual assignment identity is incomplete") from None
        if not isinstance(asset_id, str) or not asset_id:
            raise GenerationContextError("Governed visual assignment asset identity is invalid")
        asset_ids.add(asset_id)

    encoded = json.dumps(assignments, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return tuple(sorted(asset_ids)), encoded


def _decision_token(decision_key: str) -> str:
    safe = "".join(char if char.isalnum() else "_" for char in decision_key.lower())
    return f"curriculum_{safe.strip('_')}"


def _join(values: Any) -> str:
    return " | ".join(str(value) for value in values)
