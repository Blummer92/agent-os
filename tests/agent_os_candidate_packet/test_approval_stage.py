"""Focused AOS-AUTO1D approval/projection coordinator tests (#753)."""

from dataclasses import replace

from scripts.agent_os_candidate_packet.approval_stage import (
    ApprovalCandidateContext,
    ApprovalDecision,
    ApprovalProjectionStageStatus,
    prepare_approval_projection,
)
from scripts.agent_os_issue_acceptance import ApprovalKind, ApprovalState
from scripts.agent_os_issue_acceptance.planning_binding import (
    compute_planning_binding_fingerprint,
)
from tests.agent_os_candidate_packet.test_proposal_stage import _prepare

_CANDIDATE_AT = "2026-08-06T04:05:00Z"
_APPROVED_AT = "2026-08-06T04:10:00Z"
_EVALUATED_AT = "2026-08-06T04:15:00Z"
_PROJECTED_AT = "2026-08-06T04:15:00Z"
_EXPIRES_AT = "2026-08-06T05:00:00Z"


def _context() -> ApprovalCandidateContext:
    return ApprovalCandidateContext(
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id="candidate-preparer",
        decision_id="candidate-753",
        decision_at=_CANDIDATE_AT,
        expires_at=_EXPIRES_AT,
    )


def _decision(state=ApprovalState.APPROVED) -> ApprovalDecision:
    return ApprovalDecision(
        state=state,
        decision_id=f"human-{state.value}-753",
        authorizer_id="repository-owner",
        decision_at=_APPROVED_AT,
    )


def test_missing_human_decision_preserves_deterministic_pending_candidate() -> None:
    upstream = _prepare()
    first = prepare_approval_projection(
        upstream,
        candidate_context=_context(),
        evaluated_at=_EVALUATED_AT,
        projected_at=_PROJECTED_AT,
    )
    second = prepare_approval_projection(
        upstream,
        candidate_context=_context(),
        evaluated_at=_EVALUATED_AT,
        projected_at=_PROJECTED_AT,
    )

    assert first.status is ApprovalProjectionStageStatus.NEEDS_DECISION
    assert first.pending_candidate.state is ApprovalState.PENDING
    assert first.pending_candidate.approval_id == second.pending_candidate.approval_id
    assert first.decision_revision is None
    assert first.projection is None
    assert first.execution_authorized is False
    assert first.side_effects_performed is False


def test_explicit_human_approval_reaches_complete_projection_through_exact_binding() -> None:
    upstream = _prepare()
    result = prepare_approval_projection(
        upstream,
        candidate_context=_context(),
        approval_decision=_decision(),
        evaluated_at=_EVALUATED_AT,
        projected_at=_PROJECTED_AT,
    )

    assert upstream.planning_binding is not None
    assert result.status is ApprovalProjectionStageStatus.COMPLETE
    assert result.decision_revision.state is ApprovalState.APPROVED
    assert result.applicability.approval_applicable is True
    assert result.projection is result.projection_result.projection
    assert result.projection.authoritative is False
    assert result.projection.execution_authorized is False
    assert result.projection.side_effects_performed is False


def test_rejection_never_projects() -> None:
    result = prepare_approval_projection(
        _prepare(),
        candidate_context=_context(),
        approval_decision=_decision(ApprovalState.REJECTED),
        evaluated_at=_EVALUATED_AT,
        projected_at=_PROJECTED_AT,
    )

    assert result.status is ApprovalProjectionStageStatus.REJECTED
    assert result.projection is None
    assert result.execution_authorized is False


def test_binding_drift_fails_closed_before_projection() -> None:
    upstream = _prepare()
    binding = upstream.planning_binding
    assert binding is not None
    changed = replace(binding, handoff_digest="f" * 64, binding_id="")
    drifted_binding = replace(
        changed,
        binding_id=compute_planning_binding_fingerprint(changed),
    )
    drifted = replace(upstream, planning_binding=drifted_binding)

    result = prepare_approval_projection(
        drifted,
        candidate_context=_context(),
        approval_decision=_decision(),
        evaluated_at=_EVALUATED_AT,
        projected_at=_PROJECTED_AT,
    )

    assert result.status in {
        ApprovalProjectionStageStatus.INVALID,
        ApprovalProjectionStageStatus.STALE,
    }
    assert result.projection is None
