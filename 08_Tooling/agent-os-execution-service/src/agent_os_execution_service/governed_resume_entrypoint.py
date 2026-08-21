"""Fixed governed-resume entrypoint contract for Agent OS hosts.

The public contract accepts exactly one immutable ``executor-handoff:<sha256>``
identity. It never accepts command text. Currentness/admission remains owned
by the existing #1218 reconstruction seam and execution remains owned by the
existing Workflow Scheduler boundary supplied by the host composition.

``main``/``__main__`` make the module genuinely runnable as
``python3 -m agent_os_execution_service.governed_resume_entrypoint``.
``build_governed_resume_bindings`` composes the real #1218
``reconstruct_governed_invocation`` seam and the real #758/#1253 Workflow
Scheduler ``run_single_issue_pilot`` boundary into the single-argument shape
this module's bindings require; it performs no reconstruction or dispatch
logic itself.

AOS-GCE1 (#1217) wires the installed default path to the repository-owned #1319
production host bootstrap.  The import is deliberately lazy and occurs only
after the fixed argv contract has been validated, so malformed caller input
cannot trigger host configuration, credential, repository, process, or
Scheduler work.  Explicitly injected bindings remain unchanged for tests and
other governed callers, and ``_no_host_composition_bindings`` remains the
explicit fail-closed stand-in when a caller intentionally wants no host
composition.
"""

from __future__ import annotations

import functools
import json
import re
import sys
from dataclasses import dataclass
from typing import Callable, Sequence

from .invocation_reconstruction import reconstruct_governed_invocation

from workflow_scheduler.execution.single_issue_pilot import run_single_issue_pilot

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


def build_governed_resume_bindings(
    *,
    descriptor_loader: Callable[[str], object],
    resolver: object,
    lease_reader: object,
    evaluated_at: str,
    lease: object,
    workspace: object,
    executor: object | None,
    validator: object,
    cancelled: Callable[[], bool],
) -> GovernedResumeBindings:
    """Wire the real #1218 reconstruction seam and #758 Scheduler boundary.

    Every keyword argument is an existing canonical protocol implementation
    supplied by the caller/host. This function performs no reconstruction or
    dispatch logic of its own -- it only adapts the multi-argument canonical
    call shapes of ``reconstruct_governed_invocation`` and
    ``run_single_issue_pilot`` into the single-argument
    ``Callable[[str], object]``/``Callable[[object], object]`` shape
    ``GovernedResumeBindings`` requires.
    """
    reconstruct = functools.partial(
        reconstruct_governed_invocation,
        descriptor_loader=descriptor_loader,
        resolver=resolver,
        lease_reader=lease_reader,
        evaluated_at=evaluated_at,
    )
    dispatch = functools.partial(
        run_single_issue_pilot,
        lease=lease,
        workspace=workspace,
        executor=executor,
        validator=validator,
        cancelled=cancelled,
    )
    return GovernedResumeBindings(reconstruct, dispatch)


def _no_host_composition_bindings(handoff_id: str) -> object:
    raise RuntimeError(
        "governed-resume requires host-supplied #1218/#1253 composition; "
        "no production reconstruction/dispatch binding is available"
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    bindings: GovernedResumeBindings | None = None,
) -> int:
    """Parse fixed argv, select production composition, then dispatch at most once."""
    if argv is None:
        argv = sys.argv[1:]
    if bindings is None:
        handoff_id = parse_handoff_argv(argv)
        from .production_governed_resume_factory import (
            build_production_governed_resume_bindings_for_handoff,
        )

        bindings = build_production_governed_resume_bindings_for_handoff(handoff_id)
    print(run_governed_resume(argv, bindings=bindings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
