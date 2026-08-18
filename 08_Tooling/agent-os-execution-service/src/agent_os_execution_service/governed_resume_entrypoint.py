"""Fixed governed-resume entrypoint contract for Agent OS hosts.

The public contract accepts exactly one immutable ``executor-handoff:<sha256>``
identity. It never accepts command text. Currentness/admission remains owned
by the existing #1218 reconstruction seam and execution remains owned by the
existing Workflow Scheduler boundary supplied by the host composition.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Sequence

HANDOFF_RE = re.compile(r"\Aexecutor-handoff:[0-9a-f]{64}\Z")
SCHEMA = "agent-os-governed-resume-host-evidence/v1"


@dataclass(frozen=True, slots=True)
class GovernedResumeBindings:
    reconstruct: Callable[[str], object]
    dispatch: Callable[[object], object]

    def __post_init__(self) -> None:
        if not callable(self.reconstruct) or not callable(self.dispatch):
            raise TypeError("reconstruct and dispatch must be callable")


def parse_handoff_argv(argv: Sequence[str]) -> str:
    if type(argv) not in (list, tuple):
        raise TypeError("argv must be a list or tuple")
    if len(argv) != 2 or argv[0] != "--handoff-id":
        raise ValueError("expected exactly --handoff-id <canonical-handoff-id>")
    handoff_id = argv[1]
    if type(handoff_id) is not str or HANDOFF_RE.fullmatch(handoff_id) is None:
        raise ValueError("handoff id must be executor-handoff:<64-lowercase-hex>")
    return handoff_id


def _status_value(result: object) -> str | None:
    status = getattr(result, "status", None)
    value = getattr(status, "value", status)
    return value if type(value) is str else None


def _reason_values(result: object) -> tuple[str, ...]:
    raw = getattr(result, "reason_codes", ())
    values: list[str] = []
    if not isinstance(raw, (tuple, list)):
        return ()
    for item in raw:
        value = getattr(item, "value", item)
        if type(value) is str and len(value) <= 80:
            values.append(value)
    return tuple(sorted(set(values)))


def _evidence(*, handoff_id: str, status: str, reasons: tuple[str, ...]) -> str:
    payload = {
        "schema": SCHEMA,
        "handoff_id": handoff_id,
        "status": status,
        "reason_codes": list(reasons),
        "scheduler_dispatch_count": 1 if status == "completed" else 0,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def run_governed_resume(argv: Sequence[str], *, bindings: GovernedResumeBindings) -> str:
    """Reconstruct current state, then dispatch exactly once only when admitted."""
    handoff_id = parse_handoff_argv(argv)
    result = bindings.reconstruct(handoff_id)
    status = _status_value(result)
    reasons = _reason_values(result)
    pilot_input = getattr(result, "pilot_input", None)

    if status != "admitted" or pilot_input is None:
        blocked_status = (
            status
            if status in {"blocked", "stale", "needs-decision"}
            else "needs-decision"
        )
        return _evidence(handoff_id=handoff_id, status=blocked_status, reasons=reasons)

    bindings.dispatch(pilot_input)
    return _evidence(handoff_id=handoff_id, status="completed", reasons=("admitted",))
