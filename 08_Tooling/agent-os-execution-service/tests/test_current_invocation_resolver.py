from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import agent_os_execution_service.current_invocation_resolver as resolver_module


def test_resolver_module_is_composition_only() -> None:
    path = Path(resolver_module.__file__)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
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
        "google.cloud",
        "boto",
    )
    for module_name in imported:
        assert not any(token in module_name.lower() for token in forbidden)
    for forbidden_call in (
        "run_single_issue_pilot(",
        "run_single_issue_runtime_entrypoint(",
        "build_compute_control_projection(",
        ".acquire(",
        ".release(",
        "subprocess.",
        "os.system(",
    ):
        assert forbidden_call not in source


def test_descriptor_writer_dual_writes_canonical_request_and_legacy_mirror(monkeypatch) -> None:
    captured = {}

    class Value:
        pass

    route = Value()
    route.decision_id = "executor-route-decision:" + "1" * 64
    route.execution_service_request_fingerprint_or_none = "execution-request:" + "2" * 64
    route.authorization_id_or_none = "execution-authorization:" + "3" * 64
    route.environment_profile_id_or_none = "environment-profile:" + "4" * 64
    route.environment_health_evidence_id_or_none = "environment-health:" + "5" * 64
    route.workflow_runtime_identity_or_none = "workflow-runtime:" + "6" * 64
    route.created_at = "2026-08-22T00:00:00Z"
    route.expires_at = "2026-08-23T00:00:00Z"

    handoff = Value()
    handoff.issue_or_handoff_identity = "issue:1338"
    handoff.handoff_id = "executor-handoff:" + "7" * 64
    handoff.source_ref_or_none = "refs/heads/agent/1338-runtime-request"
    handoff.source_sha_or_none = "a" * 40

    authorization = Value()
    authorization.authorization_id = route.authorization_id_or_none

    checkpoint = Value()
    checkpoint.repository = "Blummer92/agent-os"
    checkpoint.issue_number = 1338
    checkpoint.checkpoint_id = "agent-os.execution-checkpoint:" + "8" * 64
    checkpoint.execution_id = "execution-1338"
    checkpoint.invocation_id = "invocation-1338"

    resume = Value()
    resume.plan_id = "agent-os.execution-checkpoint.resume-plan:" + "9" * 64

    packet = Value()
    runtime = Value()
    runtime.configuration_fingerprint = "concrete-adapters:" + "b" * 64
    runtime.required_environment_spec = object()

    readiness = Value()
    readiness.required_environment_id = "required-environment:" + "c" * 64
    readiness.dependency_readiness_evidence_id = "dependency-readiness:" + "d" * 64
    readiness.execution_surface_id = "execution-surface:gce-agent-os-test"

    pilot = Value()
    pilot.workspace_request_id = "workspace-1338"
    pilot.repository = checkpoint.repository
    pilot.branch = "agent/1338-runtime-request"
    pilot.source_head_sha = handoff.source_sha_or_none

    compute_control_projection = object()

    monkeypatch.setattr(
        resolver_module,
        "candidate_packet_id",
        lambda _packet: "candidate-packet:" + "e" * 64,
    )
    monkeypatch.setattr(
        resolver_module,
        "pilot_workspace_identity",
        lambda _request: "pilot-workspace:" + "f" * 64,
    )

    events = []

    def append_descriptor(_root, descriptor):
        captured["descriptor"] = descriptor
        events.append("descriptor")
        return "written"

    capsule = object()
    request = object()
    monkeypatch.setattr(resolver_module, "append_invocation_descriptor", append_descriptor)
    monkeypatch.setattr(
        resolver_module,
        "build_restart_capsule",
        lambda **_kwargs: events.append("capsule") or capsule,
    )
    monkeypatch.setattr(
        resolver_module,
        "build_runtime_execution_request",
        lambda **kwargs: captured.update(request_kwargs=kwargs) or request,
    )
    monkeypatch.setattr(
        resolver_module,
        "append_runtime_execution_request",
        lambda _root, value: events.append("runtime-request")
        or captured.update(runtime_request=value),
    )

    result = resolver_module.persist_current_invocation_descriptor(
        "/tmp/checkpoints",
        route_decision=route,
        handoff=handoff,
        authorization=authorization,
        checkpoint=checkpoint,
        resume_plan=resume,
        candidate_packet=packet,
        runtime_configuration=runtime,
        dependency_readiness=readiness,
        pilot_input=pilot,
        compute_control_projection=compute_control_projection,
    )
    assert result == "written"
    descriptor = captured["descriptor"]
    assert descriptor.handoff_id == handoff.handoff_id
    assert descriptor.authorization_id == authorization.authorization_id
    assert descriptor.candidate_packet_id == "candidate-packet:" + "e" * 64
    assert descriptor.workspace_identity == "pilot-workspace:" + "f" * 64
    assert descriptor.execution_authorized is False
    assert descriptor.github_writes_authorized is False
    assert descriptor.external_writes_authorized is False
    assert not hasattr(descriptor, "pilot_input")
    assert captured["runtime_request"] is request
    assert captured["request_kwargs"]["invocation_descriptor"] is descriptor
    assert captured["request_kwargs"]["restart_capsule"] is capsule
    assert (
        captured["request_kwargs"]["compute_control_projection"]
        is compute_control_projection
    )
    assert events == ["capsule", "runtime-request", "descriptor"]


def test_descriptor_loader_prefers_runtime_request_dual_read(monkeypatch) -> None:
    descriptor = object()
    loaded = SimpleNamespace(request=SimpleNamespace(invocation_descriptor=descriptor))
    monkeypatch.setattr(
        resolver_module,
        "load_runtime_execution_request_or_legacy",
        lambda *_args: loaded,
    )
    assert (
        resolver_module.load_current_invocation_descriptor(
            "/tmp/checkpoints", "executor-handoff:" + "1" * 64
        )
        is descriptor
    )
