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


def continuation_payload(decision: ContinuationDecision) -> dict[str, object]:
    """Project one canonical non-authorizing host continuation payload."""
    if type(decision) is not ContinuationDecision:
        raise TypeError("decision must be an exact ContinuationDecision")
    return {
        "action": decision.action,
        "terminal": decision.terminal,
        "blocked": decision.blocked,
        "stalled": decision.stalled,
        "reason_codes": list(decision.reason_codes),
        "execution_authorized": False,
        "github_writes_authorized": False,
        "side_effects_performed": False,
    }


def completion_continuation_payload(
    *,
    terminal: bool,
    blocked: bool,
    next_action: str,
    reason_codes: tuple[str, ...],
) -> dict[str, object]:
    """Project already-decided completion facts into the canonical host payload."""
    return continuation_payload(
        ContinuationDecision(
            action="" if terminal or blocked else next_action,
            terminal=terminal,
            blocked=blocked,
            reason_codes=reason_codes,
        )
    )


def drive_governed_continuation(adapter: ContinuationAdapter, decide: Callable[[object], ContinuationDecision], *, max_transitions: int = MAX_DRIVER_TRANSITIONS) -> ContinuationDriveResult:
    if type(max_transitions) is not int or max_transitions < 1 or max_transitions > MAX_DRIVER_TRANSITIONS:
        raise ValueError("max_transitions is outside the governed finite bound")
    transitions = []
    for _ in range(max_transitions):
        decision = decide(adapter.observe())
        if decision.terminal:
            return ContinuationDriveResult("completed", tuple(transitions), decision.reason_codes)
        if decision.blocked:
            return ContinuationDriveResult("blocked", tuple(transitions), decision.reason_codes)
        if decision.stalled:
            return ContinuationDriveResult("recovery-stalled", tuple(transitions), tuple(sorted(set(decision.reason_codes) | {"repeated-equivalent-transition"})))
        if not decision.action:
            return ContinuationDriveResult("blocked", tuple(transitions), ("no-authorized-executable-next-action",))
        adapter.dispatch(decision.action)
        transitions.append(decision.action)
    return ContinuationDriveResult("recovery-stalled", tuple(transitions), ("finite-transition-bound-exhausted",))
