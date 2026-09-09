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
    _AUTHORITY_REASON_PREFIX,
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

# Authority is carried by the AuthorityProjection fields, which this seam never
# touches, and `evaluate_operating_mode_decision` re-derives every
# `authorization.*` blocker from those projections while advancing stages. A
# merged PR whose issue is still open therefore *always* carries
# `authorization.closure-not-authorized`; treating that structural code as a
# dominating blocker made this seam a permanent no-op and reproduced the exact
# #2152 defect it exists to fix. Non-authorization blockers still dominate.
_AUTHORITY_DERIVED_PREFIXES = tuple(
    sorted(f"{prefix}-" for prefix in _AUTHORITY_REASON_PREFIX.values())
)


def _is_authority_derived(code: str) -> bool:
    """Return whether the operating-mode evaluator re-derives `code` itself."""
    return code.startswith(_AUTHORITY_DERIVED_PREFIXES)


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
    if any(not _is_authority_derived(code) for code in remaining_blockers):
        # Genuine blockers still dominate; reconciliation never grants authority.
        # `state_id` is content-bound, so it must be recomputed from the new
        # blocker projection rather than carried over from the input state.
        return replace(state, blocker_codes=remaining_blockers, state_id="")

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
