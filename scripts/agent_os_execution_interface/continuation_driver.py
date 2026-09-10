from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ContinuationDecision:
    action: str
    blocked: bool = False
    stalled: bool = False
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContinuationResult:
    terminal_state: str
    transitions: int
    reason_codes: tuple[str, ...]


def drive_bounded_continuation(
    *,
    observe: Callable[[], Any],
    decide: Callable[[Any], ContinuationDecision],
    dispatch: Callable[[str], None],
    max_transitions: int = 8,
) -> ContinuationResult:
    """Drive an already-authorized finite continuation until terminal evidence.

    Repeating an action name is not itself semantic no-progress: a later
    observation may legitimately require the same bounded transition again.
    The decision layer owns semantic stall detection and signals it explicitly
    with ``stalled=True``.
    """
    if type(max_transitions) is not int or max_transitions < 1:
        raise ValueError("max_transitions must be a positive built-in integer")

    for transition in range(max_transitions + 1):
        decision = decide(observe())
        if type(decision) is not ContinuationDecision:
            raise TypeError("decide must return an exact ContinuationDecision")
        if decision.blocked:
            return ContinuationResult("blocked", transition, decision.reason_codes)
        if decision.stalled:
            return ContinuationResult(
                "recovery-stalled",
                transition,
                decision.reason_codes or ("semantic-no-progress",),
            )
        if not decision.action:
            return ContinuationResult("complete", transition, decision.reason_codes)
        if transition == max_transitions:
            return ContinuationResult(
                "transition-limit-reached",
                transition,
                ("finite-transition-bound-reached",),
            )
        dispatch(decision.action)

    raise AssertionError("unreachable")
