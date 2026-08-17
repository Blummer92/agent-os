"""AOS-INV1 (#1218) one-id governed invocation reconstruction/admission seam.

The caller supplies one immutable ``executor-handoff:<sha256>`` identity plus
injected read-only/local evidence providers.  This module loads the small
checkpoint-owned invocation descriptor, reacquires the current canonical
objects through exactly one resolver call, cross-checks their existing
identities, observes the existing Scheduler lease without acquiring it, and
returns the exact current ``SingleIssuePilotInput`` only when every binding is
still current.

No command text, path, provider prompt, package instruction, workflow payload,
or arbitrary argv enters this interface.  The module performs no GitHub,
network, subprocess, cloud, VM-lifecycle, merge, issue-closure, retry, lease
acquisition/release, or Scheduler execution.  Existing Scheduler lease truth
remains the sole concurrency authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from scripts.agent_os_candidate_packet.models import (
    CandidatePacket,
    CandidatePacketPhase,
    candidate_packet_id,
)
from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
)
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    GovernedInvocationDescriptor,
    InvocationDescriptorIntegrityError,
    InvocationDescriptorNotFound,
)
from scripts.agent_os_execution_checkpoint.models import (
    ExecutionCheckpoint,
    InvalidationState,
    LifecycleState,
)
from scripts.agent_os_execution_checkpoint.resume_planner import ResumePlan
from workflow_scheduler.execution.host_local_lease_adapter import HostLocalLeaseObservation
from workflow_scheduler.execution.runtime_configuration import (
    ConcreteRuntimeConfiguration,
    ConcreteRuntimeConfigurationError,
)
from workflow_scheduler.execution.single_issue_pilot import (
    PilotLeaseRequest,
    SingleIssuePilotInput,
    pilot_lease_identity,
)

from .authorization import ExecutionAuthorizationEvidence
from .executor_routing import ExecutorHandoff, ExecutorRoute, ExecutorRouteDecision

INVOCATION_RECONSTRUCTION_SCHEMA_NAME = "agent-os-governed-invocation-reconstruction"
INVOCATION_RECONSTRUCTION_SCHEMA_VERSION = "1.0"
_MAX_TEXT = 4096


class InvocationReconstructionStatus(str, Enum):
    ADMITTED = "admitted"
    BLOCKED = "blocked"
    STALE = "stale"
    NEEDS_DECISION = "needs-decision"


class InvocationReconstructionReason(str, Enum):
    ADMITTED = "admitted"
    DESCRIPTOR_MISSING = "descriptor-missing"
    DESCRIPTOR_INVALID = "descriptor-invalid"
    CURRENT_EVIDENCE_UNAVAILABLE = "current-evidence-unavailable"
    CURRENT_EVIDENCE_MALFORMED = "current-evidence-malformed"
    ROUTE_DECISION_MISMATCH = "route-decision-mismatch"
    HANDOFF_MISMATCH = "handoff-mismatch"
    ROUTE_NOT_GOVERNED_RUNNER = "route-not-governed-runner"
    EXECUTION_NOT_AUTHORIZED = "execution-not-authorized"
    AUTHORIZATION_MISMATCH = "authorization-mismatch"
    AUTHORIZATION_NOT_CURRENT = "authorization-not-current"
    SOURCE_MISMATCH = "source-mismatch"
    SCOPE_MISMATCH = "scope-mismatch"
    CHECKPOINT_MISMATCH = "checkpoint-mismatch"
    CHECKPOINT_NOT_CURRENT = "checkpoint-not-current"
    RESUME_PLAN_MISMATCH = "resume-plan-mismatch"
    RESUME_PLAN_COMPLETE = "resume-plan-complete"
    ENVIRONMENT_MISMATCH = "environment-mismatch"
    DEPENDENCY_READINESS_MISMATCH = "dependency-readiness-mismatch"
    DEPENDENCY_NOT_READY = "dependency-not-ready"
    CANDIDATE_PACKET_MISMATCH = "candidate-packet-mismatch"
    CANDIDATE_PACKET_NOT_EXECUTABLE = "candidate-packet-not-executable"
    RUNTIME_CONFIGURATION_MISMATCH = "runtime-configuration-mismatch"
    PILOT_INPUT_MISMATCH = "pilot-input-mismatch"
    LEASE_OBSERVATION_UNAVAILABLE = "lease-observation-unavailable"
    LEASE_IDENTITY_MISMATCH = "lease-identity-mismatch"
    LEASE_AMBIGUOUS = "lease-ambiguous"
    LEASE_CONFLICT = "lease-conflict"
    INVOCATION_ALREADY_CONSUMED = "invocation-already-consumed"


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentInvocationEvidence:
    """Exact current canonical objects returned by the injected reacquirer."""

    route_decision: ExecutorRouteDecision
    handoff: ExecutorHandoff
    authorization: ExecutionAuthorizationEvidence
    checkpoint: ExecutionCheckpoint
    resume_plan: ResumePlan
    candidate_packet: CandidatePacket
    runtime_configuration: ConcreteRuntimeConfiguration
    dependency_readiness: DependencyReadinessEvidence
    pilot_input: SingleIssuePilotInput

    def __post_init__(self) -> None:
        exact = (
            ("route_decision", self.route_decision, ExecutorRouteDecision),
            ("handoff", self.handoff, ExecutorHandoff),
            ("authorization", self.authorization, ExecutionAuthorizationEvidence),
            ("checkpoint", self.checkpoint, ExecutionCheckpoint),
            ("resume_plan", self.resume_plan, ResumePlan),
            ("candidate_packet", self.candidate_packet, CandidatePacket),
            ("runtime_configuration", self.runtime_configuration, ConcreteRuntimeConfiguration),
            ("dependency_readiness", self.dependency_readiness, DependencyReadinessEvidence),
        )
        for name, value, expected_type in exact:
            if type(value) is not expected_type:
                raise TypeError(f"{name} must be exact {expected_type.__name__}")
        if not isinstance(self.pilot_input, SingleIssuePilotInput):
            raise TypeError("pilot_input must be SingleIssuePilotInput")


@runtime_checkable
class InvocationDescriptorLoader(Protocol):
    def __call__(self, handoff_id: str) -> GovernedInvocationDescriptor: ...


@runtime_checkable
class CurrentInvocationResolver(Protocol):
    def reacquire(
        self, descriptor: GovernedInvocationDescriptor
    ) -> CurrentInvocationEvidence: ...


@runtime_checkable
class LeaseObservationReader(Protocol):
    def inspect(self, request: PilotLeaseRequest) -> HostLocalLeaseObservation: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class InvocationReconstructionResult:
    schema_name: Literal["agent-os-governed-invocation-reconstruction"]
    schema_version: Literal["1.0"]
    result_id: str
    status: InvocationReconstructionStatus
    reason_codes: tuple[InvocationReconstructionReason, ...]
    handoff_id: str
    descriptor_id: str | None
    repository: str | None
    issue_number: int | None
    execution_id: str | None
    invocation_id: str | None
    lease_identity: str | None
    pilot_input: SingleIssuePilotInput | None
    repository_implementation_authorized: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)
    scheduler_invoked: Literal[False] = field(default=False, init=False)
    retry_attempted: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != INVOCATION_RECONSTRUCTION_SCHEMA_NAME:
            raise ValueError("unsupported invocation reconstruction schema name")
        if self.schema_version != INVOCATION_RECONSTRUCTION_SCHEMA_VERSION:
            raise ValueError("unsupported invocation reconstruction schema version")
        if type(self.status) is not InvocationReconstructionStatus:
            raise TypeError("status must be exact InvocationReconstructionStatus")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty exact tuple")
        if any(type(item) is not InvocationReconstructionReason for item in self.reason_codes):
            raise TypeError("reason_codes must contain exact InvocationReconstructionReason values")
        canonical = tuple(sorted(set(self.reason_codes), key=lambda item: item.value))
        if self.reason_codes != canonical:
            raise ValueError("reason_codes must be sorted and unique")
        if self.status is InvocationReconstructionStatus.ADMITTED:
            if self.reason_codes != (InvocationReconstructionReason.ADMITTED,):
                raise ValueError("admitted result must carry only admitted reason")
            if not isinstance(self.pilot_input, SingleIssuePilotInput):
                raise ValueError("admitted result requires exact current pilot input")
        elif self.pilot_input is not None:
            raise ValueError("non-admitted result must not expose pilot input")
        expected = _result_id(
            status=self.status,
            reasons=self.reason_codes,
            handoff_id=self.handoff_id,
            descriptor_id=self.descriptor_id,
            repository=self.repository,
            issue_number=self.issue_number,
            execution_id=self.execution_id,
            invocation_id=self.invocation_id,
            lease_identity=self.lease_identity,
        )
        if self.result_id != expected:
            raise ValueError("result_id does not match reconstruction result")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _result_id(
    *,
    status: InvocationReconstructionStatus,
    reasons: tuple[InvocationReconstructionReason, ...],
    handoff_id: str,
    descriptor_id: str | None,
    repository: str | None,
    issue_number: int | None,
    execution_id: str | None,
    invocation_id: str | None,
    lease_identity: str | None,
) -> str:
    payload = {
        "schema_name": INVOCATION_RECONSTRUCTION_SCHEMA_NAME,
        "schema_version": INVOCATION_RECONSTRUCTION_SCHEMA_VERSION,
        "status": status.value,
        "reason_codes": [item.value for item in reasons],
        "handoff_id": handoff_id,
        "descriptor_id": descriptor_id,
        "repository": repository,
        "issue_number": issue_number,
        "execution_id": execution_id,
        "invocation_id": invocation_id,
        "lease_identity": lease_identity,
    }
    digest = hashlib.sha256(
        b"agent-os-governed-invocation-reconstruction:v1\0" + _canonical_bytes(payload)
    ).hexdigest()
    return f"invocation-reconstruction:{digest}"


def _result(
    *,
    status: InvocationReconstructionStatus,
    reasons: tuple[InvocationReconstructionReason, ...],
    handoff_id: str,
    descriptor: GovernedInvocationDescriptor | None = None,
    lease_identity: str | None = None,
    pilot_input: SingleIssuePilotInput | None = None,
) -> InvocationReconstructionResult:
    canonical_reasons = tuple(sorted(set(reasons), key=lambda item: item.value))
    descriptor_id = None if descriptor is None else descriptor.descriptor_id
    repository = None if descriptor is None else descriptor.repository
    issue_number = None if descriptor is None else descriptor.issue_number
    execution_id = None if descriptor is None else descriptor.execution_id
    invocation_id = None if descriptor is None else descriptor.invocation_id
    return InvocationReconstructionResult(
        schema_name=INVOCATION_RECONSTRUCTION_SCHEMA_NAME,
        schema_version=INVOCATION_RECONSTRUCTION_SCHEMA_VERSION,
        result_id=_result_id(
            status=status,
            reasons=canonical_reasons,
            handoff_id=handoff_id,
            descriptor_id=descriptor_id,
            repository=repository,
            issue_number=issue_number,
            execution_id=execution_id,
            invocation_id=invocation_id,
            lease_identity=lease_identity,
        ),
        status=status,
        reason_codes=canonical_reasons,
        handoff_id=handoff_id,
        descriptor_id=descriptor_id,
        repository=repository,
        issue_number=issue_number,
        execution_id=execution_id,
        invocation_id=invocation_id,
        lease_identity=lease_identity,
        pilot_input=pilot_input,
    )


def _utc(value: str) -> datetime:
    if type(value) is not str or len(value) != 20 or not value.endswith("Z"):
        raise ValueError("timestamp must use canonical UTC seconds")
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError("timestamp is not canonical")
    return parsed


def _current_window(evaluated_at: str, starts_at: str, expires_at: str) -> bool:
    evaluated = _utc(evaluated_at)
    start = _utc(starts_at)
    expires = _utc(expires_at)
    return start <= evaluated < expires


def _lease_request(pilot_input: SingleIssuePilotInput) -> PilotLeaseRequest:
    if len(pilot_input.issue_numbers) != 1:
        raise ValueError("pilot input must carry exactly one issue")
    return PilotLeaseRequest(
        repository=pilot_input.repository,
        issue_number=pilot_input.issue_numbers[0],
        invocation_id=pilot_input.invocation_id,
        branch=pilot_input.branch,
        workspace_request_id=pilot_input.workspace_request_id,
        projection_id=pilot_input.expected_projection_id,
        approval_id=pilot_input.expected_approval_id,
        source_head_sha=pilot_input.source_head_sha,
    )


def _classify_reasons(
    reasons: set[InvocationReconstructionReason],
) -> InvocationReconstructionStatus:
    needs_decision = {
        InvocationReconstructionReason.CURRENT_EVIDENCE_UNAVAILABLE,
        InvocationReconstructionReason.CURRENT_EVIDENCE_MALFORMED,
        InvocationReconstructionReason.LEASE_OBSERVATION_UNAVAILABLE,
        InvocationReconstructionReason.LEASE_AMBIGUOUS,
    }
    stale = {
        InvocationReconstructionReason.ROUTE_DECISION_MISMATCH,
        InvocationReconstructionReason.HANDOFF_MISMATCH,
        InvocationReconstructionReason.AUTHORIZATION_NOT_CURRENT,
        InvocationReconstructionReason.SOURCE_MISMATCH,
        InvocationReconstructionReason.SCOPE_MISMATCH,
        InvocationReconstructionReason.CHECKPOINT_MISMATCH,
        InvocationReconstructionReason.CHECKPOINT_NOT_CURRENT,
        InvocationReconstructionReason.RESUME_PLAN_MISMATCH,
        InvocationReconstructionReason.ENVIRONMENT_MISMATCH,
        InvocationReconstructionReason.DEPENDENCY_READINESS_MISMATCH,
        InvocationReconstructionReason.CANDIDATE_PACKET_MISMATCH,
        InvocationReconstructionReason.RUNTIME_CONFIGURATION_MISMATCH,
        InvocationReconstructionReason.PILOT_INPUT_MISMATCH,
    }
    if reasons & needs_decision:
        return InvocationReconstructionStatus.NEEDS_DECISION
    if reasons & stale:
        return InvocationReconstructionStatus.STALE
    return InvocationReconstructionStatus.BLOCKED


def _cross_check(
    descriptor: GovernedInvocationDescriptor,
    current: CurrentInvocationEvidence,
    *,
    evaluated_at: str,
) -> set[InvocationReconstructionReason]:
    reasons: set[InvocationReconstructionReason] = set()
    route = current.route_decision
    handoff = current.handoff
    authorization = current.authorization
    checkpoint = current.checkpoint
    resume_plan = current.resume_plan
    packet = current.candidate_packet
    configuration = current.runtime_configuration
    readiness = current.dependency_readiness
    pilot = current.pilot_input

    if route.decision_id != descriptor.route_decision_id or handoff.route_decision_id != route.decision_id:
        reasons.add(InvocationReconstructionReason.ROUTE_DECISION_MISMATCH)
    if handoff.handoff_id != descriptor.handoff_id:
        reasons.add(InvocationReconstructionReason.HANDOFF_MISMATCH)
    if (
        route.selected_route is not ExecutorRoute.CHATGPT_GOVERNED_RUNNER
        or handoff.destination_route is not ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    ):
        reasons.add(InvocationReconstructionReason.ROUTE_NOT_GOVERNED_RUNNER)
    if not route.execution_authorized or not handoff.execution_authorized:
        reasons.add(InvocationReconstructionReason.EXECUTION_NOT_AUTHORIZED)

    request_fingerprint = descriptor.execution_service_request_fingerprint
    if (
        route.execution_service_request_fingerprint_or_none != request_fingerprint
        or handoff.execution_service_request_fingerprint_or_none != request_fingerprint
        or authorization.request_fingerprint != request_fingerprint
    ):
        reasons.add(InvocationReconstructionReason.SCOPE_MISMATCH)
    if (
        route.authorization_id_or_none != descriptor.authorization_id
        or handoff.authorization_id_or_none != descriptor.authorization_id
        or authorization.authorization_id != descriptor.authorization_id
        or authorization.repository.casefold() != descriptor.repository.casefold()
        or authorization.expected_sha != descriptor.source_sha
        or not authorization.execution_authorized
    ):
        reasons.add(InvocationReconstructionReason.AUTHORIZATION_MISMATCH)
    try:
        if not _current_window(evaluated_at, route.created_at, route.expires_at):
            reasons.add(InvocationReconstructionReason.AUTHORIZATION_NOT_CURRENT)
        if not _current_window(evaluated_at, authorization.authorized_at, authorization.expires_at):
            reasons.add(InvocationReconstructionReason.AUTHORIZATION_NOT_CURRENT)
    except (TypeError, ValueError):
        reasons.add(InvocationReconstructionReason.CURRENT_EVIDENCE_MALFORMED)

    if (
        handoff.repository.casefold() != descriptor.repository.casefold()
        or handoff.source_ref_or_none != descriptor.source_ref
        or handoff.source_sha_or_none != descriptor.source_sha
    ):
        reasons.add(InvocationReconstructionReason.SOURCE_MISMATCH)

    if (
        route.checkpoint_id_or_none != descriptor.checkpoint_id
        or handoff.checkpoint_id_or_none != descriptor.checkpoint_id
        or checkpoint.checkpoint_id != descriptor.checkpoint_id
        or checkpoint.repository.casefold() != descriptor.repository.casefold()
        or checkpoint.issue_number != descriptor.issue_number
        or checkpoint.execution_id != descriptor.execution_id
        or checkpoint.invocation_id != descriptor.invocation_id
        or checkpoint.source_sha != descriptor.source_sha
    ):
        reasons.add(InvocationReconstructionReason.CHECKPOINT_MISMATCH)
    if (
        checkpoint.invalidation_state is not InvalidationState.CURRENT
        or checkpoint.lifecycle_state not in {LifecycleState.ACTIVE, LifecycleState.INTERRUPTED}
    ):
        reasons.add(InvocationReconstructionReason.CHECKPOINT_NOT_CURRENT)

    if (
        route.resume_plan_id_or_none != descriptor.resume_plan_id
        or handoff.resume_plan_id_or_none != descriptor.resume_plan_id
        or resume_plan.plan_id != descriptor.resume_plan_id
        or resume_plan.repository.casefold() != descriptor.repository.casefold()
        or resume_plan.issue_number != descriptor.issue_number
        or resume_plan.execution_id != descriptor.execution_id
    ):
        reasons.add(InvocationReconstructionReason.RESUME_PLAN_MISMATCH)
    if resume_plan.resume_point is None:
        reasons.add(InvocationReconstructionReason.RESUME_PLAN_COMPLETE)

    if (
        route.environment_profile_id_or_none != descriptor.environment_profile_id
        or handoff.environment_profile_id_or_none != descriptor.environment_profile_id
        or route.environment_health_evidence_id_or_none
        != descriptor.environment_health_evidence_id
        or route.workflow_runtime_identity_or_none != descriptor.workflow_runtime_identity
    ):
        reasons.add(InvocationReconstructionReason.ENVIRONMENT_MISMATCH)

    required_environment = configuration.required_environment_spec
    if (
        required_environment is None
        or required_environment.required_environment_id != descriptor.required_environment_id
    ):
        reasons.add(InvocationReconstructionReason.ENVIRONMENT_MISMATCH)
    if (
        readiness.dependency_readiness_evidence_id
        != descriptor.dependency_readiness_evidence_id
        or readiness.required_environment_id != descriptor.required_environment_id
        or readiness.environment_health_evidence_id
        != descriptor.environment_health_evidence_id
        or readiness.source_sha != descriptor.source_sha
    ):
        reasons.add(InvocationReconstructionReason.DEPENDENCY_READINESS_MISMATCH)
    if readiness.preparation_status is not DependencyPreparationStatus.READY:
        reasons.add(InvocationReconstructionReason.DEPENDENCY_NOT_READY)
    try:
        if not _current_window(evaluated_at, readiness.observed_at, readiness.expires_at):
            reasons.add(InvocationReconstructionReason.DEPENDENCY_NOT_READY)
    except (TypeError, ValueError):
        reasons.add(InvocationReconstructionReason.CURRENT_EVIDENCE_MALFORMED)

    try:
        current_packet_id = candidate_packet_id(packet)
    except (TypeError, ValueError):
        reasons.add(InvocationReconstructionReason.CANDIDATE_PACKET_MISMATCH)
    else:
        if (
            current_packet_id != descriptor.candidate_packet_id
            or packet.packet_id != descriptor.candidate_packet_id
            or packet.repository.casefold() != descriptor.repository.casefold()
            or packet.issue_number != descriptor.issue_number
            or packet.invocation_id != descriptor.invocation_id
            or packet.candidate_sha != descriptor.source_sha
        ):
            reasons.add(InvocationReconstructionReason.CANDIDATE_PACKET_MISMATCH)
    if packet.phase is not CandidatePacketPhase.EXECUTION_CANDIDATE:
        reasons.add(InvocationReconstructionReason.CANDIDATE_PACKET_NOT_EXECUTABLE)

    if (
        configuration.configuration_fingerprint
        != descriptor.runtime_configuration_fingerprint
        or configuration.repository.casefold() != descriptor.repository.casefold()
        or configuration.issue_number != descriptor.issue_number
        or configuration.invocation_id != descriptor.invocation_id
        or configuration.source_head_sha != descriptor.source_sha
    ):
        reasons.add(InvocationReconstructionReason.RUNTIME_CONFIGURATION_MISMATCH)
    try:
        configuration.verify(pilot)
    except (TypeError, ValueError, ConcreteRuntimeConfigurationError):
        reasons.add(InvocationReconstructionReason.PILOT_INPUT_MISMATCH)

    if (
        pilot.repository.casefold() != descriptor.repository.casefold()
        or tuple(pilot.issue_numbers) != (descriptor.issue_number,)
        or pilot.invocation_id != descriptor.invocation_id
        or pilot.source_head_sha != descriptor.source_sha
        or tuple(pilot.allowed_files) != tuple(handoff.allowed_paths)
        or tuple(pilot.forbidden_paths) != tuple(handoff.forbidden_paths)
        or tuple(packet.allowed_files) != tuple(handoff.allowed_paths)
        or tuple(packet.forbidden_paths) != tuple(handoff.forbidden_paths)
        or tuple(packet.required_tests) != tuple(pilot.required_tests)
    ):
        reasons.add(InvocationReconstructionReason.PILOT_INPUT_MISMATCH)

    return reasons


def reconstruct_governed_invocation(
    handoff_id: str,
    *,
    descriptor_loader: InvocationDescriptorLoader,
    resolver: CurrentInvocationResolver,
    lease_reader: LeaseObservationReader,
    evaluated_at: str,
) -> InvocationReconstructionResult:
    """Resolve one immutable handoff id to one current canonical pilot input.

    Descriptor load, current-evidence reacquisition, and lease observation each
    occur at most once.  A blocked/stale/ambiguous path returns no pilot input,
    so callers cannot accidentally dispatch the Scheduler after failed
    admission.
    """
    if type(handoff_id) is not str or not handoff_id:
        raise TypeError("handoff_id must be non-empty exact text")
    if not callable(descriptor_loader):
        raise TypeError("descriptor_loader must be callable")
    if not isinstance(resolver, CurrentInvocationResolver):
        raise TypeError("resolver must satisfy CurrentInvocationResolver")
    if not isinstance(lease_reader, LeaseObservationReader):
        raise TypeError("lease_reader must satisfy LeaseObservationReader")
    _utc(evaluated_at)

    try:
        descriptor = descriptor_loader(handoff_id)
    except InvocationDescriptorNotFound:
        return _result(
            status=InvocationReconstructionStatus.BLOCKED,
            reasons=(InvocationReconstructionReason.DESCRIPTOR_MISSING,),
            handoff_id=handoff_id,
        )
    except (InvocationDescriptorIntegrityError, TypeError, ValueError):
        return _result(
            status=InvocationReconstructionStatus.NEEDS_DECISION,
            reasons=(InvocationReconstructionReason.DESCRIPTOR_INVALID,),
            handoff_id=handoff_id,
        )

    if type(descriptor) is not GovernedInvocationDescriptor or descriptor.handoff_id != handoff_id:
        return _result(
            status=InvocationReconstructionStatus.NEEDS_DECISION,
            reasons=(InvocationReconstructionReason.DESCRIPTOR_INVALID,),
            handoff_id=handoff_id,
        )

    try:
        current = resolver.reacquire(descriptor)
    except (TypeError, ValueError, RuntimeError, OSError):
        return _result(
            status=InvocationReconstructionStatus.NEEDS_DECISION,
            reasons=(InvocationReconstructionReason.CURRENT_EVIDENCE_UNAVAILABLE,),
            handoff_id=handoff_id,
            descriptor=descriptor,
        )
    if type(current) is not CurrentInvocationEvidence:
        return _result(
            status=InvocationReconstructionStatus.NEEDS_DECISION,
            reasons=(InvocationReconstructionReason.CURRENT_EVIDENCE_MALFORMED,),
            handoff_id=handoff_id,
            descriptor=descriptor,
        )

    reasons = _cross_check(descriptor, current, evaluated_at=evaluated_at)
    if reasons:
        return _result(
            status=_classify_reasons(reasons),
            reasons=tuple(reasons),
            handoff_id=handoff_id,
            descriptor=descriptor,
        )

    try:
        request = _lease_request(current.pilot_input)
        expected_lease_identity = pilot_lease_identity(request)
        observation = lease_reader.inspect(request)
    except (TypeError, ValueError, RuntimeError, OSError):
        return _result(
            status=InvocationReconstructionStatus.NEEDS_DECISION,
            reasons=(InvocationReconstructionReason.LEASE_OBSERVATION_UNAVAILABLE,),
            handoff_id=handoff_id,
            descriptor=descriptor,
        )
    if type(observation) is not HostLocalLeaseObservation:
        return _result(
            status=InvocationReconstructionStatus.NEEDS_DECISION,
            reasons=(InvocationReconstructionReason.LEASE_OBSERVATION_UNAVAILABLE,),
            handoff_id=handoff_id,
            descriptor=descriptor,
        )
    if observation.lease_identity != expected_lease_identity:
        return _result(
            status=InvocationReconstructionStatus.NEEDS_DECISION,
            reasons=(InvocationReconstructionReason.LEASE_IDENTITY_MISMATCH,),
            handoff_id=handoff_id,
            descriptor=descriptor,
            lease_identity=expected_lease_identity,
        )
    if observation.ambiguous:
        return _result(
            status=InvocationReconstructionStatus.NEEDS_DECISION,
            reasons=(InvocationReconstructionReason.LEASE_AMBIGUOUS,),
            handoff_id=handoff_id,
            descriptor=descriptor,
            lease_identity=expected_lease_identity,
        )
    if observation.active:
        return _result(
            status=InvocationReconstructionStatus.BLOCKED,
            reasons=(InvocationReconstructionReason.LEASE_CONFLICT,),
            handoff_id=handoff_id,
            descriptor=descriptor,
            lease_identity=expected_lease_identity,
        )
    if observation.generation > 0:
        return _result(
            status=InvocationReconstructionStatus.BLOCKED,
            reasons=(InvocationReconstructionReason.INVOCATION_ALREADY_CONSUMED,),
            handoff_id=handoff_id,
            descriptor=descriptor,
            lease_identity=expected_lease_identity,
        )

    return _result(
        status=InvocationReconstructionStatus.ADMITTED,
        reasons=(InvocationReconstructionReason.ADMITTED,),
        handoff_id=handoff_id,
        descriptor=descriptor,
        lease_identity=expected_lease_identity,
        pilot_input=current.pilot_input,
    )
