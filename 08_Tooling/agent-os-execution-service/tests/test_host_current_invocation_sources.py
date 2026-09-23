from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_os_execution_service.host_current_invocation_sources as host_sources_module
from agent_os_execution_service.current_invocation_resolver import (
    CurrentInvocationResolutionError,
    InvocationEvidenceSources,
)
from agent_os_execution_service.host_current_invocation_sources import (
    HostCurrentInvocationSources,
)
from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyCacheState,
    DependencyEcosystem,
    DependencyInstallMode,
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    ReproducibilityLevel,
)
from scripts.agent_os_execution_checkpoint.dependency_readiness_store import (
    append_dependency_readiness,
)
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME,
    INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    GovernedInvocationDescriptor,
)


def _id(prefix: str, label: str) -> str:
    return f"{prefix}:{hashlib.sha256(label.encode('utf-8')).hexdigest()}"


def _evidence() -> DependencyReadinessEvidence:
    return DependencyReadinessEvidence(
        execution_surface_id="execution-surface:gce-agent-os-test",
        workspace_identity=_id("pilot-workspace", "workspace"),
        source_sha="a" * 40,
        required_environment_id=_id("required-environment", "environment"),
        package_root=".",
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        runtime_version="3.12.1",
        package_manager_version="24.0",
        declared_dependency_identity=_id("manifest", "manifest"),
        lock_or_constraints_identity=_id("lock", "lock"),
        install_mode=DependencyInstallMode.NORMAL,
        source_or_registry_identity="pypi.org",
        cache_state=DependencyCacheState.CURRENT_COMPLETE,
        preparation_status=DependencyPreparationStatus.READY,
        resolved_dependency_identity=_id("pip-freeze", "resolved"),
        environment_health_evidence_id=_id("environment-health", "health"),
        observed_at="2026-08-18T20:00:00Z",
        expires_at="2026-08-18T22:00:00Z",
        reproducibility_level=ReproducibilityLevel.LOCKED,
    )


def _descriptor(
    evidence: DependencyReadinessEvidence, **overrides: object
) -> GovernedInvocationDescriptor:
    values: dict[str, object] = {
        "schema_name": INVOCATION_DESCRIPTOR_SCHEMA_NAME,
        "schema_version": INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        "repository": "Blummer92/agent-os",
        "issue_number": 1253,
        "issue_or_handoff_identity": "issue:1253",
        "handoff_id": _id("executor-handoff", "handoff"),
        "route_decision_id": _id("executor-route-decision", "route"),
        "execution_service_request_fingerprint": _id("execution-request", "request"),
        "authorization_id": _id("authorization", "authorization"),
        "source_ref": "refs/heads/agent/1253-host-current-invocation",
        "source_sha": evidence.source_sha,
        "checkpoint_id": _id("agent-os.execution-checkpoint", "checkpoint"),
        "resume_plan_id": _id("agent-os.execution-checkpoint.resume-plan", "resume"),
        "environment_profile_id": _id("environment-profile", "profile"),
        "environment_health_evidence_id": evidence.environment_health_evidence_id,
        "required_environment_id": evidence.required_environment_id,
        "dependency_readiness_evidence_id": evidence.dependency_readiness_evidence_id,
        "execution_surface_id": evidence.execution_surface_id,
        "workspace_identity": evidence.workspace_identity,
        "workflow_runtime_identity": _id("workflow-runtime", "runtime"),
        "candidate_packet_id": _id("candidate-packet", "packet"),
        "runtime_configuration_fingerprint": _id("concrete-adapters", "configuration"),
        "execution_id": "execution-1253-a",
        "invocation_id": "invocation-1253-a",
    }
    values.update(overrides)
    return GovernedInvocationDescriptor(**values)


def _sources(tmp_path, calls: list[str] | None = None) -> HostCurrentInvocationSources:
    calls = [] if calls is None else calls

    def route(descriptor):
        calls.append("route")
        return SimpleNamespace(
            decision_id=descriptor.route_decision_id,
            repository=descriptor.repository,
            issue_or_handoff_identity=descriptor.issue_or_handoff_identity,
        )

    def handoff(descriptor, _route):
        calls.append("handoff")
        return SimpleNamespace(
            handoff_id=descriptor.handoff_id,
            route_decision_id=descriptor.route_decision_id,
            repository=descriptor.repository,
            issue_or_handoff_identity=descriptor.issue_or_handoff_identity,
            source_ref_or_none=descriptor.source_ref,
            source_sha_or_none=descriptor.source_sha,
        )

    def checkpoint(descriptor):
        calls.append("checkpoint")
        return SimpleNamespace(
            checkpoint_id=descriptor.checkpoint_id,
            repository=descriptor.repository,
            issue_number=descriptor.issue_number,
            execution_id=descriptor.execution_id,
            invocation_id=descriptor.invocation_id,
            source_sha=descriptor.source_sha,
        )

    def resume(descriptor, _checkpoint):
        calls.append("resume")
        return SimpleNamespace(
            plan_id=descriptor.resume_plan_id,
            repository=descriptor.repository,
            issue_number=descriptor.issue_number,
            execution_id=descriptor.execution_id,
        )

    def packet(descriptor):
        calls.append("packet")
        return SimpleNamespace(
            packet_id=descriptor.candidate_packet_id,
            repository=descriptor.repository,
            issue_number=descriptor.issue_number,
            invocation_id=descriptor.invocation_id,
            candidate_sha=descriptor.source_sha,
        )

    def runtime(descriptor, _packet):
        calls.append("runtime")
        return SimpleNamespace(
            configuration_fingerprint=descriptor.runtime_configuration_fingerprint,
            repository=descriptor.repository,
            issue_number=descriptor.issue_number,
            invocation_id=descriptor.invocation_id,
            source_head_sha=descriptor.source_sha,
        )

    def pilot(**values):
        calls.append("pilot")
        descriptor = values["descriptor"]
        return SimpleNamespace(
            repository=descriptor.repository,
            issue_numbers=(descriptor.issue_number,),
            invocation_id=descriptor.invocation_id,
            source_head_sha=descriptor.source_sha,
        )

    return HostCurrentInvocationSources(
        checkpoint_store_root=tmp_path,
        route_decision_reader=route,
        handoff_reader=handoff,
        checkpoint_reader=checkpoint,
        resume_plan_reader=resume,
        candidate_packet_rebuilder=packet,
        runtime_configuration_builder=runtime,
        pilot_input_builder=pilot,
    )


