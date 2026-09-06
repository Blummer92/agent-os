"""Pure first-run residual invalidation projection for Issue #1970.

This module is a composition proof only. It performs no I/O, persistence,
current-state acquisition, authorization, Scheduler dispatch, or execution and
never infers event history from silence.
"""
from __future__ import annotations

from scripts.agent_os_candidate_packet.approval_stage import ApprovalProjectionStageStatus
from scripts.agent_os_candidate_packet.execution_packet_stage import ExecutionPacketDisposition
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from scripts.agent_os_issue_acceptance.approval_records import (
    APPROVAL_INVALIDATION_REASON_CODES,
    ApprovalState,
)
from scripts.agent_os_remote_validation.evidence_bundle import (
    ValidationEvidenceBundle,
    serialize_validation_evidence_bundle,
    validation_evidence_bundle_id,
)


class FirstRunInvalidationProjectionError(ValueError):
    """Canonical evidence cannot positively prove an empty residual tuple."""


def canonical_invalidation_events(value: object) -> tuple[str, ...]:
    """Normalize only the ratified #347 approval-invalidation vocabulary."""
    if type(value) is not tuple:
        raise TypeError("invalidation_events must be an exact tuple")
    if len(value) > 256:
        raise ValueError("invalidation_events exceeds the bounded count")
    if any(type(item) is not str or not item for item in value):
        raise ValueError("invalidation_events must contain non-empty exact strings")
    if len(set(value)) != len(value):
        raise ValueError("invalidation_events must be unique")
    normalized = tuple(sorted(value))
    if value != normalized:
        raise ValueError("invalidation_events must be canonically sorted")
    unsupported = set(value) - APPROVAL_INVALIDATION_REASON_CODES
    if unsupported:
        raise ValueError(f"unsupported invalidation_events: {sorted(unsupported)}")
    return normalized


def project_first_run_residual_invalidation(
    candidate_packet: object,
    approval_stage: object,
    execution_packet_stage: object,
    validation_evidence_bundle: ValidationEvidenceBundle,
) -> tuple[str, ...]:
    """Return ``()`` only after existing owners prove complete/current evidence."""
    if getattr(candidate_packet, "phase", None) is not CandidatePacketPhase.EXECUTION_CANDIDATE:
        raise FirstRunInvalidationProjectionError("candidate is not execution-candidate")
    if (
        getattr(candidate_packet, "evidence_completeness", None) != "complete"
        or getattr(candidate_packet, "disposition", None) != "verified"
    ):
        raise FirstRunInvalidationProjectionError("candidate evidence is incomplete")

    if (
        getattr(approval_stage, "status", None) is not ApprovalProjectionStageStatus.COMPLETE
        or getattr(approval_stage, "decision_revision", None) is None
        or getattr(approval_stage, "applicability", None) is None
        or getattr(approval_stage, "projection", None) is None
    ):
        raise FirstRunInvalidationProjectionError("approval evidence is incomplete")
    if approval_stage.decision_revision.state is not ApprovalState.APPROVED:
        raise FirstRunInvalidationProjectionError("approval is not approved")
    if (
        approval_stage.applicability.status != "applicable"
        or not approval_stage.applicability.approval_applicable
    ):
        raise FirstRunInvalidationProjectionError("approval is not applicable")

    execution = execution_packet_stage
    runtime = getattr(execution, "runtime_configuration", None)
    validation_stage = getattr(execution, "validation_stage", None)
    if (
        getattr(execution, "disposition", None) is not ExecutionPacketDisposition.GO
        or not getattr(execution, "packet_complete", False)
        or runtime is None
        or getattr(execution, "request", None) is None
        or getattr(execution, "command_plan", None) is None
        or validation_stage is None
        or getattr(validation_stage, "validation_plan", None) is None
    ):
        raise FirstRunInvalidationProjectionError("execution-packet evidence is incomplete")

    if type(validation_evidence_bundle) is not ValidationEvidenceBundle:
        raise TypeError("validation_evidence_bundle must be exact ValidationEvidenceBundle")
    serialize_validation_evidence_bundle(validation_evidence_bundle)
    bundle = validation_evidence_bundle
    if bundle.status != "passed" or bundle.reason_codes or bundle.validation_plan is None:
        raise FirstRunInvalidationProjectionError("validation evidence is not complete/passed")

    projection = approval_stage.projection
    identity = bundle.repository_identity
    repository = None if identity is None else f"{identity.owner}/{identity.repository}"
    bindings = (
        (repository, candidate_packet.repository),
        (bundle.base_branch, candidate_packet.base_branch),
        (bundle.base_sha, candidate_packet.base_sha),
        (bundle.source_head_sha, candidate_packet.candidate_sha),
        (bundle.tested_sha, candidate_packet.tested_sha),
        (bundle.invocation_id, candidate_packet.invocation_id),
        (bundle.projection_id, projection.projection_id),
        (bundle.proposal_id, projection.proposal_id),
        (bundle.approval_id, projection.approval_id),
        (bundle.repository_state_evidence_id, projection.repository_state_evidence_id),
        (bundle.implementation_contract_fingerprint, projection.implementation_contract_fingerprint),
        (runtime.validation_bundle_id, validation_evidence_bundle_id(bundle)),
    )
    if any(
        actual is None or str(actual).casefold() != str(expected).casefold()
        for actual, expected in bindings
    ):
        raise FirstRunInvalidationProjectionError("validation evidence binding drifted")

    # The runtime binds a candidate-specific PrePrValidationPlan identity while
    # the bundle binds a standard remote ValidationPlan identity. Those IDs are
    # deliberately domain-separated, so prove their shared semantic facts.
    commands = tuple(bundle.validation_plan.commands)
    if tuple(validation_stage.validation_plan.commands) != commands:
        raise FirstRunInvalidationProjectionError("validation command set drifted")
    if tuple(candidate_packet.required_tests) != commands:
        raise FirstRunInvalidationProjectionError("candidate validation requirements drifted")
    if tuple(item.test_id for item in runtime.required_test_commands) != commands:
        raise FirstRunInvalidationProjectionError("runtime validation requirements drifted")

    return ()


def build_first_run_authorized_validation_request(
    *, validation_evidence_bundle: ValidationEvidenceBundle, **request_fields: object
):
    """Retain the exact bundle in memory and compose canonical schema 1.1."""
    from .authorized_validation import (
        AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION,
        build_authorized_validation_lifecycle_request,
    )

    events = project_first_run_residual_invalidation(
        request_fields["candidate_packet"],
        request_fields["approval_stage"],
        request_fields["execution_packet_stage"],
        validation_evidence_bundle,
    )
    return build_authorized_validation_lifecycle_request(
        **request_fields,
        schema_version=AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION,
        validation_evidence_bundle=validation_evidence_bundle,
        invalidation_events=events,
    )
