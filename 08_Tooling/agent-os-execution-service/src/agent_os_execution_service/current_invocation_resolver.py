"""Composition-only current-evidence resolver for AOS-INV1 (#1218).

This module joins existing canonical readers/builders around the small
checkpoint-owned GovernedInvocationDescriptor. AOS-EXECSIMPL1 (#1338) keeps
that descriptor as a compatibility mirror while also persisting the canonical
RuntimeExecutionRequest through the same publication seam. It performs no
GitHub/network/process/Scheduler/lease mutation itself.

Execution authorization is reacquired through #1226's read-only source
contract. Every other evidence family remains owned by its existing reader or
pure rebuilder supplied through ``InvocationEvidenceSources``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from scripts.agent_os_candidate_packet.models import CandidatePacket, candidate_packet_id
from scripts.agent_os_execution_capabilities.dependencies import DependencyReadinessEvidence
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    AppendInvocationDescriptorOutcome,
    GovernedInvocationDescriptor,
    INVOCATION_DESCRIPTOR_SCHEMA_NAME,
    INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    append_invocation_descriptor,
)
from scripts.agent_os_execution_checkpoint.models import ExecutionCheckpoint
from scripts.agent_os_execution_checkpoint.resume_planner import ResumePlan
from workflow_scheduler.execution.runtime_configuration import ConcreteRuntimeConfiguration
from workflow_scheduler.execution.single_issue_pilot import (
    SingleIssuePilotInput,
    WorkspaceRequest,
    pilot_workspace_identity,
)

from .authorization import ExecutionAuthorizationEvidence
from .execution_authorization_source import (
    ExecutionAuthorizationSourceStatus,
    ExecutionAuthorizationSourceTransport,
    reacquire_execution_authorization,
)
from .executor_routing import ExecutorHandoff, ExecutorRouteDecision
from .governed_resume_restart_capsule import build_restart_capsule
from .invocation_reconstruction import (
    CurrentInvocationEvidence,
    InvocationReconstructionReason,
    _cross_check,
)
from .runtime_execution_request import (
    RuntimeExecutionRequestLoadResult,
    append_runtime_execution_request,
    build_runtime_execution_request,
    load_runtime_execution_request_or_legacy,
)


class CurrentInvocationResolutionError(RuntimeError):
    """The current canonical evidence could not be reacquired safely."""


@runtime_checkable
class InvocationEvidenceSources(Protocol):
    """Read/rebuild each non-authorization evidence family from its owner."""

    def route_decision(
        self, descriptor: GovernedInvocationDescriptor
    ) -> ExecutorRouteDecision: ...

    def handoff(
        self,
        descriptor: GovernedInvocationDescriptor,
        route_decision: ExecutorRouteDecision,
    ) -> ExecutorHandoff: ...

    def checkpoint(
        self, descriptor: GovernedInvocationDescriptor
    ) -> ExecutionCheckpoint: ...

    def resume_plan(
        self,
        descriptor: GovernedInvocationDescriptor,
        checkpoint: ExecutionCheckpoint,
    ) -> ResumePlan: ...

    def candidate_packet(
        self, descriptor: GovernedInvocationDescriptor
    ) -> CandidatePacket: ...

    def runtime_configuration(
        self,
        descriptor: GovernedInvocationDescriptor,
        candidate_packet: CandidatePacket,
    ) -> ConcreteRuntimeConfiguration: ...

    def dependency_readiness(
        self, descriptor: GovernedInvocationDescriptor
    ) -> DependencyReadinessEvidence: ...

    def pilot_input(
        self,
        descriptor: GovernedInvocationDescriptor,
        *,
        route_decision: ExecutorRouteDecision,
        handoff: ExecutorHandoff,
        authorization: ExecutionAuthorizationEvidence,
        checkpoint: ExecutionCheckpoint,
        resume_plan: ResumePlan,
        candidate_packet: CandidatePacket,
        runtime_configuration: ConcreteRuntimeConfiguration,
        dependency_readiness: DependencyReadinessEvidence,
    ) -> SingleIssuePilotInput: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalCurrentInvocationResolver:
    """Concrete #1218 resolver that composes existing canonical owners."""

    sources: InvocationEvidenceSources
    authorization_transport: ExecutionAuthorizationSourceTransport
    evaluated_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.sources, InvocationEvidenceSources):
            raise TypeError("sources must satisfy InvocationEvidenceSources")
        if not isinstance(
            self.authorization_transport, ExecutionAuthorizationSourceTransport
        ):
            raise TypeError(
                "authorization_transport must satisfy ExecutionAuthorizationSourceTransport"
            )
        if type(self.evaluated_at) is not str or not self.evaluated_at.strip():
            raise TypeError("evaluated_at must be non-empty text")

    def reacquire(
        self, descriptor: GovernedInvocationDescriptor
    ) -> CurrentInvocationEvidence:
        if type(descriptor) is not GovernedInvocationDescriptor:
            raise TypeError("descriptor must be an exact GovernedInvocationDescriptor")

        route_decision = self.sources.route_decision(descriptor)
        handoff = self.sources.handoff(descriptor, route_decision)
        checkpoint = self.sources.checkpoint(descriptor)
        resume_plan = self.sources.resume_plan(descriptor, checkpoint)
        packet = self.sources.candidate_packet(descriptor)
        runtime_configuration = self.sources.runtime_configuration(descriptor, packet)
        dependency_readiness = self.sources.dependency_readiness(descriptor)

        command_plan_id = handoff.validation_command_plan_id_or_none
        if command_plan_id is None:
            command_plan_id = route_decision.validation_command_plan_id_or_none
        if command_plan_id is None:
            raise CurrentInvocationResolutionError(
                "current route/handoff has no validation command-plan identity"
            )

        authorization = reacquire_execution_authorization(
            transport=self.authorization_transport,
            repository=descriptor.repository,
            issue_number=descriptor.issue_number,
            expected_candidate_packet_id=candidate_packet_id(packet),
            expected_invocation_id=descriptor.invocation_id,
            expected_operation=route_decision.requested_operation,
            expected_request_fingerprint=(
                descriptor.execution_service_request_fingerprint
            ),
            expected_command_plan_id=command_plan_id,
            expected_sha=descriptor.source_sha,
            evaluated_at=self.evaluated_at,
            expected_authorization_id=descriptor.authorization_id,
        )
        if authorization.evidence is None:
            raise CurrentInvocationResolutionError(
                "current execution authorization is unavailable: "
                + ",".join(reason.value for reason in authorization.reason_codes)
            )
        if authorization.status is ExecutionAuthorizationSourceStatus.NEEDS_DECISION:
            raise CurrentInvocationResolutionError(
                "current execution authorization is ambiguous: "
                + ",".join(reason.value for reason in authorization.reason_codes)
            )

        pilot_input = self.sources.pilot_input(
            descriptor,
            route_decision=route_decision,
            handoff=handoff,
            authorization=authorization.evidence,
            checkpoint=checkpoint,
            resume_plan=resume_plan,
            candidate_packet=packet,
            runtime_configuration=runtime_configuration,
            dependency_readiness=dependency_readiness,
        )
        return CurrentInvocationEvidence(
            route_decision=route_decision,
            handoff=handoff,
            authorization=authorization.evidence,
            checkpoint=checkpoint,
            resume_plan=resume_plan,
            candidate_packet=packet,
            runtime_configuration=runtime_configuration,
            dependency_readiness=dependency_readiness,
            pilot_input=pilot_input,
        )


