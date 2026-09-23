"""Focused tests for the #1237 execution-interface publication caller."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.agent_os_candidate_packet.execution_packet_stage import ExecutionPacketDisposition
import scripts.agent_os_execution_interface.governed_handoff_publication as publication


class _Prepared:
    pass


class _Stage:
    pass


class _Route:
    pass


class _AuthorizationRead:
    pass


def _case(monkeypatch):
    monkeypatch.setattr(publication, "PreparedCandidatePacket", _Prepared)
    monkeypatch.setattr(publication, "ExecutionPacketStageResult", _Stage)
    monkeypatch.setattr(publication, "ExecutorRouteDecision", _Route)
    monkeypatch.setattr(publication, "ExecutionAuthorizationReadResult", _AuthorizationRead)

    request = object()
    runtime_configuration = object()
    candidate_packet = SimpleNamespace(
        packet_id="candidate-packet:" + "a" * 64,
        invocation_id="invocation-1237",
    )
    stage = _Stage()
    stage.disposition = ExecutionPacketDisposition.GO
    stage.packet_complete = True
    stage.request = request
    stage.runtime_configuration = runtime_configuration

    prepared = _Prepared()
    prepared.execution_packet_stage_result = stage
    prepared.packet = candidate_packet

    route = _Route()
    route.requested_operation = publication.PRE_PR_DEVELOPER_LOOP_OPERATION

    authorization_evidence = object()
    authorization = _AuthorizationRead()
    authorization.status = publication.ExecutionAuthorizationSourceStatus.CURRENT
    authorization.evidence = authorization_evidence
    authorization.authorized_operation = publication.PRE_PR_DEVELOPER_LOOP_OPERATION
    authorization.authorized_candidate_packet_id = candidate_packet.packet_id
    authorization.authorized_invocation_id = candidate_packet.invocation_id

    checkpoint = object()
    resume_plan = object()
    dependency_readiness = object()
    pilot_input = object()
    returned = object()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_publish(*args, **kwargs):
        calls.append((args, kwargs))
        return returned

    monkeypatch.setattr(publication, "publish_governed_handoff", fake_publish)
    kwargs = {
        "store_root": "/var/lib/agent-os/checkpoints",
        "prepared_candidate": prepared,
        "route_decision": route,
        "authorization_read": authorization,
        "checkpoint": checkpoint,
        "resume_plan": resume_plan,
        "dependency_readiness": dependency_readiness,
        "pilot_input": pilot_input,
        "evaluated_at": "2026-08-23T23:00:00Z",
        "required_return_evidence": ("focused-test-results",),
        "stop_conditions": ("scope-expanded",),
    }
    return SimpleNamespace(
        kwargs=kwargs,
        prepared=prepared,
        stage=stage,
        route=route,
        authorization=authorization,
        authorization_evidence=authorization_evidence,
        candidate_packet=candidate_packet,
        checkpoint=checkpoint,
        resume_plan=resume_plan,
        dependency_readiness=dependency_readiness,
        pilot_input=pilot_input,
        returned=returned,
        calls=calls,
        request=request,
        runtime_configuration=runtime_configuration,
    )


def test_current_pre_pr_mission_delegates_once_to_existing_1243_publication(monkeypatch):
    case = _case(monkeypatch)

    result = publication.publish_current_pre_pr_handoff(**case.kwargs)

    assert result is case.returned
    assert len(case.calls) == 1
    args, kwargs = case.calls[0]
    assert args == (case.kwargs["store_root"],)
    assert kwargs == {
        "request": case.request,
        "route_decision": case.route,
        "authorization": case.authorization_evidence,
        "checkpoint": case.checkpoint,
        "resume_plan": case.resume_plan,
        "candidate_packet": case.candidate_packet,
        "runtime_configuration": case.runtime_configuration,
        "dependency_readiness": case.dependency_readiness,
        "pilot_input": case.pilot_input,
        "evaluated_at": case.kwargs["evaluated_at"],
        "required_return_evidence": case.kwargs["required_return_evidence"],
        "stop_conditions": case.kwargs["stop_conditions"],
    }


def test_non_pre_pr_route_fails_before_publication(monkeypatch):
    case = _case(monkeypatch)
    case.route.requested_operation = "aggregate-validation"

    with pytest.raises(
        publication.ExecutionInterfacePublicationError,
        match="route is not bound to pre-pr-developer-loop",
    ):
        publication.publish_current_pre_pr_handoff(**case.kwargs)

    assert case.calls == []


def test_missing_or_incomplete_candidate_fails_before_publication(monkeypatch):
    case = _case(monkeypatch)
    case.prepared.packet = None

    with pytest.raises(
        publication.ExecutionInterfacePublicationError,
        match="no complete execution-candidate evidence",
    ):
        publication.publish_current_pre_pr_handoff(**case.kwargs)
    assert case.calls == []

    case = _case(monkeypatch)
    case.stage.packet_complete = False
    with pytest.raises(
        publication.ExecutionInterfacePublicationError,
        match="execution packet is not complete and GO",
    ):
        publication.publish_current_pre_pr_handoff(**case.kwargs)
    assert case.calls == []


def test_malformed_execution_stage_fails_before_publication(monkeypatch):
    case = _case(monkeypatch)
    case.prepared.execution_packet_stage_result = SimpleNamespace(
        disposition=ExecutionPacketDisposition.GO,
        packet_complete=True,
        request=case.request,
        runtime_configuration=case.runtime_configuration,
    )

    with pytest.raises(
        publication.ExecutionInterfacePublicationError,
        match="execution packet evidence is malformed",
    ):
        publication.publish_current_pre_pr_handoff(**case.kwargs)

    assert case.calls == []


def test_non_current_authorization_fails_before_publication(monkeypatch):
    case = _case(monkeypatch)
    case.authorization.status = publication.ExecutionAuthorizationSourceStatus.BLOCKED
    case.authorization.evidence = None

    with pytest.raises(
        publication.ExecutionInterfacePublicationError,
        match="execution authorization is not current",
    ):
        publication.publish_current_pre_pr_handoff(**case.kwargs)

    assert case.calls == []


def test_authorization_must_bind_pre_pr_operation(monkeypatch):
    case = _case(monkeypatch)
    case.authorization.authorized_operation = "aggregate-validation"

    with pytest.raises(
        publication.ExecutionInterfacePublicationError,
        match="execution authorization is not bound to pre-pr-developer-loop",
    ):
        publication.publish_current_pre_pr_handoff(**case.kwargs)

    assert case.calls == []


def test_authorization_must_bind_candidate_and_invocation(monkeypatch):
    case = _case(monkeypatch)
    case.authorization.authorized_candidate_packet_id = "candidate-packet:" + "b" * 64

    with pytest.raises(
        publication.ExecutionInterfacePublicationError,
        match="does not bind the prepared candidate",
    ):
        publication.publish_current_pre_pr_handoff(**case.kwargs)
    assert case.calls == []

    case = _case(monkeypatch)
    case.authorization.authorized_invocation_id = "invocation-other"
    with pytest.raises(
        publication.ExecutionInterfacePublicationError,
        match="does not bind the prepared candidate",
    ):
        publication.publish_current_pre_pr_handoff(**case.kwargs)
    assert case.calls == []


def test_adapter_contains_no_scheduler_or_persistence_fallbacks():
    source = publication.__file__
    text = open(source, encoding="utf-8").read()

    assert "publish_governed_handoff(" in text
    assert "run_single_issue_pilot" not in text
    assert "append_invocation_descriptor" not in text
    assert "append_executor_handoff" not in text
    assert "acquire_lease" not in text
    assert "subprocess" not in text
