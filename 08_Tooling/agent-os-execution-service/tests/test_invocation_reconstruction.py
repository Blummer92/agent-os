from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_os_execution_service.invocation_reconstruction as reconstruction
from agent_os_execution_service.executor_routing import ExecutorRoute
from agent_os_execution_service.invocation_reconstruction import (
    CurrentInvocationEvidence,
    InvocationReconstructionReason,
    InvocationReconstructionStatus,
    reconstruct_governed_invocation,
)
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from scripts.agent_os_execution_capabilities.dependencies import DependencyPreparationStatus
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME,
    INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    GovernedInvocationDescriptor,
    InvocationDescriptorIntegrityError,
    InvocationDescriptorNotFound,
)
from scripts.agent_os_execution_checkpoint.models import InvalidationState, LifecycleState
from workflow_scheduler.execution.host_local_lease_adapter import HostLocalLeaseObservation
from workflow_scheduler.execution.single_issue_pilot import (
    PilotLeaseRequest,
    WorkspaceRequest,
    pilot_lease_identity,
    pilot_workspace_identity,
)

BRANCH = "agent/1218-governed-invocation-descriptor"
SOURCE_SHA = "a" * 40
WORKSPACE_REQUEST_ID = "workspace-1218-a"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _id(prefix: str, label: str) -> str:
    return f"{prefix}:{_digest(label)}"


def _workspace_id(workspace_request_id: str = WORKSPACE_REQUEST_ID) -> str:
    return pilot_workspace_identity(
        WorkspaceRequest(
            workspace_request_id=workspace_request_id,
            repository="Blummer92/agent-os",
            branch=BRANCH,
            expected_revision=SOURCE_SHA,
        )
    )


def _descriptor(**overrides: object) -> GovernedInvocationDescriptor:
    values: dict[str, object] = {
        "schema_name": INVOCATION_DESCRIPTOR_SCHEMA_NAME,
        "schema_version": INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        "repository": "Blummer92/agent-os",
        "issue_number": 1218,
        "issue_or_handoff_identity": "issue:1218",
        "handoff_id": _id("executor-handoff", "handoff"),
        "route_decision_id": _id("executor-route-decision", "route"),
        "execution_service_request_fingerprint": _id("execution-request", "request"),
        "authorization_id": _id("authorization", "authorization"),
        "source_ref": f"refs/heads/{BRANCH}",
        "source_sha": SOURCE_SHA,
        "checkpoint_id": _id("agent-os.execution-checkpoint", "checkpoint"),
        "resume_plan_id": _id("agent-os.execution-checkpoint.resume-plan", "resume"),
        "environment_profile_id": _id("environment-profile", "profile"),
        "environment_health_evidence_id": _id("environment-health", "health"),
        "required_environment_id": _id("required-environment", "required-environment"),
        "dependency_readiness_evidence_id": _id("dependency-readiness", "readiness"),
        "execution_surface_id": "execution-surface:gce-agent-os-test",
        "workspace_identity": _workspace_id(),
        "workflow_runtime_identity": _id("workflow-runtime", "runtime"),
        "candidate_packet_id": _id("candidate-packet", "packet"),
        "runtime_configuration_fingerprint": _id("concrete-adapters", "configuration"),
        "execution_id": "execution-1218-a",
        "invocation_id": "invocation-1218-a",
    }
    values.update(overrides)
    return GovernedInvocationDescriptor(**values)


