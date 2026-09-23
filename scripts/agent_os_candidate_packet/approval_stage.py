"""Pure-local approval preparation, applicability, and projection stage (#753).

Candidate provenance and a later human approval decision are deliberately
separate immutable inputs. Candidate provenance never confers approval; a
later decision must name a distinct explicit authorizer. This module composes
the canonical #398/#407 contracts; it creates no approval authority, execution
authority, persistence, or external side effect. Any projection remains
non-authoritative and cannot authorize execution.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from scripts.agent_os_issue_acceptance.approval_records import (
    ApprovalApplicabilityResult,
    ApprovalKind,
    ApprovalRecord,
    ApprovalState,
    build_approval_candidate,
    evaluate_approval_applicability,
    reconstruct_approval_applicability_result,
    reconstruct_approval_record,
    record_approval_decision,
    serialize_approval_applicability_result,
    serialize_approval_record,
)
from scripts.agent_os_issue_acceptance.approved_execution_projection import (
    ApprovedExecutionProjection,
    ApprovedExecutionProjectionResult,
    build_approved_execution_projection,
    reconstruct_approved_execution_projection_result,
    serialize_approved_execution_projection_result,
)

from .proposal_stage import RepositoryProposalStageResult, RepositoryProposalStageStatus
from .stage_models import STAGE_SCHEMA_VERSION, require_exact_keys


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


_APPROVAL_PROJECTION_STAGE_RESULT_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "pending_candidate",
        "decision_revision",
        "applicability",
        "projection_result",
        "reason_codes",
        "execution_authorized",
        "side_effects_performed",
    }
)


def approval_projection_stage_result_to_dict(
    result: ApprovalProjectionStageResult,
) -> dict[str, Any]:
    """Serialize one canonical ApprovalProjectionStageResult.

    ``projection`` is not carried as an independent payload field: for a
    complete result it is always ``projection_result``'s own projection
    object, so ``approval_projection_stage_result_from_dict`` recovers it by
    identity rather than transporting a duplicate copy.
    """
    if not isinstance(result, ApprovalProjectionStageResult):
        raise TypeError("result must be an ApprovalProjectionStageResult")
    payload = {
        "schema_version": STAGE_SCHEMA_VERSION,
        "status": result.status.value,
        "pending_candidate": (
            None
            if result.pending_candidate is None
            else json.loads(serialize_approval_record(result.pending_candidate))
        ),
        "decision_revision": (
            None
            if result.decision_revision is None
            else json.loads(serialize_approval_record(result.decision_revision))
        ),
        "applicability": (
            None
            if result.applicability is None
            else json.loads(
                serialize_approval_applicability_result(result.applicability)
            )
        ),
        "projection_result": (
            None
            if result.projection_result is None
            else json.loads(
                serialize_approved_execution_projection_result(
                    result.projection_result
                )
            )
        ),
        "reason_codes": list(result.reason_codes),
        "execution_authorized": False,
        "side_effects_performed": False,
    }
    if approval_projection_stage_result_from_dict(payload) != result:
        raise ValueError("result has noncanonical approval projection stage fields")
    return payload


def approval_projection_stage_result_from_dict(
    payload: Mapping[str, Any],
) -> ApprovalProjectionStageResult:
    """Reconstruct one canonical ApprovalProjectionStageResult, failing closed on drift."""
    if not isinstance(payload, Mapping):
        raise ValueError("approval projection stage result must be a mapping")
    if payload.get("schema_version") != STAGE_SCHEMA_VERSION:
        raise ValueError("unsupported stage schema_version")
    require_exact_keys(
        payload,
        _APPROVAL_PROJECTION_STAGE_RESULT_PAYLOAD_KEYS,
        "approval projection stage result",
    )
    if payload["execution_authorized"] is not False:
        raise ValueError("execution_authorized must be false")
    if payload["side_effects_performed"] is not False:
        raise ValueError("side_effects_performed must be false")

    status = ApprovalProjectionStageStatus(payload["status"])

    pending_candidate_payload = payload["pending_candidate"]
    decision_revision_payload = payload["decision_revision"]
    applicability_payload = payload["applicability"]
    projection_result_payload = payload["projection_result"]

    pending_candidate = (
        None
        if pending_candidate_payload is None
        else reconstruct_approval_record(pending_candidate_payload)
    )
    decision_revision = (
        None
        if decision_revision_payload is None
        else reconstruct_approval_record(decision_revision_payload)
    )
    applicability = (
        None
        if applicability_payload is None
        else reconstruct_approval_applicability_result(applicability_payload)
    )
    projection_result = (
        None
        if projection_result_payload is None
        else reconstruct_approved_execution_projection_result(
            projection_result_payload
        )
    )

    # The nested transports above each verify their own object's internal
    # identity, but nothing yet proves the four carried approval objects all
    # describe the *same* approval lineage. ``approval_id`` is stable across
    # an approval's revisions (see ``ApprovalRecord``/``_approval_id``), so a
    # decision revision must share it with the pending candidate it decided;
    # ``approval_revision`` is a fresh per-revision identity by design, so
    # its exact string is never required to match across revisions -- only
    # ``previous_revision`` lineage is checked instead.
    if pending_candidate is not None and decision_revision is not None:
        if decision_revision.approval_id != pending_candidate.approval_id:
            raise ValueError(
                "decision_revision does not bind to the pending candidate's approval_id"
            )
        if decision_revision.previous_revision != pending_candidate.approval_revision:
            raise ValueError(
                "decision_revision does not continue the pending candidate's revision lineage"
            )

    if applicability is not None:
        reference_record = (
            decision_revision if decision_revision is not None else pending_candidate
        )
        if reference_record is None:
            raise ValueError(
                "applicability cannot be carried without an approval record to bind to"
            )
        if applicability.approval_id != reference_record.approval_id:
            raise ValueError(
                "applicability does not bind to the carried approval record's approval_id"
            )
        if (
            decision_revision is not None
            and applicability.approval_revision != decision_revision.approval_revision
        ):
            raise ValueError(
                "applicability does not bind to the carried decision revision"
            )

    projection = None
    if status is ApprovalProjectionStageStatus.COMPLETE:
        if projection_result is None or not projection_result.complete:
            raise ValueError("complete results require a complete projection result")
        if decision_revision is None:
            raise ValueError("complete results require a decision revision")
        projection = projection_result.projection
        if projection.approval_id != decision_revision.approval_id:
            raise ValueError(
                "projection does not bind to the carried decision revision's approval_id"
            )
        if projection.approval_revision != decision_revision.approval_revision:
            raise ValueError(
                "projection does not bind to the carried decision revision's approval_revision"
            )

    reason_codes = payload["reason_codes"]
    if not isinstance(reason_codes, list) or not all(
        isinstance(item, str) for item in reason_codes
    ):
        raise ValueError("reason_codes must be a list of strings")

    return ApprovalProjectionStageResult(
        status=status,
        pending_candidate=pending_candidate,
        decision_revision=decision_revision,
        applicability=applicability,
        projection_result=projection_result,
        projection=projection,
        reason_codes=tuple(reason_codes),
    )


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
    if approval_decision.authorizer_id == candidate.authorizer_id:
        return _result(
            ApprovalProjectionStageStatus.INVALID,
            candidate,
            None,
            None,
            None,
            ("self-approval-forbidden",),
        )
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
