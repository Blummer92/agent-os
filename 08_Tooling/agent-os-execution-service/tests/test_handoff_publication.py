from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_os_execution_service.current_invocation_resolver as resolver_module
import agent_os_execution_service.handoff_publication as publication
from agent_os_execution_service.authorization import ExecutionAuthorizationEvidence
from agent_os_execution_service.executor_routing import (
    ExecutorHandoff,
    ExecutorRoute,
    ExecutorRouteDecision,
)
from agent_os_execution_service.invocation_reconstruction import (
    InvocationReconstructionReason,
)
from agent_os_execution_service.models import ExecutionServiceRequest
from scripts.agent_os_candidate_packet.models import CandidatePacket
from scripts.agent_os_execution_capabilities.dependencies import DependencyReadinessEvidence
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    AppendInvocationDescriptorOutcome,
    GovernedInvocationDescriptor,
)
from scripts.agent_os_execution_checkpoint.models import ExecutionCheckpoint
from scripts.agent_os_execution_checkpoint.resume_planner import ResumePlan
from workflow_scheduler.execution.runtime_configuration import ConcreteRuntimeConfiguration
from workflow_scheduler.execution.single_issue_pilot import SingleIssuePilotInput


def _shell(cls, **attrs):
    value = object.__new__(cls)
    for name, item in attrs.items():
        object.__setattr__(value, name, item)
    return value


def _inputs(route: ExecutorRoute = ExecutorRoute.CHATGPT_GOVERNED_RUNNER):
    repository = "Blummer92/agent-os"
    sha = "a" * 40
    request = _shell(
        ExecutionServiceRequest,
        repository_identity=SimpleNamespace(owner="Blummer92", repository="agent-os"),
        issue_or_handoff_identity="issue:1243",
        request_fingerprint="execution-request:" + "1" * 64,
        requested_ref="refs/heads/agent/1243-handoff-publication",
        expected_sha=sha,
        allowed_paths=("08_Tooling/agent-os-execution-service/",),
        forbidden_paths=(".github/workflows/",),
    )
    decision = _shell(
        ExecutorRouteDecision,
        selected_route=route,
        repository=repository,
        issue_or_handoff_identity=request.issue_or_handoff_identity,
        execution_service_request_fingerprint_or_none=request.request_fingerprint,
        environment_profile_id_or_none="environment-profile:" + "2" * 64,
    )
    authorization = _shell(ExecutionAuthorizationEvidence)
    checkpoint = _shell(
        ExecutionCheckpoint,
        checkpoint_id="agent-os.execution-checkpoint:" + "3" * 64,
    )
    resume = _shell(
        ResumePlan,
        plan_id="agent-os.execution-checkpoint.resume-plan:" + "4" * 64,
    )
    packet = _shell(CandidatePacket)
    configuration = _shell(ConcreteRuntimeConfiguration, repository_identity=request.repository_identity)
    readiness = _shell(DependencyReadinessEvidence)
    pilot = _shell(SingleIssuePilotInput)
    handoff = _shell(ExecutorHandoff, handoff_id="executor-handoff:" + "5" * 64)
    descriptor = _shell(
        GovernedInvocationDescriptor,
        repository=repository,
        issue_or_handoff_identity=request.issue_or_handoff_identity,
        execution_service_request_fingerprint=request.request_fingerprint,
        source_ref=request.requested_ref,
        source_sha=sha,
        descriptor_id="agent-os.governed-invocation-descriptor:" + "6" * 64,
    )
    return {
        "request": request,
        "route_decision": decision,
        "authorization": authorization,
        "checkpoint": checkpoint,
        "resume_plan": resume,
        "candidate_packet": packet,
        "runtime_configuration": configuration,
        "dependency_readiness": readiness,
        "pilot_input": pilot,
        "handoff": handoff,
        "descriptor": descriptor,
    }


def _wire_success(monkeypatch, values, events, *, already_present=False):
    monkeypatch.setattr(
        publication,
        "validate_execution_service_request",
        lambda *_a, **_k: (),
    )
    monkeypatch.setattr(
        publication,
        "_reselect",
        lambda route: events.append("select") or route,
    )
    monkeypatch.setattr(
        publication,
        "build_executor_handoff",
        lambda *_a, **_k: events.append("build") or values["handoff"],
    )
    monkeypatch.setattr(
        publication,
        "build_current_invocation_descriptor",
        lambda **_k: events.append("descriptor") or values["descriptor"],
    )
    monkeypatch.setattr(
        publication,
        "validate_current_invocation_bindings",
        lambda *_a, **_k: events.append("validate") or (),
    )

    def persist(*_a, **_k):
        events.append("persist")
        return AppendInvocationDescriptorOutcome(
            descriptor_id=values["descriptor"].descriptor_id,
            handoff_id=values["handoff"].handoff_id,
            path=Path("/tmp/invocations/example.json"),
            already_present=already_present,
        )

    monkeypatch.setattr(publication, "persist_current_invocation_descriptor", persist)


def _publish(values):
    return publication.publish_governed_handoff(
        "/tmp/checkpoints",
        request=values["request"],
        route_decision=values["route_decision"],
        authorization=values["authorization"],
        checkpoint=values["checkpoint"],
        resume_plan=values["resume_plan"],
        candidate_packet=values["candidate_packet"],
        runtime_configuration=values["runtime_configuration"],
        dependency_readiness=values["dependency_readiness"],
        pilot_input=values["pilot_input"],
        evaluated_at="2026-08-18T02:20:00Z",
        required_return_evidence=("focused-tests",),
        stop_conditions=("evidence-stale",),
    )