def build_current_invocation_descriptor(
    *,
    route_decision: ExecutorRouteDecision,
    handoff: ExecutorHandoff,
    authorization: ExecutionAuthorizationEvidence,
    checkpoint: ExecutionCheckpoint,
    resume_plan: ResumePlan,
    candidate_packet: CandidatePacket,
    runtime_configuration: ConcreteRuntimeConfiguration,
    dependency_readiness: DependencyReadinessEvidence,
    pilot_input: SingleIssuePilotInput,
) -> GovernedInvocationDescriptor:
    """Build the existing bounded descriptor without persisting it."""

    required = (
        (route_decision.execution_service_request_fingerprint_or_none, "request"),
        (route_decision.authorization_id_or_none, "authorization"),
        (route_decision.environment_profile_id_or_none, "environment profile"),
        (
            route_decision.environment_health_evidence_id_or_none,
            "environment health",
        ),
        (route_decision.workflow_runtime_identity_or_none, "workflow runtime"),
        (handoff.source_ref_or_none, "source ref"),
        (handoff.source_sha_or_none, "source SHA"),
    )
    missing = tuple(label for value, label in required if value is None)
    if missing:
        raise ValueError(
            "runnable handoff is missing descriptor bindings: " + ", ".join(missing)
        )

    workspace_identity = pilot_workspace_identity(
        WorkspaceRequest(
            workspace_request_id=pilot_input.workspace_request_id,
            repository=pilot_input.repository,
            branch=pilot_input.branch,
            expected_revision=pilot_input.source_head_sha,
        )
    )
    return GovernedInvocationDescriptor(
        schema_name=INVOCATION_DESCRIPTOR_SCHEMA_NAME,
        schema_version=INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        repository=checkpoint.repository,
        issue_number=checkpoint.issue_number,
        issue_or_handoff_identity=handoff.issue_or_handoff_identity,
        handoff_id=handoff.handoff_id,
        route_decision_id=route_decision.decision_id,
        execution_service_request_fingerprint=(
            route_decision.execution_service_request_fingerprint_or_none
        ),
        authorization_id=authorization.authorization_id,
        source_ref=handoff.source_ref_or_none,
        source_sha=handoff.source_sha_or_none,
        checkpoint_id=checkpoint.checkpoint_id,
        resume_plan_id=resume_plan.plan_id,
        environment_profile_id=route_decision.environment_profile_id_or_none,
        environment_health_evidence_id=(
            route_decision.environment_health_evidence_id_or_none
        ),
        required_environment_id=dependency_readiness.required_environment_id,
        dependency_readiness_evidence_id=(
            dependency_readiness.dependency_readiness_evidence_id
        ),
        execution_surface_id=dependency_readiness.execution_surface_id,
        workspace_identity=workspace_identity,
        workflow_runtime_identity=route_decision.workflow_runtime_identity_or_none,
        candidate_packet_id=candidate_packet_id(candidate_packet),
        runtime_configuration_fingerprint=(
            runtime_configuration.configuration_fingerprint
        ),
        execution_id=checkpoint.execution_id,
        invocation_id=checkpoint.invocation_id,
    )


