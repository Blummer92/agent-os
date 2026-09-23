"""Pure RJ -> Teacher Modeling -> Picture Perfect integration transforms.

RJ1/RJ2 provide evidence. Teacher Modeling owns instructional disposition and
sequence. Picture Perfect owns visual-state planning. ImageIntent remains the
provider-neutral visual contract for non-interface imagery. This module performs
no Recorder parsing, browser execution, provider call, or external write.
"""

from __future__ import annotations

import re
from typing import Any

from .common import validate_sha256, validate_stable_id, validate_text

RJ_EVIDENCE_STATES = frozenset({"pending", "passed", "failed", "indeterminate"})
MODELING_DISPOSITIONS = frozenset({"keep", "combine", "not-instructional", "needs-review"})
VISUAL_STATES = frozenset({"action", "result", "action+result"})
ORIENTATIONS = frozenset({"portrait", "landscape", "square", "wide", "tall", "unspecified"})
_TECHNICAL_MARKER_RE = re.compile(
    r"(?:data-testid|aria/|xpath/|pierce/|css/|urn:aaid:|x-loading|folder-asset-card-)",
    re.IGNORECASE,
)
_SOFTWARE_UI_GENERATION_ERROR = (
    "Picture Perfect software-tutorial visuals require approved screen-capture evidence; "
    "the generative ImageIntent path is not allowed"
)


def build_modeling_candidates(
    *,
    recording_id: str,
    recording_sha256: str,
    semantic_actions: list[dict[str, Any]],
    rewrite_operations: list[dict[str, Any]] | None = None,
    rj3_state: str = "pending",
    rj4_state: str = "pending",
) -> list[dict[str, Any]]:
    """Build evidence-bound candidates without making instructional decisions."""
    recording_id = validate_stable_id(recording_id, "recording_id")
    recording_sha256 = validate_sha256(recording_sha256, "recording_sha256")
    _evidence_state(rj3_state, "rj3_state")
    _evidence_state(rj4_state, "rj4_state")
    if type(semantic_actions) is not list:
        raise TypeError("semantic_actions must be a built-in list")
    if rewrite_operations is None:
        rewrite_operations = []
    if type(rewrite_operations) is not list:
        raise TypeError("rewrite_operations must be a built-in list")

    rewrites: dict[str, dict[str, Any]] = {}
    for operation in rewrite_operations:
        if type(operation) is not dict:
            raise TypeError("rewrite operation must be a built-in mapping")
        action_id = validate_stable_id(operation.get("semantic_action_id"), "semantic_action_id")
        if action_id in rewrites:
            raise ValueError("duplicate rewrite operation for semantic action")
        source_indexes = _source_indexes(operation.get("source_indexes"))
        confidence = validate_text(operation.get("confidence"), "rewrite confidence", max_length=32)
        kind = validate_text(operation.get("kind"), "rewrite kind", max_length=32)
        rewrites[action_id] = {
            "kind": kind,
            "confidence": confidence,
            "source_indexes": source_indexes,
        }

    candidates: list[dict[str, Any]] = []
    seen_sources: set[int] = set()
    for index, action in enumerate(semantic_actions):
        if type(action) is not dict:
            raise TypeError("semantic action must be a built-in mapping")
        action_id = f"action-{index}"
        source_indexes = _source_indexes(action.get("source_indexes"))
        overlap = seen_sources.intersection(source_indexes)
        if overlap:
            raise ValueError("semantic actions contain duplicate source indexes")
        seen_sources.update(source_indexes)
        evidence = _text_list(action.get("evidence", []), "semantic evidence")
        rewrite = rewrites.get(action_id)
        if rewrite is not None and rewrite["source_indexes"] != source_indexes:
            raise ValueError("rewrite provenance does not match semantic action")
        candidates.append(
            {
                "candidate_id": f"modeling-candidate:{recording_id}:{index}",
                "recording_id": recording_id,
                "recording_sha256": recording_sha256,
                "semantic_action_id": action_id,
                "source_indexes": list(source_indexes),
                "action_kind": validate_text(action.get("kind"), "action kind", max_length=64),
                "target": _optional_text(action.get("target"), "target"),
                "interaction": _optional_text(action.get("interaction"), "interaction"),
                "evidence": list(evidence),
                "fragile": _exact_bool(action.get("fragile", False), "fragile"),
                "recovery": _exact_bool(action.get("recovery", False), "recovery"),
                "rewrite": rewrite,
                "rj3_state": rj3_state,
                "rj4_state": rj4_state,
                "instructional_disposition": "undecided",
                "execution_authorized": False,
            }
        )
    unknown_rewrites = set(rewrites).difference(item["semantic_action_id"] for item in candidates)
    if unknown_rewrites:
        raise ValueError("rewrite operation references unknown semantic action")
    return candidates


