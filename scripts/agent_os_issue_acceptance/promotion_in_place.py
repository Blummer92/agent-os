"""Pure-local deterministic promotion-in-place evaluator (#1309-A).

Compares a planning/design issue's durable contract snapshot against a
proposed post-implementation snapshot and decides whether the existing
issue may be promoted in place to Level 2 (see
`01_Shared_Standards/github/issue-lifecycle-standard.md`) instead of being
superseded by a successor issue. The existing Child-Issue Creation Test in
that standard remains the sole splitting policy; this module does not add a
second one, does not read or write GitHub, and creates no issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

PROMOTION_IN_PLACE_SCHEMA_VERSION = "1.0"


class PromotionDecision(str, Enum):
    PROMOTE_IN_PLACE = "promote-in-place"
    SUCCESSOR_REQUIRED = "successor-required"


_MATERIAL_FLAGS: tuple[str, ...] = (
    "architecture_touched",
    "compatibility_break",
    "external_effect",
    "protected_surface_touched",
)


@dataclass(frozen=True, slots=True)
class IssueScopeSnapshot:
    objective: str
    owner: str
    bounded_scope: tuple[str, ...]
    source_of_truth: str
    risk_tier: int
    architecture_touched: bool = False
    compatibility_break: bool = False
    external_effect: bool = False
    protected_surface_touched: bool = False

    def __post_init__(self) -> None:
        for name in ("objective", "owner", "source_of_truth"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if type(self.bounded_scope) is not tuple or not self.bounded_scope:
            raise ValueError("bounded_scope must be a non-empty tuple")
        if len(set(self.bounded_scope)) != len(self.bounded_scope):
            raise ValueError("bounded_scope must not contain duplicates")
        if (
            not isinstance(self.risk_tier, int)
            or isinstance(self.risk_tier, bool)
            or self.risk_tier not in (0, 1, 2)
        ):
            raise ValueError("risk_tier must be 0, 1, or 2")
        for name in _MATERIAL_FLAGS:
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be bool")


@dataclass(frozen=True, slots=True)
class PromotionEvaluationResult:
    schema_version: str
    decision: PromotionDecision
    reason: str
    changed_fields: tuple[str, ...]


def evaluate_promotion_in_place(
    before: IssueScopeSnapshot,
    after: IssueScopeSnapshot,
) -> PromotionEvaluationResult:
    """Decide promotion-in-place vs. successor issue from two bounded snapshots.

    Promotion in place requires an unchanged objective, owner, bounded
    scope, source of truth, and risk tier, and requires every material
    change flag on ``after`` to be ``False``. Any material flag ``True``, or
    a changed objective/owner/scope/source-of-truth/risk-tier, always
    requires a successor issue under the existing Child-Issue Creation Test.
    Closed historical issues are immutable and are never a valid ``before``
    for this evaluator; that is enforced by the caller's canonical
    issue-state evidence, not re-derived here.
    """
    if not isinstance(before, IssueScopeSnapshot) or not isinstance(
        after, IssueScopeSnapshot
    ):
        raise TypeError("before and after must be IssueScopeSnapshot")

    changed: list[str] = []
    if before.objective != after.objective:
        changed.append("objective")
    if before.owner != after.owner:
        changed.append("owner")
    if tuple(sorted(before.bounded_scope)) != tuple(sorted(after.bounded_scope)):
        changed.append("bounded_scope")
    if before.source_of_truth != after.source_of_truth:
        changed.append("source_of_truth")
    if before.risk_tier != after.risk_tier:
        changed.append("risk_tier")
    for flag in _MATERIAL_FLAGS:
        if getattr(after, flag):
            changed.append(flag)

    changed_fields = tuple(sorted(set(changed)))
    if changed_fields:
        return PromotionEvaluationResult(
            schema_version=PROMOTION_IN_PLACE_SCHEMA_VERSION,
            decision=PromotionDecision.SUCCESSOR_REQUIRED,
            reason=(
                "material change to "
                + ", ".join(changed_fields)
                + " requires a successor issue under the existing Child-Issue"
                " Creation Test"
            ),
            changed_fields=changed_fields,
        )
    return PromotionEvaluationResult(
        schema_version=PROMOTION_IN_PLACE_SCHEMA_VERSION,
        decision=PromotionDecision.PROMOTE_IN_PLACE,
        reason="objective, owner, bounded scope, source of truth, and risk tier are unchanged",
        changed_fields=(),
    )