def validate_current_invocation_bindings(
    descriptor: GovernedInvocationDescriptor,
    current: CurrentInvocationEvidence,
    *,
    evaluated_at: str,
) -> set[InvocationReconstructionReason]:
    """Reuse #1218's current-evidence cross-check without observing a lease."""

    if type(descriptor) is not GovernedInvocationDescriptor:
        raise TypeError("descriptor must be an exact GovernedInvocationDescriptor")
    if type(current) is not CurrentInvocationEvidence:
        raise TypeError("current must be an exact CurrentInvocationEvidence")
    return _cross_check(descriptor, current, evaluated_at=evaluated_at)


def load_current_invocation_descriptor(
    store_root: Path | str,
    handoff_id: str,
) -> GovernedInvocationDescriptor:
    """Prefer #1338's canonical request and fall back to the legacy record graph."""

    loaded: RuntimeExecutionRequestLoadResult = load_runtime_execution_request_or_legacy(
        store_root, handoff_id
    )
    return loaded.request.invocation_descriptor


def persist_current_invocation_descriptor(
    store_root: Path | str,
    *,
    route_decision: ExecutorRouteDecision,
    handoff: ExecutorHandoff,
    authorization: ExecutionAuthorizationEvidence,
    checkpoint: ExecutionCheckpoint,
    resume_plan: ResumePlan,
    candidate_packet: CandidatePacket,
    runtime_configuration: ConcreteRuntimeConfiguration,
    dependency_readiness: DependencyReadinessEvidence,
    pilot_input: SingleIssuePilotInput,
) -> AppendInvocationDescriptorOutcome:
    """Persist the canonical runtime request plus the legacy descriptor mirror.

    The legacy descriptor remains the compatibility publication marker during
    the additive #1338 migration. The canonical RuntimeExecutionRequest is
    persisted through this same bounded seam and carries no authority of its
    own. No old record is deleted or rewritten.
    """

    descriptor = build_current_invocation_descriptor(
        route_decision=route_decision,
        handoff=handoff,
        authorization=authorization,
        checkpoint=checkpoint,
        resume_plan=resume_plan,
        candidate_packet=candidate_packet,
        runtime_configuration=runtime_configuration,
        dependency_readiness=dependency_readiness,
        pilot_input=pilot_input,
    )
    descriptor_outcome = append_invocation_descriptor(store_root, descriptor)
    restart_capsule = build_restart_capsule(
        handoff_id=handoff.handoff_id,
        candidate_packet=candidate_packet,
        pilot_input=pilot_input,
        required_environment_spec=runtime_configuration.required_environment_spec,
        created_at=route_decision.created_at,
        expires_at=route_decision.expires_at,
    )
    request = build_runtime_execution_request(
        route_decision=route_decision,
        handoff=handoff,
        invocation_descriptor=descriptor,
        restart_capsule=restart_capsule,
    )
    append_runtime_execution_request(store_root, request)
    return descriptor_outcome
