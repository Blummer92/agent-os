from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

MAX_DRIVER_TRANSITIONS = 12


@dataclass(frozen=True, slots=True)
class ContinuationDecision:
    action: str
    terminal: bool = False
    blocked: bool = False
    stalled: bool = False
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContinuationDriveResult:
    status: str
    transitions: tuple[str, ...]
    reason_codes: tuple[str, ...]
    user_turns_required: int = 0


class ContinuationAdapter(Protocol):
    def observe(self) -> object: ...
    def dispatch(self, action: str) -> None: ...


def drive_governed_continuation(adapter: ContinuationAdapter, decide: Callable[[object], ContinuationDecision], *, max_transitions: int = MAX_DRIVER_TRANSITIONS) -> ContinuationDriveResult:
    if type(max_transitions) is not int or max_transitions < 1 or max_transitions > MAX_DRIVER_TRANSITIONS:
        raise ValueError("max_transitions is outside the governed finite bound")
    transitions = []
    prior_action = None
    for _ in range(max_transitions):
        decision = decide(adapter.observe())
        if decision.terminal:
            return ContinuationDriveResult("completed", tuple(transitions), decision.reason_codes)
        if decision.blocked:
            return ContinuationDriveResult("blocked", tuple(transitions), decision.reason_codes)
        if decision.stalled or (prior_action is not None and decision.action == prior_action):
            return ContinuationDriveResult("recovery-stalled", tuple(transitions), tuple(sorted(set(decision.reason_codes) | {"repeated-equivalent-transition"})))
        if not decision.action:
            return ContinuationDriveResult("blocked", tuple(transitions), ("no-authorized-executable-next-action",))
        adapter.dispatch(decision.action)
        transitions.append(decision.action)
        prior_action = decision.action
    return ContinuationDriveResult("recovery-stalled", tuple(transitions), ("finite-transition-bound-exhausted",))
