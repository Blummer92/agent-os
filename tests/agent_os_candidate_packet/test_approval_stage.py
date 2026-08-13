"""Focused AOS-AUTO1D approval/projection coordinator tests (#753)."""

from dataclasses import replace

import pytest

from scripts.agent_os_candidate_packet.approval_stage import (
    ApprovalCandidateContext,
    ApprovalDecision,
    ApprovalProjectionStageResult,
    ApprovalProjectionStageStatus,
    approval_projection_stage_result_from_dict,
    approval_projection_stage_result_to_dict,
    prepare_approval_projection,
)
from scripts.agent_os_candidate_packet.stage_models import STAGE_SCHEMA_VERSION
from scripts.agent_os_issue_acceptance import ApprovalKind, ApprovalState
from scripts.agent_os_issue_acceptance.approved_execution_projection import (
    serialize_approved_execution_projection,
)
from tests.agent_os_candidate_packet.test_proposal_stage import _observation, _prepare

_CANDIDATE_AT = "2026-08-06T04:05:00Z"
_APPROVED_AT = "2026-08-06T04:10:00Z"
_EVALUATED_AT = "2026-08-06T04:15:00Z"
_PROJECTED_AT = "2026-08-06T04:15:00Z"
_EXPIRES_AT = "2026-08-06T05:00:00Z"
_EXPIRED_AT = "2026-08-06T05:00:01Z"


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
        decision_at=_EXPIRED_AT if state is ApprovalState.EXPIRED else _APPROVED_AT,
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
    assert first.pending_candidate.authorizer_id == "candidate-preparer"
    assert first.pending_candidate.decision_id == "candidate-753"
    assert first.decision_revision is None
    assert first.projection is None
    assert first.execution_authorized is False
    assert first.side_effects_performed is False


def test_candidate_preparer_cannot_self_approve() -> None:
    result = prepare_approval_projection(
        _prepare(),
        candidate_context=_context(),
        approval_decision=ApprovalDecision(
            state=ApprovalState.APPROVED,
            decision_id="self-approved-753",
            authorizer_id="candidate-preparer",
            decision_at=_APPROVED_AT,
        ),
        evaluated_at=_EVALUATED_AT,
        projected_at=_PROJECTED_AT,
    )

    assert result.status is ApprovalProjectionStageStatus.INVALID
    assert result.reason_codes == ("self-approval-forbidden",)
    assert result.decision_revision is None
    assert result.applicability is None
    assert result.projection is None
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_human_decision_authorizer_cannot_be_inferred() -> None:
    with pytest.raises(ValueError, match="authorizer_id"):
        ApprovalDecision(
            state=ApprovalState.APPROVED,
            decision_id="missing-authorizer-753",
            authorizer_id="",
            decision_at=_APPROVED_AT,
        )


def test_explicit_human_approval_reaches_complete_projection() -> None:
    upstream = _prepare()
    result = prepare_approval_projection(
        upstream,
        candidate_context=_context(),
        approval_decision=_decision(),
        evaluated_at=_EVALUATED_AT,
        projected_at=_PROJECTED_AT,
    )

    assert result.status is ApprovalProjectionStageStatus.COMPLETE
    assert result.decision_revision.state is ApprovalState.APPROVED
    assert result.decision_revision.authorizer_id == "repository-owner"
    assert result.decision_revision.decision_id == "human-approved-753"
    assert result.pending_candidate.authorizer_id != result.decision_revision.authorizer_id
    assert result.pending_candidate.decision_id != result.decision_revision.decision_id
    assert result.applicability.approval_applicable is True
    assert result.projection is result.projection_result.projection
    assert result.projection.handoff_digest == upstream.proposal.handoff_digest
    assert result.projection.graph_digest == upstream.proposal.graph_digest
    assert result.projection.planning_result_digest == upstream.proposal.planning_result_digest
    assert result.projection.authoritative is False
    assert result.projection.execution_authorized is False
    assert result.projection.side_effects_performed is False


def test_complete_projection_serialization_is_deterministic() -> None:
    first = prepare_approval_projection(
        _prepare(),
        candidate_context=_context(),
        approval_decision=_decision(),
        evaluated_at=_EVALUATED_AT,
        projected_at=_PROJECTED_AT,
    )
    second = prepare_approval_projection(
        _prepare(),
        candidate_context=_context(),
        approval_decision=_decision(),
        evaluated_at=_EVALUATED_AT,
        projected_at=_PROJECTED_AT,
    )

    assert first.status is ApprovalProjectionStageStatus.COMPLETE
    assert second.status is ApprovalProjectionStageStatus.COMPLETE
    assert first.projection.projection_id == second.projection.projection_id
    assert serialize_approved_execution_projection(first.projection) == serialize_approved_execution_projection(
        second.projection
    )


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


