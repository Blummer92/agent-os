from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from agent_os_execution_service import first_publication_source_activation as activation


def _request() -> activation.FirstPublicationSourceActivationRequest:
    marker = SimpleNamespace(
        repository="Blummer92/agent-os",
        issue_number=1428,
        invocation_id="invocation-1428",
        execution_id="execution-1428",
        branch="agent/1428-first-publication-producer",
        source_sha="a" * 40,
        tested_sha="b" * 40,
    )
    return activation.FirstPublicationSourceActivationRequest(
        source_capsule_id="pre-publication-evidence:" + "1" * 64,
        execution=marker,
        worktree=object(),
        environment=object(),
        dependencies=object(),
        acceptance=object(),
        governance=object(),
        stage_observations=(),
        actor_id="github-service-agent",
        dependency_readiness=object(),
        authorization=SimpleNamespace(authorization_id="authorization:" + "2" * 64),
        route=object(),
        evaluated_at="2026-09-03T15:00:00Z",
        expires_at="2026-09-03T16:00:00Z",
    )


def _source(request):
    return SimpleNamespace(
        execution_id=request.execution.execution_id,
        candidate_branch=request.execution.branch,
        required_environment_spec=object(),
        candidate_packet=SimpleNamespace(
            repository=request.execution.repository,
            issue_number=request.execution.issue_number,
            invocation_id=request.execution.invocation_id,
            candidate_sha=request.execution.source_sha,
            tested_sha=request.execution.tested_sha,
        ),
    )


def test_activation_has_no_publication_scheduler_install_or_transport_surface() -> None:
    source = inspect.getsource(activation)
    for forbidden in (
        "publish_authorized_validation_handoff",
        "publish_governed_handoff",
        "workflow_scheduler.scheduler",
        "DependencyCommandRunner",
        "subprocess",
        "requests",
        "google.cloud",
    ):
        assert forbidden not in source


def test_source_binding_failure_occurs_before_any_write(monkeypatch) -> None:
    request = _request()
    source = _source(request)
    source.candidate_packet.issue_number = 999
    events: list[str] = []
    monkeypatch.setattr(activation, "parse_canonical_utc", lambda value: value)
    monkeypatch.setattr(activation, "load_source_pre_publication_evidence", lambda *_a: source)
    for name in (
        "append_checkpoint",
        "append_pre_publication_evidence",
        "append_resume_plan",
        "append_route_decision",
        "append_dependency_readiness",
    ):
        monkeypatch.setattr(activation, name, lambda *_a, _name=name, **_k: events.append(_name))
    with pytest.raises(activation.FirstPublicationProducerError, match="source-capsule-binding-mismatch"):
        activation.activate_first_publication_source("/tmp/store", request)
    assert events == []


def test_success_binds_source_after_durable_checkpoint_and_stops_before_publication(monkeypatch) -> None:
    request = _request()
    source = _source(request)
    events: list[str] = []
    checkpoint = SimpleNamespace(
        checkpoint_id="agent-os.execution-checkpoint:" + "3" * 64,
        repository=request.execution.repository,
        issue_number=request.execution.issue_number,
        execution_id=request.execution.execution_id,
        source_sha=request.execution.source_sha,
        tested_sha=request.execution.tested_sha,
    )
    bound = SimpleNamespace(capsule_id="pre-publication-evidence:" + "4" * 64)
    resume = SimpleNamespace(plan_id="resume-plan:" + "5" * 64)
    route = SimpleNamespace(decision_id="executor-route-decision:" + "6" * 64)
    dependency = SimpleNamespace(evidence_id="dependency-readiness:" + "7" * 64)

    monkeypatch.setattr(activation, "parse_canonical_utc", lambda value: value)
    monkeypatch.setattr(activation, "load_source_pre_publication_evidence", lambda *_a: events.append("load-source") or source)
    monkeypatch.setattr(activation, "_require_current_authorization", lambda *_a, **_k: events.append("authorization-current"))
    monkeypatch.setattr(activation, "_require_ready_dependencies", lambda *_a, **_k: events.append("dependency-current"))
    monkeypatch.setattr(activation, "construct_execution_checkpoint", lambda **_k: events.append("construct-checkpoint") or checkpoint)
    monkeypatch.setattr(activation, "append_checkpoint", lambda *_a: events.append("persist-checkpoint"))
    monkeypatch.setattr(activation, "bind_source_capsule_to_checkpoint", lambda *_a: events.append("bind-source") or bound)
    monkeypatch.setattr(activation, "append_pre_publication_evidence", lambda *_a: events.append("persist-bound-capsule"))
    monkeypatch.setattr(activation, "binding_snapshot_from_checkpoint", lambda *_a: object())
    monkeypatch.setattr(activation, "plan_resume", lambda **_k: events.append("plan-resume") or resume)
    monkeypatch.setattr(activation, "append_resume_plan", lambda *_a: events.append("persist-resume"))
    monkeypatch.setattr(activation, "_select_route", lambda *_a, **_k: events.append("select-route") or route)
    monkeypatch.setattr(activation, "append_route_decision", lambda *_a: events.append("persist-route"))
    monkeypatch.setattr(activation, "append_dependency_readiness", lambda *_a: events.append("persist-dependency") or dependency)

    result = activation.activate_first_publication_source("/tmp/store", request)

    assert events == [
        "load-source",
        "authorization-current",
        "dependency-current",
        "construct-checkpoint",
        "persist-checkpoint",
        "bind-source",
        "persist-bound-capsule",
        "plan-resume",
        "persist-resume",
        "select-route",
        "persist-route",
        "persist-dependency",
    ]
    assert result.pre_publication_evidence_id == bound.capsule_id
    assert result.publication_invoked is False
    assert result.scheduler_invoked is False


def test_request_has_no_caller_selected_store_or_authority_fields() -> None:
    fields = activation.FirstPublicationSourceActivationRequest.__dataclass_fields__
    for forbidden in (
        "store_root",
        "repository_root",
        "workspace_parent",
        "lease_directory",
        "command",
        "credential",
        "execution_authorized",
        "publication_authorized",
        "scheduler_authorized",
    ):
        assert forbidden not in fields
