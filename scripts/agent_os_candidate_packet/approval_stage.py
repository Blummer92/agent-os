"""Pure-local approval preparation, applicability, and projection stage (#753).

Candidate provenance and a later human approval decision are deliberately
separate immutable inputs. This module composes the canonical #398/#407
contracts; it creates no approval authority, execution authority, persistence,
or external side effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from scripts.agent_os_issue_acceptance.approval_records import (
    ApprovalApplicabilityResult,
    ApprovalKind,
    ApprovalRecord,
    ApprovalState,
    build_approval_candidate,
    evaluate_approval_applicability,
    record_approval_decision,
)
from scripts.agent_os_issue_acceptance.approved_execution_projection import (
    ApprovedExecutionProjection,
    ApprovedExecutionProjectionResult,
    build_approved_execution_projection,
)

from .proposal_stage import RepositoryProposalStageResult, RepositoryProposalStageStatus


class ApprovalProjectionStageStatus(str, Enum):
    COMPLETE = "complete"
    NEEDS_DECISION = "needs-decision"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"
    STALE = "stale"
    BLOCKED = "blocked"
    INVALID = "invalid"
    INVALID_INPUT = "invalid-input"


@dataclass(frozen=True, slots=True)
class ApprovalCandidateContext:
    """Explicit provenance for revision-1 pending-candidate construction only."""
    approval_kind: ApprovalKind
    authorizer_id: str
    decision_id: str
    decision_at: str
    expires_at: str | None = None
    supersedes: ApprovalRecord | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.approval_kind, ApprovalKind):
            raise TypeError("approval_kind must be an ApprovalKind")
        for name in ("authorizer_id", "decision_id", "decision_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty text")
        if self.expires_at is not None and not isinstance(self.expires_at, str):
            raise TypeError("expires_at must be text or None")
        if self.supersedes is not None and not isinstance(self.supersedes, ApprovalRecord):
            raise TypeError("supersedes must be an ApprovalRecord or None")


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """Externally supplied immutable human decision; never inferred here."""
    state: ApprovalState
    decision_id: str
    authorizer_id: str
    decision_at: str
    reason_codes: tuple[str, ...] = ()
    details: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state, ApprovalState):
            raise TypeError("state must be an ApprovalState")
        if self.state is ApprovalState.PENDING:
            raise ValueError("a human decision cannot transition to pending")
        for name in ("decision_id", "authorizer_id", "decision_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty text")
        if not isinstance(self.reason_codes, tuple) or not all(isinstance(item, str) for item in self.reason_codes):
            raise TypeError("reason_codes must be a tuple of strings")
        if not isinstance(self.details, tuple) or not all(isinstance(item, str) for item in self.details):
            raise TypeError("details must be a tuple of strings")


@dataclass(frozen=True, slots=True)
class ApprovalProjectionStageResult:
    status: ApprovalProjectionStageStatus
    pending_candidate: ApprovalRecord | None
    decision_revision: ApprovalRecord | None
    applicability: ApprovalApplicabilityResult | None
    projection_result: ApprovedExecutionProjectionResult | None
    projection: ApprovedExecutionProjection | None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ApprovalProjectionStageStatus):
            raise TypeError("status must be an ApprovalProjectionStageStatus")
        if self.pending_candidate is not None and not isinstance(self.pending_candidate, ApprovalRecord):
            raise TypeError("pending_candidate must be an ApprovalRecord or None")
        if self.decision_revision is not None and not isinstance(self.decision_revision, ApprovalRecord):
            raise TypeError("decision_revision must be an ApprovalRecord or None")
        if self.applicability is not None and not isinstance(self.applicability, ApprovalApplicabilityResult):
            raise TypeError("applicability must be an ApprovalApplicabilityResult or None")
        if self.projection_result is not None and not isinstance(self.projection_result, ApprovedExecutionProjectionResult):
            raise TypeError("projection_result must be an ApprovedExecutionProjectionResult or None")
        if self.projection is not None and not isinstance(self.projection, ApprovedExecutionProjection):
            raise TypeError("projection must be an ApprovedExecutionProjection or None")
        if self.status is ApprovalProjectionStageStatus.COMPLETE:
            if self.projection_result is None or not self.projection_result.complete:
                raise ValueError("complete results require a complete projection result")
            if self.projection is not self.projection_result.projection:
                raise ValueError("projection must be the projection result's exact object")
        elif self.projection is not None:
            raise ValueError("non-complete results cannot carry a projection")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))


def prepare_approval_projection(
    repository_proposal_stage_result: RepositoryProposalStageResult,
    *,
    candidate_context: ApprovalCandidateContext,
    approval_decision: ApprovalDecision | None = None,
    evaluated_at: str,
    projected_at: str,
) -> ApprovalProjectionStageResult:
    if not isinstance(repository_proposal_stage_result, RepositoryProposalStageResult):
        raise TypeError("repository_proposal_stage_result must be a RepositoryProposalStageResult")
    if not isinstance(candidate_context, ApprovalCandidateContext):
        raise TypeError("candidate_context must be an ApprovalCandidateContext")
    if approval_decision is not None and not isinstance(approval_decision, ApprovalDecision):
        raise TypeError("approval_decision must be an ApprovalDecision or None")
    upstream = repository_proposal_stage_result
    if upstream.status is not RepositoryProposalStageStatus.ELIGIBLE:
        return _result(ApprovalProjectionStageStatus.INVALID_INPUT, None, None, None, None, upstream.reason_codes)
    proposal = upstream.proposal
    issueplan = upstream.issueplan_current_state_evidence
    repository = upstream.repository_state_evidence
    if proposal is None or issueplan is None or repository is None:
        return _result(ApprovalProjectionStageStatus.INVALID_INPUT, None, None, None, None, ("upstream-evidence-incomplete",))
    try:
        candidate = build_approval_candidate(
            proposal,
            issueplan,
            repository,
            approval_kind=candidate_context.approval_kind,
            authorizer_id=candidate_context.authorizer_id,
            decision_id=candidate_context.decision_id,
            decision_at=candidate_context.decision_at,
            expires_at=candidate_context.expires_at,
            supersedes=candidate_context.supersedes,
            planning_binding=upstream.planning_binding,
        )
    except (TypeError, ValueError):
        return _result(ApprovalProjectionStageStatus.INVALID, None, None, None, None, ("approval-candidate-invalid",))
    if approval_decision is None:
        return _result(ApprovalProjectionStageStatus.NEEDS_DECISION, candidate, None, None, None, ("human-decision-required",))
    try:
        revision = record_approval_decision(
            candidate,
            state=approval_decision.state,
            decision_id=approval_decision.decision_id,
            authorizer_id=approval_decision.authorizer_id,
            decision_at=approval_decision.decision_at,
            reason_codes=approval_decision.reason_codes,
            details=approval_decision.details,
        )
    except (TypeError, ValueError):
        return _result(ApprovalProjectionStageStatus.INVALID, candidate, None, None, None, ("approval-decision-invalid",))
    applicability = evaluate_approval_applicability(
        revision,
        proposal,
        issueplan,
        repository,
        evaluated_at=evaluated_at,
        planning_binding=upstream.planning_binding,
    )
    lifecycle_status = {
        ApprovalState.REJECTED: ApprovalProjectionStageStatus.REJECTED,
        ApprovalState.EXPIRED: ApprovalProjectionStageStatus.EXPIRED,
        ApprovalState.INVALIDATED: ApprovalProjectionStageStatus.INVALIDATED,
        ApprovalState.SUPERSEDED: ApprovalProjectionStageStatus.SUPERSEDED,
    }.get(revision.state)
    if lifecycle_status is not None:
        return _result(lifecycle_status, candidate, revision, applicability, None, applicability.reason_codes)
    if applicability.status != "applicable":
        status = {
            "stale": ApprovalProjectionStageStatus.STALE,
            "blocked": ApprovalProjectionStageStatus.BLOCKED,
            "invalid": ApprovalProjectionStageStatus.INVALID,
            "needs-decision": ApprovalProjectionStageStatus.NEEDS_DECISION,
        }[applicability.status]
        return _result(status, candidate, revision, applicability, None, applicability.reason_codes)
    projection_result = build_approved_execution_projection(
        proposal,
        revision,
        applicability,
        issueplan,
        repository,
        projected_at=projected_at,
        planning_binding=upstream.planning_binding,
    )
    if not projection_result.complete:
        status = {
            "stale": ApprovalProjectionStageStatus.STALE,
            "blocked": ApprovalProjectionStageStatus.BLOCKED,
            "invalid": ApprovalProjectionStageStatus.INVALID,
            "needs-decision": ApprovalProjectionStageStatus.NEEDS_DECISION,
        }.get(projection_result.status, ApprovalProjectionStageStatus.INVALID)
        return _result(status, candidate, revision, applicability, projection_result, projection_result.reason_codes)
    return ApprovalProjectionStageResult(
        status=ApprovalProjectionStageStatus.COMPLETE,
        pending_candidate=candidate,
        decision_revision=revision,
        applicability=applicability,
        projection_result=projection_result,
        projection=projection_result.projection,
    )


def _result(status, candidate, revision, applicability, projection_result, reasons):
    return ApprovalProjectionStageResult(
        status=status,
        pending_candidate=candidate,
        decision_revision=revision,
        applicability=applicability,
        projection_result=projection_result,
        projection=None,
        reason_codes=reasons,
    )