def _current_like(descriptor: GovernedInvocationDescriptor) -> SimpleNamespace:
    command_plan_id = _id("command-plan", "plan")
    route = SimpleNamespace(
        decision_id=descriptor.route_decision_id,
        repository=descriptor.repository,
        issue_or_handoff_identity=descriptor.issue_or_handoff_identity,
        selected_route=ExecutorRoute.CHATGPT_GOVERNED_RUNNER,
        execution_authorized=True,
        execution_service_request_fingerprint_or_none=(
            descriptor.execution_service_request_fingerprint
        ),
        authorization_id_or_none=descriptor.authorization_id,
        validation_command_plan_id_or_none=command_plan_id,
        checkpoint_id_or_none=descriptor.checkpoint_id,
        resume_plan_id_or_none=descriptor.resume_plan_id,
        environment_profile_id_or_none=descriptor.environment_profile_id,
        environment_health_evidence_id_or_none=(
            descriptor.environment_health_evidence_id
        ),
        workflow_runtime_identity_or_none=descriptor.workflow_runtime_identity,
        created_at="2026-08-17T10:00:00Z",
        expires_at="2026-08-17T12:00:00Z",
    )
    handoff = SimpleNamespace(
        route_decision_id=descriptor.route_decision_id,
        handoff_id=descriptor.handoff_id,
        issue_or_handoff_identity=descriptor.issue_or_handoff_identity,
        destination_route=ExecutorRoute.CHATGPT_GOVERNED_RUNNER,
        execution_authorized=True,
        execution_service_request_fingerprint_or_none=(
            descriptor.execution_service_request_fingerprint
        ),
        authorization_id_or_none=descriptor.authorization_id,
        repository=descriptor.repository,
        source_ref_or_none=descriptor.source_ref,
        source_sha_or_none=descriptor.source_sha,
        checkpoint_id_or_none=descriptor.checkpoint_id,
        resume_plan_id_or_none=descriptor.resume_plan_id,
        environment_profile_id_or_none=descriptor.environment_profile_id,
        validation_command_plan_id_or_none=command_plan_id,
        allowed_paths=("scripts/agent_os_execution_checkpoint",),
        forbidden_paths=(".github/workflows",),
    )
    authorization = SimpleNamespace(
        request_fingerprint=descriptor.execution_service_request_fingerprint,
        authorization_id=descriptor.authorization_id,
        repository=descriptor.repository,
        expected_sha=descriptor.source_sha,
        execution_authorized=True,
        authorized_at="2026-08-17T10:00:00Z",
        expires_at="2026-08-17T12:00:00Z",
    )
    checkpoint = SimpleNamespace(
        checkpoint_id=descriptor.checkpoint_id,
        repository=descriptor.repository,
        issue_number=descriptor.issue_number,
        execution_id=descriptor.execution_id,
        invocation_id=descriptor.invocation_id,
        source_sha=descriptor.source_sha,
        command_plan_id=command_plan_id,
        invalidation_state=InvalidationState.CURRENT,
        lifecycle_state=LifecycleState.INTERRUPTED,
    )
    resume_plan = SimpleNamespace(
        plan_id=descriptor.resume_plan_id,
        repository=descriptor.repository,
        issue_number=descriptor.issue_number,
        execution_id=descriptor.execution_id,
        resume_point=object(),
    )
    packet = SimpleNamespace(
        packet_id=descriptor.candidate_packet_id,
        repository=descriptor.repository,
        issue_number=descriptor.issue_number,
        invocation_id=descriptor.invocation_id,
        candidate_sha=descriptor.source_sha,
        phase=CandidatePacketPhase.EXECUTION_CANDIDATE,
        allowed_files=handoff.allowed_paths,
        forbidden_paths=handoff.forbidden_paths,
        required_tests=("focused",),
    )
    required_environment = SimpleNamespace(
        required_environment_id=descriptor.required_environment_id
    )

    class _Configuration(SimpleNamespace):
        def verify(self, _pilot) -> None:
            return None

    configuration = _Configuration(
        required_environment_spec=required_environment,
        configuration_fingerprint=descriptor.runtime_configuration_fingerprint,
        repository=descriptor.repository,
        issue_number=descriptor.issue_number,
        invocation_id=descriptor.invocation_id,
        source_head_sha=descriptor.source_sha,
    )
    readiness = SimpleNamespace(
        dependency_readiness_evidence_id=descriptor.dependency_readiness_evidence_id,
        required_environment_id=descriptor.required_environment_id,
        environment_health_evidence_id=descriptor.environment_health_evidence_id,
        execution_surface_id=descriptor.execution_surface_id,
        workspace_identity=descriptor.workspace_identity,
        source_sha=descriptor.source_sha,
        preparation_status=DependencyPreparationStatus.READY,
        observed_at="2026-08-17T10:00:00Z",
        expires_at="2026-08-17T12:00:00Z",
    )
    pilot = SimpleNamespace(
        repository=descriptor.repository,
        issue_numbers=(descriptor.issue_number,),
        invocation_id=descriptor.invocation_id,
        source_head_sha=descriptor.source_sha,
        branch=BRANCH,
        workspace_request_id=WORKSPACE_REQUEST_ID,
        allowed_files=handoff.allowed_paths,
        forbidden_paths=handoff.forbidden_paths,
        required_tests=("focused",),
    )
    return SimpleNamespace(
        route_decision=route,
        handoff=handoff,
        authorization=authorization,
        checkpoint=checkpoint,
        resume_plan=resume_plan,
        candidate_packet=packet,
        runtime_configuration=configuration,
        dependency_readiness=readiness,
        pilot_input=pilot,
    )


