from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest

import agent_os_execution_service.runtime_execution_request as runtime_request


class _Route:
    selected_route = None

    def to_dict(self):
        return {"kind": "route"}

    @classmethod
    def from_dict(cls, _payload):
        return ROUTE


class _Handoff:
    def to_dict(self):
        return {"kind": "handoff"}

    @classmethod
    def from_dict(cls, _payload):
        return HANDOFF


class _Descriptor:
    def to_dict(self):
        return {"kind": "descriptor"}


class _Capsule:
    pass


ROUTE = _Route()
HANDOFF = _Handoff()
DESCRIPTOR = _Descriptor()
CAPSULE = _Capsule()


def _bind_fakes(monkeypatch):
    governed = SimpleNamespace(value="chatgpt-governed-runner")
    monkeypatch.setattr(runtime_request, "ExecutorRouteDecision", _Route)
    monkeypatch.setattr(runtime_request, "ExecutorHandoff", _Handoff)
    monkeypatch.setattr(runtime_request, "GovernedInvocationDescriptor", _Descriptor)
    monkeypatch.setattr(runtime_request, "GovernedResumeRestartCapsule", _Capsule)
    monkeypatch.setattr(
        runtime_request,
        "ExecutorRoute",
        SimpleNamespace(CHATGPT_GOVERNED_RUNNER=governed),
    )

    ROUTE.selected_route = governed
    ROUTE.decision_id = "executor-route-decision:" + "1" * 64
    ROUTE.repository = "Blummer92/agent-os"
    ROUTE.execution_service_request_fingerprint_or_none = "execution-request:" + "2" * 64
    ROUTE.authorization_id_or_none = "authorization:" + "3" * 64
    ROUTE.checkpoint_id_or_none = "checkpoint:" + "4" * 64
    ROUTE.resume_plan_id_or_none = "resume-plan:" + "5" * 64
    ROUTE.environment_profile_id_or_none = "environment-profile:" + "6" * 64
    ROUTE.environment_health_evidence_id_or_none = "environment-health:" + "7" * 64
    ROUTE.workflow_runtime_identity_or_none = "workflow-runtime:" + "8" * 64

    HANDOFF.destination_route = governed
    HANDOFF.route_decision_id = ROUTE.decision_id
    HANDOFF.handoff_id = "executor-handoff:" + "9" * 64
    HANDOFF.repository = ROUTE.repository
    HANDOFF.issue_or_handoff_identity = "issue:1338"
    HANDOFF.execution_service_request_fingerprint_or_none = ROUTE.execution_service_request_fingerprint_or_none
    HANDOFF.authorization_id_or_none = ROUTE.authorization_id_or_none
    HANDOFF.source_ref_or_none = "refs/heads/agent/1338-runtime-request"
    HANDOFF.source_sha_or_none = "a" * 40
    HANDOFF.checkpoint_id_or_none = ROUTE.checkpoint_id_or_none
    HANDOFF.resume_plan_id_or_none = ROUTE.resume_plan_id_or_none
    HANDOFF.environment_profile_id_or_none = ROUTE.environment_profile_id_or_none
    HANDOFF.allowed_paths = ("08_Tooling/agent-os-execution-service",)
    HANDOFF.forbidden_paths = (".github/workflows",)

    DESCRIPTOR.route_decision_id = ROUTE.decision_id
    DESCRIPTOR.handoff_id = HANDOFF.handoff_id
    DESCRIPTOR.repository = ROUTE.repository
    DESCRIPTOR.issue_number = 1338
    DESCRIPTOR.issue_or_handoff_identity = HANDOFF.issue_or_handoff_identity
    DESCRIPTOR.execution_service_request_fingerprint = ROUTE.execution_service_request_fingerprint_or_none
    DESCRIPTOR.authorization_id = ROUTE.authorization_id_or_none
    DESCRIPTOR.source_ref = HANDOFF.source_ref_or_none
    DESCRIPTOR.source_sha = HANDOFF.source_sha_or_none
    DESCRIPTOR.checkpoint_id = ROUTE.checkpoint_id_or_none
    DESCRIPTOR.resume_plan_id = ROUTE.resume_plan_id_or_none
    DESCRIPTOR.environment_profile_id = ROUTE.environment_profile_id_or_none
    DESCRIPTOR.environment_health_evidence_id = ROUTE.environment_health_evidence_id_or_none
    DESCRIPTOR.workflow_runtime_identity = ROUTE.workflow_runtime_identity_or_none
    DESCRIPTOR.required_environment_id = "required-environment:" + "b" * 64
    DESCRIPTOR.candidate_packet_id = "candidate-packet:" + "c" * 64
    DESCRIPTOR.invocation_id = "invocation-1338"

    CAPSULE.handoff_id = HANDOFF.handoff_id
    CAPSULE.candidate_packet = SimpleNamespace(
        repository=ROUTE.repository,
        issue_number=1338,
        invocation_id=DESCRIPTOR.invocation_id,
        candidate_sha=DESCRIPTOR.source_sha,
        packet_id=DESCRIPTOR.candidate_packet_id,
        allowed_files=HANDOFF.allowed_paths,
        forbidden_paths=HANDOFF.forbidden_paths,
    )
    CAPSULE.required_environment_spec = SimpleNamespace(
        required_environment_id=DESCRIPTOR.required_environment_id
    )
    monkeypatch.setattr(
        runtime_request,
        "serialize_restart_capsule",
        lambda _capsule: b'{"kind":"capsule"}',
    )
    monkeypatch.setattr(
        runtime_request,
        "deserialize_invocation_descriptor",
        lambda _payload: DESCRIPTOR,
    )
    monkeypatch.setattr(
        runtime_request,
        "deserialize_restart_capsule",
        lambda _payload: CAPSULE,
    )


