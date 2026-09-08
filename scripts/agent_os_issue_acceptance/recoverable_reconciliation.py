"""Normalize mechanical lifecycle drift before operating-mode evaluation (#2152).

The canonical IssueOperationalState currently records merged-PR/open-issue and
closed-with-ready-label reconciliation signals as both reasons and blockers.
Those signals describe mechanical synchronization work, not new authority. This
pure seam removes only those two recoverable drift codes from blocker projection
and restores the state outcome needed by the existing operating-mode evaluator.
All authorization, source, freshness, validation, dependency, and claim blockers
remain untouched.
"""

from __future__ import annotations

from dataclasses import replace

from .issue_operational_state import (
    IssueOperationalState,
    IssueState,
    LifecycleStage,
    OperationalOutcome,
)

RECOVERABLE_RECONCILIATION_CODES = frozenset(
    {
        "reconciliation.merged-pr-open-issue",
        "reconciliation.closed-with-ready-label",
    }
)


def normalize_recoverable_reconciliation(
    state: IssueOperationalState,
) -> IssueOperationalState:
    """Return an authority-preserving state suitable for operating-mode routing."""
    if type(state) is not IssueOperationalState:
        raise TypeError("state must be an exact IssueOperationalState")
    if not state.reconciliation_required:
        return state

    recoverable = RECOVERABLE_RECONCILIATION_CODES & set(state.reason_codes)
    if not recoverable:
        return state

    remaining_blockers = tuple(
        code for code in state.blocker_codes if code not in RECOVERABLE_RECONCILIATION_CODES
    )
    if remaining_blockers:
        # Genuine blockers still dominate; reconciliation never grants authority.
        return replace(state, blocker_codes=remaining_blockers)

    # A merged implementation awaiting issue synchronization is productive
    # lifecycle work. Preserve MERGED rather than rewinding it to planning.
    if state.issue_state is IssueState.OPEN and state.lifecycle_stage is LifecycleStage.MERGED:
        return replace(
            state,
            outcome=OperationalOutcome.READY,
            blocker_codes=(),
            state_id="",
        )

    # A closed issue with a stale active label is already terminal; label cleanup
    # is reconciliation metadata, not a reason to invent new lifecycle authority.
    if state.issue_state is IssueState.CLOSED:
        return replace(state, blocker_codes=(), state_id="")

    return state
