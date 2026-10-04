"""Terminal aggregator-gate decision for the Agent OS Validation Gate (#3114).

GitHub reports skipped jobs as Success on the enclosing workflow, so a
skipped authoritative aggregate would otherwise read as a green Validation
Gate. This module is the single decision point the workflow's `aggregate-gate`
job calls: the gate is open only when the authoritative aggregate job itself
reports exactly ``success``. Any other disposition — skipped, failure,
cancelled — closes the gate and can never become merge/Ready authority.

Completed exact-head aggregate success (#2638/#3043 reuse) still reports
``success`` at the job level, so reuse behavior is unchanged.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Iterable, Mapping, NamedTuple

AGGREGATE_JOB_NAME = "Run aggregate validation"

# Canonical future server-required identity (#2589). It is a *commit status*
# published only by authoritative (non-Draft / admitted final-candidate) runs
# of the Agent OS Validation Gate. Ordinary Draft runs never publish it, so
# deferred Draft validation can never satisfy it.
AUTHORITATIVE_STATUS_CONTEXT = "agent-os/authoritative-aggregate"

_OPEN = "authoritative aggregate established on this head; gate open."


def evaluate_aggregate_gate(validate_result: str) -> tuple[bool, str]:
    """Decide the gate disposition from the authoritative aggregate job result.

    Returns ``(gate_open, message)``. The gate opens only for an exact
    ``success`` disposition.
    """
    if type(validate_result) is not str:
        raise TypeError("validate_result must be a string")
    if validate_result == "success":
        return True, _OPEN
    return (
        False,
        f"authoritative aggregate ({AGGREGATE_JOB_NAME}) did not report "
        f"success: {validate_result or 'unreported'}; a skipped aggregate is "
        "not aggregate success; the gate is closed.",
    )


class TerminalStatus(NamedTuple):
    state: str
    description: str


def latest_authoritative_state(statuses: Iterable[Mapping[str, object]]) -> str:
    """Return the state of the newest status for the canonical context.

    ``statuses`` is the GitHub commit-status list for one exact SHA. Only the
    newest entry (highest status ``id``) for ``AUTHORITATIVE_STATUS_CONTEXT``
    governs, so an older ``success`` can never mask a newer contradictory
    ``failure``/``error``/``pending`` (#2761). ``missing`` means no status.
    """
    newest = None
    for entry in statuses:
        if entry.get("context") != AUTHORITATIVE_STATUS_CONTEXT:
            continue
        if newest is None or int(entry.get("id") or 0) > int(newest.get("id") or 0):
            newest = entry
    state = newest.get("state") if newest else None
    return state if state in ("success", "failure", "error", "pending") else "missing"


def evaluate_reuse(statuses: Iterable[Mapping[str, object]]) -> tuple[bool, str]:
    """Decide exact-head reuse: only a latest ``success`` may be reused."""
    state = latest_authoritative_state(statuses)
    return state == "success", state


def decide_terminal_status(
    *,
    authoritative: bool,
    reused: bool,
    validate_result: str,
    aggregate_outcome: str = "",
    main_health_outcome: str = "",
    main_recovery_stop_outcome: str = "",
) -> TerminalStatus | None:
    """Map the authoritative run disposition to the terminal commit status.

    Returns ``None`` when nothing may be published: non-authoritative runs
    (ordinary Draft, diagnostic dispatch, main push) and reused success, where
    the latest ``success`` already stands and re-minting it could overwrite
    newer contradictory evidence.
    """
    if not authoritative:
        return None
    if validate_result == "success":
        if reused:
            return None
        if aggregate_outcome == "success":
            return TerminalStatus("success", "Authoritative aggregate validation passed on this exact head")
        return TerminalStatus("error", "Aggregate job reported success without a successful aggregate step")
    if validate_result == "failure":
        if main_health_outcome == "failure" or main_recovery_stop_outcome == "failure":
            return TerminalStatus(
                "pending",
                "Authority not established: exact-current main health withheld candidate aggregate",
            )
        if aggregate_outcome == "failure":
            return TerminalStatus("failure", "Authoritative aggregate validation failed on this exact head")
        return TerminalStatus("error", "Authoritative aggregate run failed before a verdict (infrastructure)")
    if validate_result == "cancelled":
        return TerminalStatus("error", "Authoritative aggregate run was cancelled; no verdict")
    return TerminalStatus("error", f"Authoritative aggregate run ended {validate_result or 'unreported'}; no verdict")


def status_main() -> int:
    """Print the terminal status as JSON, or nothing when none may be published."""
    env = os.environ.get
    decision = decide_terminal_status(
        authoritative=env("AUTHORITATIVE", "") == "true",
        reused=env("REUSED", "") == "true",
        validate_result=env("VALIDATE_RESULT", ""),
        aggregate_outcome=env("AGGREGATE_OUTCOME", ""),
        main_health_outcome=env("MAIN_HEALTH_OUTCOME", ""),
        main_recovery_stop_outcome=env("MAIN_RECOVERY_STOP_OUTCOME", ""),
    )
    if decision is not None:
        print(json.dumps(decision._asdict()))
    return 0


def main() -> int:
    """Workflow entry point: reads ``VALIDATE_RESULT`` and exits 0/1."""
    validate_result = os.environ.get("VALIDATE_RESULT", "")
    plan_result = os.environ.get("PLAN_RESULT", "")
    gate_open, message = evaluate_aggregate_gate(validate_result)
    print(f"plan job result: {plan_result or 'unreported'}")
    print(f"aggregate job result: {validate_result or 'unreported'}")
    print(message, file=sys.stderr if not gate_open else sys.stdout)
    return 0 if gate_open else 1


if __name__ == "__main__":
    sys.exit(status_main() if sys.argv[1:] == ["status"] else main())