def test_host_sources_satisfy_existing_protocol(tmp_path) -> None:
    assert isinstance(_sources(tmp_path), InvocationEvidenceSources)


def test_host_sources_reacquire_each_owner_and_load_exact_readiness(tmp_path) -> None:
    evidence = _evidence()
    append_dependency_readiness(tmp_path, evidence)
    descriptor = _descriptor(evidence)
    calls: list[str] = []
    sources = _sources(tmp_path, calls)

    route = sources.route_decision(descriptor)
    handoff = sources.handoff(descriptor, route)
    checkpoint = sources.checkpoint(descriptor)
    resume = sources.resume_plan(descriptor, checkpoint)
    packet = sources.candidate_packet(descriptor)
    runtime = sources.runtime_configuration(descriptor, packet)
    readiness = sources.dependency_readiness(descriptor)
    pilot = sources.pilot_input(
        descriptor,
        route_decision=route,
        handoff=handoff,
        authorization=object(),
        checkpoint=checkpoint,
        resume_plan=resume,
        candidate_packet=packet,
        runtime_configuration=runtime,
        dependency_readiness=readiness,
    )

    assert calls == ["route", "handoff", "checkpoint", "resume", "packet", "runtime", "pilot"]
    assert readiness == evidence
    assert pilot.source_head_sha == descriptor.source_sha


def test_dependency_readiness_same_sha_wrong_workspace_fails_closed(tmp_path) -> None:
    evidence = _evidence()
    append_dependency_readiness(tmp_path, evidence)
    descriptor = _descriptor(evidence, workspace_identity=_id("pilot-workspace", "other"))

    with pytest.raises(CurrentInvocationResolutionError, match="workspace_identity"):
        _sources(tmp_path).dependency_readiness(descriptor)


def test_dependency_readiness_wrong_surface_fails_closed(tmp_path) -> None:
    evidence = _evidence()
    append_dependency_readiness(tmp_path, evidence)
    descriptor = _descriptor(evidence, execution_surface_id="execution-surface:other")

    with pytest.raises(CurrentInvocationResolutionError, match="execution_surface_id"):
        _sources(tmp_path).dependency_readiness(descriptor)


def test_owner_binding_mismatch_fails_before_cross_check(tmp_path) -> None:
    evidence = _evidence()
    descriptor = _descriptor(evidence)
    baseline = _sources(tmp_path)
    sources = HostCurrentInvocationSources(
        checkpoint_store_root=tmp_path,
        route_decision_reader=lambda _descriptor: SimpleNamespace(
            decision_id=_id("executor-route-decision", "stale"),
            repository="Blummer92/agent-os",
            issue_or_handoff_identity="issue:1253",
        ),
        handoff_reader=baseline.handoff_reader,
        checkpoint_reader=baseline.checkpoint_reader,
        resume_plan_reader=baseline.resume_plan_reader,
        candidate_packet_rebuilder=baseline.candidate_packet_rebuilder,
        runtime_configuration_builder=baseline.runtime_configuration_builder,
        pilot_input_builder=baseline.pilot_input_builder,
    )

    with pytest.raises(CurrentInvocationResolutionError, match="decision_id"):
        sources.route_decision(descriptor)


def test_module_is_read_only_composition_and_never_persists_pilot_input() -> None:
    path = Path(host_sources_module.__file__)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden_imports = ("subprocess", "socket", "requests", "urllib", "google.cloud", "boto")
    for module_name in imported:
        assert not any(token in module_name.lower() for token in forbidden_imports)

    for forbidden_call in (
        "append_dependency_readiness(",
        "append_invocation_descriptor(",
        "run_single_issue_pilot(",
        ".acquire(",
        ".release(",
        "subprocess.",
        "os.system(",
        ".write_text(",
        ".write_bytes(",
    ):
        assert forbidden_call not in source