def _set(current: SimpleNamespace, path: str, value: object) -> None:
    parent, name = path.split(".", 1)
    setattr(getattr(current, parent), name, value)


def test_cross_check_accepts_fully_matching_reacquired_bindings(monkeypatch) -> None:
    descriptor = _descriptor()
    current = _current_like(descriptor)
    monkeypatch.setattr(
        reconstruction, "candidate_packet_id", lambda packet: packet.packet_id
    )
    assert reconstruction._cross_check(
        descriptor,
        current,
        evaluated_at="2026-08-17T11:00:00Z",
    ) == set()


@pytest.mark.parametrize(
    "path,value,reason",
    [
        ("handoff.handoff_id", _id("executor-handoff", "stale"), InvocationReconstructionReason.HANDOFF_MISMATCH),
        ("handoff.issue_or_handoff_identity", "issue:999", InvocationReconstructionReason.SUBJECT_MISMATCH),
        ("route_decision.decision_id", _id("executor-route-decision", "stale"), InvocationReconstructionReason.ROUTE_DECISION_MISMATCH),
        ("authorization.expires_at", "2026-08-17T10:30:00Z", InvocationReconstructionReason.AUTHORIZATION_NOT_CURRENT),
        ("authorization.execution_authorized", False, InvocationReconstructionReason.AUTHORIZATION_MISMATCH),
        ("handoff.source_sha_or_none", "b" * 40, InvocationReconstructionReason.SOURCE_MISMATCH),
        ("handoff.execution_service_request_fingerprint_or_none", _id("execution-request", "other"), InvocationReconstructionReason.SCOPE_MISMATCH),
        ("handoff.validation_command_plan_id_or_none", _id("command-plan", "other"), InvocationReconstructionReason.COMMAND_PLAN_MISMATCH),
        ("checkpoint.checkpoint_id", _id("agent-os.execution-checkpoint", "other"), InvocationReconstructionReason.CHECKPOINT_MISMATCH),
        ("checkpoint.invalidation_state", InvalidationState.SUPERSEDED, InvocationReconstructionReason.CHECKPOINT_NOT_CURRENT),
        ("resume_plan.plan_id", _id("agent-os.execution-checkpoint.resume-plan", "other"), InvocationReconstructionReason.RESUME_PLAN_MISMATCH),
        ("resume_plan.resume_point", None, InvocationReconstructionReason.RESUME_PLAN_COMPLETE),
        ("route_decision.environment_profile_id_or_none", _id("environment-profile", "other"), InvocationReconstructionReason.ENVIRONMENT_MISMATCH),
        ("dependency_readiness.required_environment_id", _id("required-environment", "other"), InvocationReconstructionReason.DEPENDENCY_READINESS_MISMATCH),
        ("dependency_readiness.execution_surface_id", "execution-surface:other-host", InvocationReconstructionReason.EXECUTION_SURFACE_MISMATCH),
        ("dependency_readiness.workspace_identity", _id("pilot-workspace", "other"), InvocationReconstructionReason.WORKSPACE_MISMATCH),
        ("pilot_input.workspace_request_id", "workspace-other", InvocationReconstructionReason.WORKSPACE_MISMATCH),
        ("dependency_readiness.preparation_status", DependencyPreparationStatus.BLOCKED, InvocationReconstructionReason.DEPENDENCY_NOT_READY),
        ("candidate_packet.packet_id", _id("candidate-packet", "other"), InvocationReconstructionReason.CANDIDATE_PACKET_MISMATCH),
        ("runtime_configuration.configuration_fingerprint", _id("concrete-adapters", "other"), InvocationReconstructionReason.RUNTIME_CONFIGURATION_MISMATCH),
        ("pilot_input.allowed_files", ("outside",), InvocationReconstructionReason.PILOT_INPUT_MISMATCH),
    ],
)
def test_cross_check_fails_closed_on_stale_or_mismatched_current_evidence(
    monkeypatch,
    path,
    value,
    reason,
) -> None:
    descriptor = _descriptor()
    current = _current_like(descriptor)
    monkeypatch.setattr(
        reconstruction, "candidate_packet_id", lambda packet: packet.packet_id
    )
    _set(current, path, value)
    reasons = reconstruction._cross_check(
        descriptor,
        current,
        evaluated_at="2026-08-17T11:00:00Z",
    )
    assert reason in reasons