def _request(monkeypatch):
    _bind_fakes(monkeypatch)
    return runtime_request.RuntimeExecutionRequest(
        schema_name=runtime_request.RUNTIME_EXECUTION_REQUEST_SCHEMA_NAME,
        schema_version=runtime_request.RUNTIME_EXECUTION_REQUEST_SCHEMA_VERSION,
        route_decision=ROUTE,
        handoff=HANDOFF,
        invocation_descriptor=DESCRIPTOR,
        restart_capsule=CAPSULE,
    )


def test_request_is_content_addressed_and_non_authorizing(monkeypatch) -> None:
    request = _request(monkeypatch)
    assert request.request_id.startswith("runtime-execution-request:")
    assert request.handoff_id == HANDOFF.handoff_id
    assert request.execution_authorized is False
    assert request.github_writes_authorized is False
    assert request.merge_authorized is False
    assert request.issue_closure_authorized is False
    assert request.external_writes_authorized is False


def test_request_store_is_idempotent(monkeypatch, tmp_path) -> None:
    request = _request(monkeypatch)
    first = runtime_request.append_runtime_execution_request(tmp_path, request)
    second = runtime_request.append_runtime_execution_request(tmp_path, request)
    assert first.request_id == second.request_id == request.request_id
    assert first.already_present is False
    assert second.already_present is True


def test_binding_drift_fails_closed(monkeypatch) -> None:
    _bind_fakes(monkeypatch)
    original = DESCRIPTOR.source_sha
    DESCRIPTOR.source_sha = "b" * 40
    try:
        with pytest.raises(ValueError, match="source binding drifted"):
            runtime_request.RuntimeExecutionRequest(
                schema_name=runtime_request.RUNTIME_EXECUTION_REQUEST_SCHEMA_NAME,
                schema_version=runtime_request.RUNTIME_EXECUTION_REQUEST_SCHEMA_VERSION,
                route_decision=ROUTE,
                handoff=HANDOFF,
                invocation_descriptor=DESCRIPTOR,
                restart_capsule=CAPSULE,
            )
    finally:
        DESCRIPTOR.source_sha = original


def test_dual_read_prefers_canonical_request(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(runtime_request, "load_runtime_execution_request", lambda *_args: sentinel)
    monkeypatch.setattr(
        runtime_request,
        "load_invocation_descriptor",
        lambda *_args: (_ for _ in ()).throw(AssertionError("legacy fallback used")),
    )
    result = runtime_request.load_runtime_execution_request_or_legacy("/tmp/store", HANDOFF.handoff_id)
    assert result.request is sentinel
    assert result.source == "runtime-execution-request"


def test_dual_read_falls_back_only_when_canonical_request_is_absent(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(
        runtime_request,
        "load_runtime_execution_request",
        lambda *_args: (_ for _ in ()).throw(
            runtime_request.RuntimeExecutionRequestNotFound(HANDOFF.handoff_id)
        ),
    )
    descriptor = SimpleNamespace(route_decision_id="route-id")
    monkeypatch.setattr(runtime_request, "load_invocation_descriptor", lambda *_args: descriptor)
    monkeypatch.setattr(runtime_request, "load_route_decision", lambda *_args: object())
    monkeypatch.setattr(runtime_request, "load_executor_handoff", lambda *_args: object())
    monkeypatch.setattr(runtime_request, "load_restart_capsule", lambda *_args: object())
    monkeypatch.setattr(runtime_request, "build_runtime_execution_request", lambda **_kwargs: sentinel)
    result = runtime_request.load_runtime_execution_request_or_legacy("/tmp/store", HANDOFF.handoff_id)
    assert result.request is sentinel
    assert result.source == "legacy-artifacts"


def test_integrity_failure_never_silently_falls_back(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_request,
        "load_runtime_execution_request",
        lambda *_args: (_ for _ in ()).throw(
            runtime_request.RuntimeExecutionRequestIntegrityError("tampered")
        ),
    )
    monkeypatch.setattr(
        runtime_request,
        "load_invocation_descriptor",
        lambda *_args: (_ for _ in ()).throw(AssertionError("legacy fallback used")),
    )
    with pytest.raises(runtime_request.RuntimeExecutionRequestIntegrityError):
        runtime_request.load_runtime_execution_request_or_legacy("/tmp/store", HANDOFF.handoff_id)


def test_module_has_no_execution_or_external_io_imports() -> None:
    source = inspect.getsource(runtime_request)
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(
        token in name.lower()
        for name in imported
        for token in ("subprocess", "socket", "requests", "google.cloud", "github")
    )
    assert "run_single_issue_pilot(" not in source
    assert "execution_authorized=True" not in source
