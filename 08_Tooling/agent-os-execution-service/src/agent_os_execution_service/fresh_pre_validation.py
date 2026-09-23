"""Fresh-process #1985 reconstruction from Option-C vNext provenance.

This module does not create a second approval/currentness engine. It verifies the
persisted canonical proposal-stage material against the APPROVAL_READY packet,
delegates the later human decision to existing #753 projection semantics, then
delegates PR-less validation-plan construction to the existing #1985 seam.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from scripts.agent_os_candidate_packet.approval_stage import (
    ApprovalDecision,
    ApprovalProjectionStageResult,
    ApprovalProjectionStageStatus,
    prepare_approval_projection,
)
from scripts.agent_os_candidate_packet.pre_validation_stage import (
    PreValidationCandidateInputs,
    prepare_pre_validation_stage,
)
from scripts.agent_os_candidate_packet.proposal_stage import RepositoryProposalStageStatus
from scripts.agent_os_candidate_packet.validation_stage import ValidationStageDisposition, ValidationStageResult

from .candidate_approval_provenance import CandidateApprovalProvenanceEvidence, SCHEMA_VERSION


class FreshPreValidationError(RuntimeError):
    """Persisted pre-approval material cannot safely produce a current plan."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FreshPreValidationResult:
    approval_stage_result: ApprovalProjectionStageResult
    validation_stage_result: ValidationStageResult
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def prepare_fresh_pre_validation(
    *,
    provenance: CandidateApprovalProvenanceEvidence,
    approval_decision: ApprovalDecision,
    candidate_inputs: PreValidationCandidateInputs,
    evaluated_at: str,
    projected_at: str,
) -> FreshPreValidationResult:
    """Rebuild #753 projection from exact persisted stage material, then #1985 plan."""
    if type(provenance) is not CandidateApprovalProvenanceEvidence:
        raise TypeError("provenance must be exact CandidateApprovalProvenanceEvidence")
    if provenance.schema_version != SCHEMA_VERSION:
        raise FreshPreValidationError("candidate-provenance-vnext-required")
    proposal_stage = provenance.repository_proposal_stage_result
    if proposal_stage is None or proposal_stage.status is not RepositoryProposalStageStatus.ELIGIBLE:
        raise FreshPreValidationError("candidate-proposal-stage-incomplete")
    proposal = proposal_stage.proposal
    issueplan = proposal_stage.issueplan_current_state_evidence
    repository = proposal_stage.repository_state_evidence
    planning = proposal_stage.planning_binding
    if proposal is None or issueplan is None or repository is None:
        raise FreshPreValidationError("candidate-proposal-evidence-incomplete")

    packet = provenance.approval_ready_packet
    identities = dict(packet.stage_identities)
    expected = {
        "issueplan": issueplan.evidence_id,
        "repository-evidence": repository.evidence_id,
        "proposal": proposal.proposal_id,
    }
    if planning is not None:
        expected["planning-handoff"] = proposal.handoff_digest
    for name, value in expected.items():
        if identities.get(name) != value:
            raise FreshPreValidationError(f"candidate-provenance-drift:{name}")
    if (
        packet.repository.casefold() != proposal.repository.casefold()
        or packet.base_branch != proposal.base_branch
        or packet.base_sha != proposal.evaluated_repository_sha
        or candidate_inputs.repository_state_evidence.evidence_id != repository.evidence_id
    ):
        raise FreshPreValidationError("candidate-currentness-binding-mismatch")

    approval = prepare_approval_projection(
        proposal_stage,
        candidate_context=provenance.candidate_context,
        approval_decision=approval_decision,
        evaluated_at=evaluated_at,
        projected_at=projected_at,
    )
    if approval.status is not ApprovalProjectionStageStatus.COMPLETE:
        raise FreshPreValidationError(
            "approval-projection-not-complete:" + ",".join(approval.reason_codes)
        )
    validation = prepare_pre_validation_stage(approval, candidate_inputs)
    if validation.disposition is not ValidationStageDisposition.GO:
        raise FreshPreValidationError(
            "pre-validation-plan-not-admitted:" + ",".join(validation.reason_codes)
        )
    return FreshPreValidationResult(
        approval_stage_result=approval,
        validation_stage_result=validation,
    )


__all__ = [
    "FreshPreValidationError",
    "FreshPreValidationResult",
    "prepare_fresh_pre_validation",
]
