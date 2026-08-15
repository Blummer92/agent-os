"""Many-to-one Teacher Modeling combination helper for Picture Perfect integration."""

from __future__ import annotations

from typing import Any

from .picture_perfect_integration import apply_modeling_decision


def apply_combined_modeling_decision(
    candidates: list[dict[str, Any]],
    *,
    step_id: str,
    sequence: int,
    title: str,
    student_action: str,
    notice: str,
    check: str,
) -> dict[str, Any]:
    """Combine multiple evidence candidates while preserving every source index."""
    if type(candidates) is not list or len(candidates) < 2:
        raise ValueError("combine requires at least two modeling candidates")
    first = candidates[0]
    required = {
        "candidate_id",
        "recording_id",
        "recording_sha256",
        "semantic_action_id",
        "source_indexes",
        "rewrite",
        "rj3_state",
        "rj4_state",
        "fragile",
        "recovery",
    }
    if type(first) is not dict or not required.issubset(first):
        raise ValueError("combine candidate is missing required provenance")

    semantic_ids: list[str] = []
    source_indexes: list[int] = []
    rewrites: list[Any] = []
    fragile = False
    recovery = False
    for candidate in candidates:
        if type(candidate) is not dict or not required.issubset(candidate):
            raise ValueError("combine candidate is missing required provenance")
        if (
            candidate["recording_id"] != first["recording_id"]
            or candidate["recording_sha256"] != first["recording_sha256"]
        ):
            raise ValueError("combined candidates must share recording identity")
        if candidate["rj3_state"] != first["rj3_state"] or candidate["rj4_state"] != first["rj4_state"]:
            raise ValueError("combined candidates have conflicting RJ evidence state")
        if candidate["semantic_action_id"] in semantic_ids:
            raise ValueError("combined candidates contain duplicate semantic action identity")
        semantic_ids.append(candidate["semantic_action_id"])
        for source_index in candidate["source_indexes"]:
            if type(source_index) is not int or source_index < 0:
                raise ValueError("combined candidate source index is invalid")
            if source_index in source_indexes:
                raise ValueError("combined candidates contain duplicate source indexes")
            source_indexes.append(source_index)
        rewrites.append(candidate["rewrite"])
        fragile = fragile or candidate["fragile"]
        recovery = recovery or candidate["recovery"]

    merged = dict(first)
    merged["candidate_id"] = "modeling-combination:" + "+".join(semantic_ids)
    merged["source_indexes"] = sorted(source_indexes)
    merged["rewrite"] = rewrites
    merged["fragile"] = fragile
    merged["recovery"] = recovery

    return apply_modeling_decision(
        merged,
        disposition="combine",
        step_id=step_id,
        sequence=sequence,
        title=title,
        student_action=student_action,
        notice=notice,
        check=check,
        combined_semantic_action_ids=semantic_ids[1:],
    )