def apply_modeling_decision(
    candidate: dict[str, Any],
    *,
    disposition: str,
    step_id: str,
    sequence: int,
    title: str | None = None,
    student_action: str | None = None,
    notice: str | None = None,
    check: str | None = None,
    combined_semantic_action_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Apply the Teacher Modeling decision without altering upstream evidence."""
    _candidate(candidate)
    if disposition not in MODELING_DISPOSITIONS:
        raise ValueError("unsupported instructional disposition")
    step_id = validate_stable_id(step_id, "step_id")
    if type(sequence) is not int or sequence < 1:
        raise ValueError("sequence must be a positive built-in integer")
    if combined_semantic_action_ids is None:
        combined_semantic_action_ids = []
    if type(combined_semantic_action_ids) is not list:
        raise TypeError("combined_semantic_action_ids must be a built-in list")
    semantic_action_ids = [candidate["semantic_action_id"]]
    for action_id in combined_semantic_action_ids:
        checked = validate_stable_id(action_id, "combined semantic action id")
        if checked not in semantic_action_ids:
            semantic_action_ids.append(checked)

    instructional = disposition in {"keep", "combine"}
    if instructional:
        title = validate_text(title, "step title")
        student_action = validate_text(student_action, "student action")
        notice = validate_text(notice, "what students need to notice")
        check = validate_text(check, "check evidence")
    else:
        for value, name in (
            (title, "step title"),
            (student_action, "student action"),
            (notice, "what students need to notice"),
            (check, "check evidence"),
        ):
            if value is not None:
                validate_text(value, name)

    return {
        "step_id": step_id,
        "sequence": sequence,
        "disposition": disposition,
        "title": title,
        "student_action": student_action,
        "notice": notice,
        "check": check,
        "semantic_action_ids": semantic_action_ids,
        "source": {
            "candidate_id": candidate["candidate_id"],
            "recording_id": candidate["recording_id"],
            "recording_sha256": candidate["recording_sha256"],
            "source_indexes": list(candidate["source_indexes"]),
            "rewrite": candidate["rewrite"],
            "rj3_state": candidate["rj3_state"],
            "rj4_state": candidate["rj4_state"],
            "fragile": candidate["fragile"],
            "recovery": candidate["recovery"],
        },
        "execution_authorized": False,
    }


def build_visual_requirement(
    modeling_step: dict[str, Any],
    *,
    visual_state: str,
    must_show: list[str],
    must_not_show: list[str],
    orientation: str = "landscape",
    aspect_target: str = "16:9",
    annotation_space: str = "leave clear space for a later callout",
) -> dict[str, Any]:
    """Append Picture Perfect visual requirements without changing instruction."""
    _modeling_step(modeling_step)
    if modeling_step["disposition"] not in {"keep", "combine"}:
        raise ValueError("non-instructional modeling step cannot produce a visual requirement")
    if visual_state not in VISUAL_STATES:
        raise ValueError("unsupported visual state")
    if orientation not in ORIENTATIONS:
        raise ValueError("unsupported orientation")
    show = _text_list(must_show, "must_show", allow_empty=False)
    avoid = _text_list(must_not_show, "must_not_show")
    annotation_space = validate_text(annotation_space, "annotation_space")
    aspect_target = validate_text(aspect_target, "aspect_target", max_length=64)
    for value in (*show, *avoid, annotation_space):
        if _TECHNICAL_MARKER_RE.search(value):
            raise ValueError("visual requirements cannot expose raw Recorder selector evidence")

    return {
        "visual_id": f"visual:{modeling_step['step_id']}",
        "step_id": modeling_step["step_id"],
        "sequence": modeling_step["sequence"],
        "student_action": modeling_step["student_action"],
        "notice": modeling_step["notice"],
        "check": modeling_step["check"],
        "visual_state": visual_state,
        "must_show": list(show),
        "must_not_show": list(avoid),
        "orientation": orientation,
        "aspect_target": aspect_target,
        "annotation_space": annotation_space,
        "source": modeling_step["source"],
        "semantic_action_ids": list(modeling_step["semantic_action_ids"]),
        "execution_authorized": False,
    }


def build_image_intent(visual_requirement: dict[str, Any]) -> Any:
    """Reject generative reconstruction of Picture Perfect software-tutorial UI."""
    _visual_requirement(visual_requirement)
    raise ValueError(_SOFTWARE_UI_GENERATION_ERROR)


def visual_provenance(visual_requirement: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded provenance chain for review/debugging."""
    _visual_requirement(visual_requirement)
    return {
        "visual_id": visual_requirement["visual_id"],
        "modeling_step_id": visual_requirement["step_id"],
        "semantic_action_ids": list(visual_requirement["semantic_action_ids"]),
        "recording_id": visual_requirement["source"]["recording_id"],
        "recording_sha256": visual_requirement["source"]["recording_sha256"],
        "source_indexes": list(visual_requirement["source"]["source_indexes"]),
    }


def _candidate(value: object) -> None:
    if type(value) is not dict:
        raise TypeError("candidate must be a built-in mapping")
    required = {
        "candidate_id", "recording_id", "recording_sha256", "semantic_action_id",
        "source_indexes", "rewrite", "rj3_state", "rj4_state", "fragile", "recovery",
    }
    if not required.issubset(value):
        raise ValueError("candidate is missing required provenance")
    _source_indexes(value["source_indexes"])
    validate_sha256(value["recording_sha256"], "recording_sha256")
    _evidence_state(value["rj3_state"], "rj3_state")
    _evidence_state(value["rj4_state"], "rj4_state")


def _modeling_step(value: object) -> None:
    if type(value) is not dict:
        raise TypeError("modeling step must be a built-in mapping")
    required = {"step_id", "sequence", "disposition", "student_action", "notice", "check", "semantic_action_ids", "source"}
    if not required.issubset(value):
        raise ValueError("modeling step is missing required fields")
    _candidate({
        "candidate_id": value["source"].get("candidate_id"),
        "recording_id": value["source"].get("recording_id"),
        "recording_sha256": value["source"].get("recording_sha256"),
        "semantic_action_id": value["semantic_action_ids"][0] if value["semantic_action_ids"] else None,
        "source_indexes": value["source"].get("source_indexes"),
        "rewrite": value["source"].get("rewrite"),
        "rj3_state": value["source"].get("rj3_state"),
        "rj4_state": value["source"].get("rj4_state"),
        "fragile": value["source"].get("fragile"),
        "recovery": value["source"].get("recovery"),
    })


def _visual_requirement(value: object) -> None:
    if type(value) is not dict:
        raise TypeError("visual requirement must be a built-in mapping")
    required = {"visual_id", "step_id", "sequence", "student_action", "notice", "check", "visual_state", "must_show", "must_not_show", "orientation", "aspect_target", "annotation_space", "source", "semantic_action_ids"}
    if not required.issubset(value):
        raise ValueError("visual requirement is missing required fields")
    if value["visual_state"] not in VISUAL_STATES:
        raise ValueError("unsupported visual state")


def _source_indexes(value: object) -> tuple[int, ...]:
    if type(value) not in {list, tuple} or not value:
        raise ValueError("source indexes must be a non-empty list or tuple")
    indexes: list[int] = []
    for item in value:
        if type(item) is not int or item < 0:
            raise ValueError("source indexes must contain non-negative built-in integers")
        if item in indexes:
            raise ValueError("source indexes must be unique")
        indexes.append(item)
    return tuple(indexes)


def _text_list(value: object, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if type(value) is not list:
        raise TypeError(f"{name} must be a built-in list")
    if not value and not allow_empty:
        raise ValueError(f"{name} cannot be empty")
    return tuple(validate_text(item, name) for item in value)


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return validate_text(value, name)


def _exact_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a built-in bool")
    return value


def _evidence_state(value: object, name: str) -> str:
    text = validate_text(value, name, max_length=32)
    if text not in RJ_EVIDENCE_STATES:
        raise ValueError(f"unsupported {name}")
    return text
