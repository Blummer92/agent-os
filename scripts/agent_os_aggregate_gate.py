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

import os
import sys

AGGREGATE_JOB_NAME = "Run aggregate validation"

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
    sys.exit(main())
