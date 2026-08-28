"""Compose governed current-curriculum evidence into existing lesson content tokens.

This module is deliberately a narrow adapter. It creates no new curriculum schema,
performs no provider reads or writes, and grants no authority. It consumes the
existing #975 evidence packet, #973 resolver, MaterialRequirement validator, and
#944 visual-plan result supplied by the caller.
"""
from __future__ import annotations

from typing import Any, Mapping

from instructional_workflow_contracts.current_curriculum_state import (
    resolve_current_curriculum_state,
)
from instructional_workflow_contracts.material_requirement import (
    validate_material_requirement,
)

from .content_spec import LessonContent


class GenerationContextError(ValueError):
    """Fail-closed error for unusable or unresolved generation evidence."""


def compose_generation_context(
    content: LessonContent,
    *,
    material_requirement: object,
    current_curriculum_evidence: object,
    selected_asset_ids: tuple[str, ...] = (),
) -> LessonContent:
    """Augment lesson content with current governed evidence without replacing it.

    Existing authored lesson tokens always remain present. Current owner/context
    evidence is added as namespaced tokens, MaterialRequirement identity and
    requirements are preserved, and selected governed visual identities are
    carried forward. Any blocked/manual-review #973 state fails closed before
    generation.
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

    requirement = requirement_result.record.to_dict()
    tokens: dict[str, str] = {}

    identity = requirement["identity"]
    tokens.update(
        {
            "context_course_ref": identity["course_ref"],
            "context_unit_ref": identity["unit_ref"],
            "context_lesson_ref": identity["lesson_ref"],
            "context_material_purpose": requirement["instructional"]["purpose"],
            "context_required_sections": _join(requirement["instructional"]["required_sections"]),
            "context_vocabulary_refs": _join(
                item["stable_id"] for item in requirement["requirements"]["vocabulary_references"]
            ),
            "context_content_requirements": _join(requirement["requirements"]["content_requirements"]),
            "context_classroom_requirements": _join(
                requirement["requirements"]["classroom_use_requirements"]
            ),
            "context_template_ids": _join(item["template_id"] for item in requirement["templates"]),
            "context_requirement_asset_ids": _join(item["asset_id"] for item in requirement["assets"]),
            "context_selected_asset_ids": _join(sorted(set(selected_asset_ids))),
        }
    )

    for item in state.get("owner_states", []):
        value = item.get("value")
        if isinstance(value, str):
            tokens[_decision_token(item["decision_key"])] = value
    for item in state.get("context_evidence", []):
        if item.get("currentness") != "current":
            continue
        value = item.get("value")
        if isinstance(value, str):
            tokens.setdefault(_decision_token(item["decision_key"]), value)

    # Keep authority evidence visible and fixed false; never infer authorization.
    tokens["context_production_authorized"] = "false"
    tokens["context_publication_authorized"] = "false"
    tokens["context_external_write_authorized"] = "false"

    return content.with_context_tokens(tokens)


def _decision_token(decision_key: str) -> str:
    safe = "".join(char if char.isalnum() else "_" for char in decision_key.lower())
    return f"curriculum_{safe.strip('_')}"


def _join(values: Any) -> str:
    return " | ".join(str(value) for value in values)