def test_expired_decision_never_projects() -> None:
    result = prepare_approval_projection(
        _prepare(),
        candidate_context=_context(),
        approval_decision=_decision(ApprovalState.EXPIRED),
        evaluated_at=_EXPIRED_AT,
        projected_at=_EXPIRED_AT,
    )

    assert result.status is ApprovalProjectionStageStatus.EXPIRED
    assert result.decision_revision.state is ApprovalState.EXPIRED
    assert result.projection is None
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_superseded_decision_never_projects() -> None:
    result = prepare_approval_projection(
        _prepare(),
        candidate_context=_context(),
        approval_decision=_decision(ApprovalState.SUPERSEDED),
        evaluated_at=_EVALUATED_AT,
        projected_at=_PROJECTED_AT,
    )

    assert result.status is ApprovalProjectionStageStatus.SUPERSEDED
    assert result.decision_revision.state is ApprovalState.SUPERSEDED
    assert result.projection is None
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_binding_drift_fails_closed_before_projection() -> None:
    upstream = _prepare()
    object.__setattr__(upstream.proposal, "handoff_digest", "f" * 64)

    result = prepare_approval_projection(
        upstream,
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


# --------------------------------------------------------------------------
# ApprovalProjectionStageResult transport (#1054).
# --------------------------------------------------------------------------


def _complete() -> ApprovalProjectionStageResult:
    result = prepare_approval_projection(
        _prepare(),
        candidate_context=_context(),
        approval_decision=_decision(),
        evaluated_at=_EVALUATED_AT,
        projected_at=_PROJECTED_AT,
    )
    assert result.status is ApprovalProjectionStageStatus.COMPLETE
    return result


def test_complete_result_round_trips_to_an_identical_payload() -> None:
    result = _complete()

    payload = approval_projection_stage_result_to_dict(result)
    rebuilt = approval_projection_stage_result_from_dict(payload)

    assert type(rebuilt) is ApprovalProjectionStageResult
    assert rebuilt == result
    assert rebuilt.projection is rebuilt.projection_result.projection
    assert approval_projection_stage_result_to_dict(rebuilt) == payload
    assert payload["schema_version"] == STAGE_SCHEMA_VERSION
    assert payload["execution_authorized"] is False
    assert payload["side_effects_performed"] is False


def test_needs_decision_result_with_only_a_pending_candidate_round_trips() -> None:
    result = prepare_approval_projection(
        _prepare(),
        candidate_context=_context(),
        evaluated_at=_EVALUATED_AT,
        projected_at=_PROJECTED_AT,
    )
    assert result.status is ApprovalProjectionStageStatus.NEEDS_DECISION
    assert result.pending_candidate is not None
    assert result.decision_revision is None
    assert result.projection_result is None

    payload = approval_projection_stage_result_to_dict(result)
    rebuilt = approval_projection_stage_result_from_dict(payload)

    assert rebuilt == result
    assert payload["decision_revision"] is None
    assert payload["applicability"] is None
    assert payload["projection_result"] is None


def test_unsupported_schema_version_is_rejected() -> None:
    payload = approval_projection_stage_result_to_dict(_complete())
    bad = {**payload, "schema_version": "9.9"}

    with pytest.raises(ValueError, match="unsupported stage schema_version"):
        approval_projection_stage_result_from_dict(bad)


def test_unknown_field_is_rejected() -> None:
    payload = approval_projection_stage_result_to_dict(_complete())
    bad = {**payload, "surprise": 1}

    with pytest.raises(ValueError, match="unsupported field"):
        approval_projection_stage_result_from_dict(bad)


def test_missing_field_is_rejected() -> None:
    payload = approval_projection_stage_result_to_dict(_complete())
    bad = dict(payload)
    del bad["projection_result"]

    with pytest.raises(ValueError, match="missing field"):
        approval_projection_stage_result_from_dict(bad)


def test_malformed_status_enum_is_rejected() -> None:
    payload = approval_projection_stage_result_to_dict(_complete())
    bad = {**payload, "status": "not-a-real-status"}

    with pytest.raises(ValueError):
        approval_projection_stage_result_from_dict(bad)


def test_wrong_nested_projection_result_type_is_rejected() -> None:
    payload = approval_projection_stage_result_to_dict(_complete())
    bad = {**payload, "projection_result": "not-an-object"}

    with pytest.raises((ValueError, TypeError)):
        approval_projection_stage_result_from_dict(bad)


def test_incomplete_projection_result_cannot_back_a_complete_status() -> None:
    payload = approval_projection_stage_result_to_dict(_complete())
    tampered = dict(payload["projection_result"])
    tampered["complete"] = False
    tampered["status"] = "blocked"
    tampered["projection"] = None
    bad = {**payload, "projection_result": tampered}

    with pytest.raises(ValueError):
        approval_projection_stage_result_from_dict(bad)


def test_approval_record_identity_drift_is_rejected() -> None:
    """The nested ApprovalRecord transport's own identity check still applies."""
    payload = approval_projection_stage_result_to_dict(_complete())
    tampered_candidate = dict(payload["pending_candidate"])
    tampered_candidate["approval_id"] = "approval:" + "0" * 64
    bad = {**payload, "pending_candidate": tampered_candidate}

    with pytest.raises(ValueError):
        approval_projection_stage_result_from_dict(bad)


def test_execution_authorized_set_true_is_rejected() -> None:
    payload = approval_projection_stage_result_to_dict(_complete())
    bad = {**payload, "execution_authorized": True}

    with pytest.raises(ValueError, match="execution_authorized must be false"):
        approval_projection_stage_result_from_dict(bad)


def test_side_effects_performed_set_true_is_rejected() -> None:
    payload = approval_projection_stage_result_to_dict(_complete())
    bad = {**payload, "side_effects_performed": True}

    with pytest.raises(ValueError, match="side_effects_performed must be false"):
        approval_projection_stage_result_from_dict(bad)


def test_reason_codes_are_canonicalized() -> None:
    result = replace(_complete(), reason_codes=("zeta", "alpha", "alpha"))

    payload = approval_projection_stage_result_to_dict(result)

    assert payload["reason_codes"] == ["alpha", "zeta"]


def test_a_foreign_object_is_rejected_at_serialization() -> None:
    with pytest.raises(TypeError):
        approval_projection_stage_result_to_dict(_observation())
