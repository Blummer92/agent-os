from __future__ import annotations

from dataclasses import dataclass

_LOCAL_TERMINAL = frozenset({"already-fixed", "duplicate", "external-owner", "separately-gated", "no-residual-gap"})
_SHARED_BLOCKERS = frozenset({"authorization-blocked", "source-of-truth-blocked", "capability-blocked", "material-decision-required"})


@dataclass(frozen=True, slots=True)
class BatchCursorDecision:
    action: str
    next_index: int | None
    parent_complete: bool
    reason_codes: tuple[str, ...]


def advance_finite_batch(*, current_index: int, candidate_count: int, candidate_disposition: str) -> BatchCursorDecision:
    if type(current_index) is not int or type(candidate_count) is not int or current_index < 0 or candidate_count < 1 or current_index >= candidate_count:
        raise ValueError("batch cursor bounds are invalid")
    if candidate_disposition == "needs-residual-gap-proof":
        return BatchCursorDecision("investigate-current-candidate", current_index, False, ("residual-gap-proof-required",))
    if candidate_disposition in _SHARED_BLOCKERS:
        return BatchCursorDecision("stop-parent-batch", None, False, (candidate_disposition,))
    if candidate_disposition in _LOCAL_TERMINAL or candidate_disposition in {"pr-created", "implemented"}:
        next_index = current_index + 1
        if next_index < candidate_count:
            return BatchCursorDecision("advance-next-candidate", next_index, False, ("candidate-local-disposition",))
        return BatchCursorDecision("batch-exhausted", None, True, ("reconciled-candidate-pool-exhausted",))
    raise ValueError("unsupported candidate disposition")
