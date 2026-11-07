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


# The plan job is the only place focused (for example Teacher OS React) commands
# run; the aggregate does not repeat them. A plan that ran and did not succeed is
# a verdict on this head, so it must close the gate. ``skipped`` (non-PR events,
# where no plan runs) and an unset value stay neutral and change nothing.
_PLAN_BLOCKING = frozenset({"failure", "cancelled"})


class FrontendBlock(NamedTuple):
    """Why the frontend job closes the gate: the commit-status state to publish
    and a short reason that fits GitHub's 140-character status description."""

    state: str
    reason: str


def frontend_blocker(
    frontend_result: str,
    frontend_required: bool,
    tested_sha: str = "",
    expected_sha: str = "",
) -> FrontendBlock | None:
    """Return why the frontend check job closes the gate, or ``None``.

    The frontend job (``scripts/agent_os_frontend_checks.py``) owns every Node
    project's mandatory checks and runs on pull_request and workflow_dispatch
    events regardless of which validation profile the selector chose. When it is
    ``required`` for the event, only an exact ``success`` may stand: skipped,
    cancelled, failed, or unreported all close the gate, because none of them is
    proof that the applicable frontend checks executed. A job that ran and found
    no applicable project reports ``success`` itself and states that in its
    check annotation and summary, so legitimate non-applicability never needs a
    skip. A required ``success`` must also name the SHA it tested and that SHA
    must be the one this verdict is minted for (``expected_sha``): validation
    evidence from another SHA never stands. When the job is not required
    (``push`` to main, where no frontend job runs) only an explicit failure or
    cancellation blocks.
    """
    if any(type(value) is not str for value in (frontend_result, tested_sha, expected_sha)):
        raise TypeError("job results and SHAs must be strings")
    if frontend_result == "success":
        if frontend_required and expected_sha and tested_sha != expected_sha:
            return FrontendBlock("error", "Frontend checks tested a different SHA than this verdict")
        return None
    if frontend_required or frontend_result in _PLAN_BLOCKING:
        state = "failure" if frontend_result == "failure" else "error"
        return FrontendBlock(state, f"Frontend checks reported {frontend_result or 'unreported'}")
    return None


def _frontend_message(block: FrontendBlock) -> str:
    return (
        f"{block.reason}; only an exact success of the frontend job, tested on the SHA "
        "this verdict covers, proves the applicable frontend checks executed and passed; "
        "the gate is closed."
    )


def evaluate_aggregate_gate(
    validate_result: str,
    plan_result: str = "",
    frontend_result: str = "",
    frontend_required: bool = False,
    frontend_tested_sha: str = "",
    frontend_expected_sha: str = "",
) -> tuple[bool, str]:
    """Decide the gate disposition from the authoritative aggregate job result.

    Returns ``(gate_open, message)``. The gate opens only for an exact
    ``success`` aggregate disposition, a plan job that did not fail, and a
    frontend job that satisfies :func:`frontend_blocker`.
    """
    if type(validate_result) is not str or type(plan_result) is not str:
        raise TypeError("job results must be strings")
    if plan_result in _PLAN_BLOCKING:
        return (
            False,
            f"focused validation plan reported {plan_result}; aggregate success "
            "cannot stand for a head whose focused commands did not pass; the gate is closed.",
        )
    block = frontend_blocker(frontend_result, frontend_required, frontend_tested_sha, frontend_expected_sha)
    if block is not None:
        return False, _frontend_message(block)
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
    plan_result: str = "",
    frontend_result: str = "",
    frontend_required: bool = False,
    frontend_tested_sha: str = "",
    frontend_expected_sha: str = "",
) -> TerminalStatus | None:
    """Map the authoritative run disposition to the terminal commit status.

    Returns ``None`` when nothing may be published: non-authoritative runs
    (ordinary Draft, diagnostic dispatch, main push) and reused success, where
    the latest ``success`` already stands and re-minting it could overwrite
    newer contradictory evidence.
    """
    if not authoritative:
        return None
    if plan_result in _PLAN_BLOCKING:
        # Newest status wins (#2761), so this also supersedes a reused success.
        state = "failure" if plan_result == "failure" else "error"
        return TerminalStatus(state, f"Focused validation plan {plan_result} on this exact head; no verdict can pass")
    block = frontend_blocker(frontend_result, frontend_required, frontend_tested_sha, frontend_expected_sha)
    if block is not None:
        # Same supersession rule as the plan: newest status wins, so this also
        # supersedes a reused aggregate success. A proven failure is a failure;
        # a skipped/missing/cancelled/other-SHA result is "no verdict", never a pass.
        return TerminalStatus(block.state, f"{block.reason} on this exact head; no verdict can pass")
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
        plan_result=env("PLAN_RESULT", ""),
        frontend_result=env("FRONTEND_RESULT", ""),
        frontend_required=env("FRONTEND_REQUIRED", "") == "true",
        frontend_tested_sha=env("FRONTEND_TESTED_SHA", ""),
        frontend_expected_sha=env("FRONTEND_EXPECTED_SHA", ""),
    )
    if decision is not None:
        print(json.dumps(decision._asdict()))
    return 0


def main() -> int:
    """Workflow entry point: reads ``VALIDATE_RESULT`` and exits 0/1."""
    validate_result = os.environ.get("VALIDATE_RESULT", "")
    plan_result = os.environ.get("PLAN_RESULT", "")
    frontend_result = os.environ.get("FRONTEND_RESULT", "")
    frontend_required = os.environ.get("FRONTEND_REQUIRED", "") == "true"
    tested_sha = os.environ.get("FRONTEND_TESTED_SHA", "")
    expected_sha = os.environ.get("FRONTEND_EXPECTED_SHA", "")
    gate_open, message = evaluate_aggregate_gate(
        validate_result, plan_result, frontend_result, frontend_required, tested_sha, expected_sha
    )
    print(f"plan job result: {plan_result or 'unreported'}")
    print(
        f"frontend job result: {frontend_result or 'unreported'} (required: {frontend_required}); "
        f"tested SHA: {tested_sha or 'none'}; verdict SHA: {expected_sha or 'none'}"
    )
    print(f"aggregate job result: {validate_result or 'unreported'}")
    print(message, file=sys.stderr if not gate_open else sys.stdout)
    return 0 if gate_open else 1


if __name__ == "__main__":
    sys.exit(status_main() if sys.argv[1:] == ["status"] else main())
