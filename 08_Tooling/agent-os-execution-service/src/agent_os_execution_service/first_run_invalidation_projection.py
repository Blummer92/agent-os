"""Pure first-run residual invalidation projection for Issue #1970.

The first-run validation-only path has no residual historical invalidation event
once the existing canonical candidate, approval, execution-packet, and validation
evidence owners have positively proved their own currentness/completeness. This
module verifies only those already-produced objects. It performs no I/O,
persistence, current-state acquisition, authorization, Scheduler dispatch, or
execution and never infers event history from silence.
"""
from __future__ import annotations

from scripts.agent_os_candidate_packet.approval_stage import (
    ApprovalProjectionStageResult,
    ApprovalProjectionStageStatus,
)
from scripts.agent_os_candidate_packet.execution_packet_stage import (
    ExecutionPacketDisposition,
    ExecutionPacketStageResult,
)
from scripts.agent_os_candidate_packet.models import CandidatePacket, CandidatePacketPhase
from scripts.agent_os_issue_acceptance.approval_records import ApprovalState
from scripts.agent_os_remote_validation.evidence_bundle import (
    ValidationEvidenceBundle,
    serialize_validation_evidence_bundle,
    validation_evidence_bundle_id,
)


class FirstRunInvalidationProjectionError(ValueError):
    """Raised when canonical evidence cannot positively prove an empty residual."""


def project_first_run_residual_invalidation(
    candidate_packet: CandidatePacket,
    approval_stage: ApprovalProjectionStageResult,
    execution_packet_stage: ExecutionPacketStageResult,
    validation_evidence_bundle: ValidationEvidenceBundle,
) -> tuple[str, ...]:
    """Return the canonical first-run residual tuple after positive proof.

    Approval lifecycle history remains ``ApprovalRecord``-owned; source/scanner,
    binding, identity, projection, and version currentness remain owned by their
    existing IssuePlanCore/currentness operations; validation staleness remains
    independently enforced by approved-projection consumption; and runtime
    capability remains a separate runtime preflight. Consequently the residual
    first-run caller-supplied category is empty when, and only when, the canonical
    evidence below is complete and mutually bound.
    """
    if type(candidate_packet) is not CandidatePacket:
        raise TypeError("candidate_packet must be an exact CandidatePacket")
    if type(approval_stage) is not ApprovalProjectionStageResult:
        raise TypeError("approval_stage must be an exact ApprovalProjectionStageResult")
    if type(execution_packet_stage) is not ExecutionPacketStageResult:
        raise TypeError("execution_packet_stage must be an exact ExecutionPacketStageResult")
    if type(validation_evidence_bundle) is not ValidationEvidenceBundle:
        raise TypeError("validation_evidence_bundle must be an exact ValidationEvidenceBundle")

    # Canonical serializers/constructors own structural validity. Re-serialize
    # the bundle rather than copying its schema rules here.
    serialize_validation_evidence_bundle(validation_evidence_bundle)

    if (
        candidate_packet.phase is not CandidatePacketPhase.EXECUTION_CANDIDATE
        or candidate_packet.evidence_completeness != "complete"
        or candidate_packet.disposition != "verified"
    ):
        raise FirstRunInvalidationProjectionError("candidate evidence is not complete/current")

    if (
        approval_stage.status is not ApprovalProjectionStageStatus.COMPLETE
        or approval_stage.decision_revision is None
        or approval_stage.applicability is None
        or approval_stage.projection is None
        or approval_stage.decision_revision.state is not ApprovalState.APPROVED
        or approval_stage.applicability.status != "applicable"
        or not approval_stage.applicability.approval_applicable
    ):
        raise FirstRunInvalidationProjectionError("approval evidence is not complete/applicable")

    execution = execution_packet_stage
    runtime = execution.runtime_configuration
    validation_stage = execution.validation_stage
    if (
        execution.disposition is not ExecutionPacketDisposition.GO
        or not execution.packet_complete
        or runtime is None
        or execution.request is None
        or execution.command_plan is None
        or validation_stage.validation_plan is None
        or validation_stage.validation_plan_id is None
    ):
        raise FirstRunInvalidationProjectionError("execution-packet evidence is not complete/current")

    bundle = validation_evidence_bundle
    if bundle.status != "passed" or bundle.reason_codes:
        raise FirstRunInvalidationProjectionError("validation evidence is not complete/passed")
    if bundle.validation_plan is None or bundle.plan_id is None:
        raise FirstRunInvalidationProjectionError("validation bundle plan evidence is incomplete")

    projection = approval_stage.projection
    repository_identity = bundle.repository_identity
    repository_name = (
        None
        if repository_identity is None
        else f"{repository_identity.owner}/{repository_identity.repository}"
    )
    expected = (
        (repository_name, candidate_packet.repository),
        (bundle.base_branch, candidate_packet.base_branch),
        (bundle.base_sha, candidate_packet.base_sha),
        (bundle.source_head_sha, candidate_packet.candidate_sha),
        (bundle.tested_sha, candidate_packet.tested_sha),
        (bundle.invocation_id, candidate_packet.invocation_id),
        (bundle.projection_id, projection.projection_id),
        (bundle.proposal_id, projection.proposal_id),
        (bundle.approval_id, projection.approval_id),
        (bundle.repository_state_evidence_id, projection.repository_state_evidence_id),
        (
            bundle.implementation_contract_fingerprint,
            projection.implementation_contract_fingerprint,
        ),
        (runtime.validation_bundle_id, validation_evidence_bundle_id(bundle)),
    )
    if any(
        actual is None or str(actual).casefold() != str(wanted).casefold()
        for actual, wanted in expected
    ):
        raise FirstRunInvalidationProjectionError("validation evidence binding drifted")

    # The candidate runtime intentionally binds the candidate-specific
    # PrePrValidationPlan identity (``pre-pr-validation-plan:*``), while the
    # ValidationEvidenceBundle intentionally binds the remote ValidationPlan
    # identity (``validation-plan:*``). Do not compare those domain-separated
    # IDs. Prove their semantic intersection instead: exact repository/SHA
    # subject and exact ordered command set.
    pre_pr_plan = validation_stage.validation_plan
    remote_plan = bundle.validation_plan
    if tuple(pre_pr_plan.commands) != tuple(remote_plan.commands):
        raise FirstRunInvalidationProjectionError("validation command set drifted")
    if tuple(candidate_packet.required_tests) != tuple(remote_plan.commands):
        raise FirstRunInvalidationProjectionError("candidate validation requirements drifted")
    if tuple(item.test_id for item in runtime.required_test_commands) != tuple(remote_plan.commands):
        raise FirstRunInvalidationProjectionError("runtime validation requirements drifted")

    return ()