def test_publication_orders_route_build_validate_persist_before_return(monkeypatch) -> None:
    values = _inputs()
    events = []
    _wire_success(monkeypatch, values, events)

    result = _publish(values)

    assert result is values["handoff"]
    assert events == ["select", "build", "descriptor", "validate", "persist"]


def test_equivalent_repeat_is_idempotent_and_reuses_handoff_identity(monkeypatch) -> None:
    values = _inputs()
    events = []
    _wire_success(monkeypatch, values, events, already_present=True)

    first = _publish(values)
    second = _publish(values)

    assert first.handoff_id == second.handoff_id == values["handoff"].handoff_id
    assert events.count("persist") == 2


def test_current_binding_failure_prevents_descriptor_persistence(monkeypatch) -> None:
    values = _inputs()
    events = []
    _wire_success(monkeypatch, values, events)
    monkeypatch.setattr(
        publication,
        "validate_current_invocation_bindings",
        lambda *_a, **_k: (InvocationReconstructionReason.SOURCE_MISMATCH,),
    )
    monkeypatch.setattr(
        publication,
        "persist_current_invocation_descriptor",
        lambda *_a, **_k: pytest.fail("persistence must not run"),
    )

    with pytest.raises(publication.HandoffPublicationError) as caught:
        _publish(values)

    assert caught.value.reason_codes == ("source-mismatch",)


def test_non_governed_route_exposes_no_handoff_or_descriptor(monkeypatch) -> None:
    values = _inputs(ExecutorRoute.CHATGPT_CONNECTOR_NATIVE)
    monkeypatch.setattr(
        publication,
        "validate_execution_service_request",
        lambda *_a, **_k: (),
    )
    monkeypatch.setattr(publication, "_reselect", lambda route: route)
    monkeypatch.setattr(
        publication,
        "build_executor_handoff",
        lambda *_a, **_k: pytest.fail("handoff must not be built"),
    )
    monkeypatch.setattr(
        publication,
        "persist_current_invocation_descriptor",
        lambda *_a, **_k: pytest.fail("descriptor must not be persisted"),
    )

    with pytest.raises(publication.HandoffPublicationError) as caught:
        _publish(values)

    assert caught.value.reason_codes == ("route-not-governed-runner",)


def test_persistence_failure_returns_no_runnable_handoff(monkeypatch) -> None:
    values = _inputs()
    events = []
    _wire_success(monkeypatch, values, events)

    def fail(*_a, **_k):
        events.append("persist-failed")
        raise OSError("simulated store failure")

    monkeypatch.setattr(publication, "persist_current_invocation_descriptor", fail)

    with pytest.raises(publication.HandoffPublicationError) as caught:
        _publish(values)

    assert caught.value.reason_codes == ("descriptor-persistence-failed",)
    assert events[-1] == "persist-failed"


def test_persistence_identity_mismatch_fails_closed(monkeypatch) -> None:
    values = _inputs()
    events = []
    _wire_success(monkeypatch, values, events)
    monkeypatch.setattr(
        publication,
        "persist_current_invocation_descriptor",
        lambda *_a, **_k: AppendInvocationDescriptorOutcome(
            descriptor_id="agent-os.governed-invocation-descriptor:" + "9" * 64,
            handoff_id=values["handoff"].handoff_id,
            path=Path("/tmp/invocations/example.json"),
            already_present=False,
        ),
    )

    with pytest.raises(publication.HandoffPublicationError) as caught:
        _publish(values)

    assert caught.value.reason_codes == ("descriptor-persistence-mismatch",)


def test_writer_delegates_to_pure_descriptor_builder_once(monkeypatch) -> None:
    values = _inputs()
    calls = []
    monkeypatch.setattr(
        resolver_module,
        "build_current_invocation_descriptor",
        lambda **_k: calls.append("build") or values["descriptor"],
    )
    monkeypatch.setattr(
        resolver_module,
        "append_invocation_descriptor",
        lambda _root, descriptor: calls.append(("append", descriptor)) or "written",
    )

    result = resolver_module.persist_current_invocation_descriptor(
        "/tmp/checkpoints",
        route_decision=values["route_decision"],
        handoff=values["handoff"],
        authorization=values["authorization"],
        checkpoint=values["checkpoint"],
        resume_plan=values["resume_plan"],
        candidate_packet=values["candidate_packet"],
        runtime_configuration=values["runtime_configuration"],
        dependency_readiness=values["dependency_readiness"],
        pilot_input=values["pilot_input"],
    )

    assert result == "written"
    assert calls == ["build", ("append", values["descriptor"])]


def test_publication_modules_do_not_own_scheduler_process_network_or_pilot_persistence() -> None:
    for module in (publication, resolver_module):
        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        forbidden_imports = (
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "google.cloud",
            "boto",
        )
        assert not any(
            token in imported.lower()
            for imported in imports
            for token in forbidden_imports
        )
        for forbidden_call in (
            "run_single_issue_pilot(",
            "run_single_issue_runtime_entrypoint(",
            "run_concrete_runtime_entrypoint_with_validation_evidence(",
            ".acquire(",
            ".release(",
            "serialize_single_issue_pilot",
            "subprocess.",
            "os.system(",
        ):
            assert forbidden_call not in source