class _Loader:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self, _handoff_id: str):
        self.calls += 1
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


class _Resolver:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def reacquire(self, _descriptor):
        self.calls += 1
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


class _LeaseReader:
    def __init__(self, observation):
        self.observation = observation
        self.calls = 0

    def inspect(self, _request):
        self.calls += 1
        return self.observation


def _bypassed_current(pilot_input: object) -> CurrentInvocationEvidence:
    current = object.__new__(CurrentInvocationEvidence)
    object.__setattr__(current, "pilot_input", pilot_input)
    return current


def _lease_request() -> PilotLeaseRequest:
    return PilotLeaseRequest(
        repository="Blummer92/agent-os",
        issue_number=1218,
        invocation_id="invocation-1218-a",
        branch=BRANCH,
        workspace_request_id=WORKSPACE_REQUEST_ID,
        projection_id="projection-1218-a",
        approval_id="approval-1218-a",
        source_head_sha=SOURCE_SHA,
    )


def _run_lease_case(
    monkeypatch,
    *,
    active: bool,
    ambiguous: bool,
    generation: int,
):
    descriptor = _descriptor()

    class _Pilot:
        pass

    current = _bypassed_current(_Pilot())
    request = _lease_request()
    expected = pilot_lease_identity(request)
    loader = _Loader(descriptor)
    resolver = _Resolver(current)
    lease = _LeaseReader(
        HostLocalLeaseObservation(
            lease_identity=expected,
            active=active,
            ambiguous=ambiguous,
            generation=generation,
            holder_identity="pilot-holder:test" if active else None,
        )
    )
    monkeypatch.setattr(reconstruction, "SingleIssuePilotInput", _Pilot)
    monkeypatch.setattr(
        reconstruction,
        "_cross_check",
        lambda *_args, **_kwargs: set(),
    )
    monkeypatch.setattr(reconstruction, "_lease_request", lambda _pilot: request)
    result = reconstruct_governed_invocation(
        descriptor.handoff_id,
        descriptor_loader=loader,
        resolver=resolver,
        lease_reader=lease,
        evaluated_at="2026-08-17T11:00:00Z",
    )
    assert loader.calls == 1
    assert resolver.calls == 1
    assert lease.calls == 1
    return result


