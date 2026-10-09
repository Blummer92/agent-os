"""Requirement-driven visual completeness check for rendered student materials.

Completeness keys on (role_id, slot_id) bindings (#3251): one role with N
slots is N distinct completeness obligations. Plain role-id strings keep
working and address the implicit slot "0", so existing callers
(worksheet_revision_qa) are unaffected.
"""
from __future__ import annotations
from dataclasses import dataclass

IMPLICIT_SLOT_ID = "0"


@dataclass(frozen=True)
class VisualCompletenessResult:
    status: str
    missing_roles: tuple[str, ...] = ()
    unresolved_roles: tuple[str, ...] = ()


def _binding_key(value: object) -> tuple[str, str]:
    """Normalize one completeness entry to a (role_id, slot_id) binding."""
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("visual role identity must be non-empty text")
        return (value, IMPLICIT_SLOT_ID)
    try:
        role_id, slot_id = value  # type: ignore[misc]
    except (TypeError, ValueError):
        raise ValueError("visual completeness entries must be role ids or (role_id, slot_id) pairs") from None
    if not isinstance(role_id, str) or not role_id.strip():
        raise ValueError("visual role identity must be non-empty text")
    if not isinstance(slot_id, str) or not slot_id.strip():
        raise ValueError("visual slot identity must be non-empty text")
    return (role_id, slot_id)


def _display(binding: tuple[str, str]) -> str:
    role_id, slot_id = binding
    if slot_id == IMPLICIT_SLOT_ID:
        return role_id
    return f"{role_id}:{slot_id}"


def validate_visual_completeness(*, required_roles: tuple[object, ...], verified_roles: tuple[object, ...], unresolved_roles: tuple[object, ...] = ()) -> VisualCompletenessResult:
    required = {_binding_key(role) for role in required_roles}
    verified = {_binding_key(role) for role in verified_roles}
    unresolved = required & {_binding_key(role) for role in unresolved_roles}
    missing = required - verified - unresolved
    if missing:
        return VisualCompletenessResult("fail", tuple(sorted(_display(binding) for binding in missing)), tuple(sorted(_display(binding) for binding in unresolved)))
    if unresolved:
        return VisualCompletenessResult("manual-review", (), tuple(sorted(_display(binding) for binding in unresolved)))
    return VisualCompletenessResult("pass")
