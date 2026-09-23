"""Requirement-driven visual completeness check for rendered student materials."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class VisualCompletenessResult:
    status: str
    missing_roles: tuple[str, ...] = ()
    unresolved_roles: tuple[str, ...] = ()


def validate_visual_completeness(*, required_roles: tuple[str, ...], verified_roles: tuple[str, ...], unresolved_roles: tuple[str, ...] = ()) -> VisualCompletenessResult:
    required = set(required_roles)
    verified = set(verified_roles)
    unresolved = required & set(unresolved_roles)
    missing = required - verified - unresolved
    if missing:
        return VisualCompletenessResult("fail", tuple(sorted(missing)), tuple(sorted(unresolved)))
    if unresolved:
        return VisualCompletenessResult("manual-review", (), tuple(sorted(unresolved)))
    return VisualCompletenessResult("pass")