@pytest.mark.parametrize("generation", [0, 1, 9])
def test_inactive_exact_lease_is_admitted_for_canonical_reacquisition(
    monkeypatch,
    generation,
) -> None:
    result = _run_lease_case(
        monkeypatch,
        active=False,
        ambiguous=False,
        generation=generation,
    )
    assert result.status is InvocationReconstructionStatus.ADMITTED
    assert result.reason_codes == (InvocationReconstructionReason.ADMITTED,)
    assert result.pilot_input is not None
    assert result.scheduler_invoked is False
    assert result.retry_attempted is False
    assert result.execution_authorized is False
    assert result.github_writes_authorized is False
    assert result.merge_authorized is False
    assert result.external_writes_authorized is False


def test_active_lease_blocks_without_second_execution(monkeypatch) -> None:
    result = _run_lease_case(
        monkeypatch,
        active=True,
        ambiguous=False,
        generation=1,
    )
    assert result.status is InvocationReconstructionStatus.BLOCKED
    assert result.reason_codes == (InvocationReconstructionReason.LEASE_CONFLICT,)
    assert result.pilot_input is None


def test_ambiguous_retained_lease_needs_decision_without_takeover(monkeypatch) -> None:
    result = _run_lease_case(
        monkeypatch,
        active=True,
        ambiguous=True,
        generation=1,
    )
    assert result.status is InvocationReconstructionStatus.NEEDS_DECISION
    assert result.reason_codes == (InvocationReconstructionReason.LEASE_AMBIGUOUS,)
    assert result.pilot_input is None


def test_missing_invalid_and_unavailable_evidence_fail_before_lease() -> None:
    descriptor = _descriptor()
    lease = _LeaseReader(None)

    cases = (
        (
            InvocationDescriptorNotFound("missing"),
            InvocationReconstructionStatus.BLOCKED,
            InvocationReconstructionReason.DESCRIPTOR_MISSING,
        ),
        (
            InvocationDescriptorIntegrityError("tampered"),
            InvocationReconstructionStatus.NEEDS_DECISION,
            InvocationReconstructionReason.DESCRIPTOR_INVALID,
        ),
        (
            RuntimeError("store unavailable"),
            InvocationReconstructionStatus.NEEDS_DECISION,
            InvocationReconstructionReason.DESCRIPTOR_UNAVAILABLE,
        ),
    )
    for error, status, reason in cases:
        result = reconstruct_governed_invocation(
            descriptor.handoff_id,
            descriptor_loader=_Loader(error),
            resolver=_Resolver(RuntimeError("must not run")),
            lease_reader=lease,
            evaluated_at="2026-08-17T11:00:00Z",
        )
        assert result.status is status
        assert result.reason_codes == (reason,)
    assert lease.calls == 0

    unavailable = reconstruct_governed_invocation(
        descriptor.handoff_id,
        descriptor_loader=_Loader(descriptor),
        resolver=_Resolver(RuntimeError("canonical read failed")),
        lease_reader=lease,
        evaluated_at="2026-08-17T11:00:00Z",
    )
    assert unavailable.status is InvocationReconstructionStatus.NEEDS_DECISION
    assert unavailable.reason_codes == (
        InvocationReconstructionReason.CURRENT_EVIDENCE_UNAVAILABLE,
    )
    assert lease.calls == 0


def test_module_has_no_external_or_execution_side_effect_surface() -> None:
    path = Path(reconstruction.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = (
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "github",
        "google.cloud",
        "boto",
    )
    for module_name in imported:
        assert not any(token in module_name.lower() for token in forbidden)

    source = path.read_text(encoding="utf-8")
    for forbidden_call in (
        "run_single_issue_pilot(",
        "run_single_issue_runtime_entrypoint(",
        ".acquire(",
        ".release(",
        "subprocess.",
        "os.system(",
    ):
        assert forbidden_call not in source
