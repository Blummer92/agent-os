from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from agent_os_execution_service import first_publication_producer as producer


def _request() -> producer.FirstPublicationProducerRequest:
    marker = object()
    return producer.FirstPublicationProducerRequest(
        execution=marker,
        worktree=marker,
        environment=marker,
        dependencies=marker,
        acceptance=marker,
        governance=marker,
        stage_observations=(),
        actor_id="github-service-agent",
        candidate_packet=marker,
        pilot_input=marker,
        required_environment_spec=marker,
        dependency_readiness=marker,
        authorization=marker,
        route=marker,
        evaluated_at="2026-09-03T12:00:00Z",
        expires_at="2026-09-03T13:00:00Z",
    )


def test_architecture_has_no_publication_scheduler_or_dependency_install_surface() -> None:
    source = inspect.getsource(producer)
    assert "publish_authorized_validation_handoff" not in source
    assert "publish_governed_handoff" not in source
    assert "workflow_scheduler.scheduler" not in source
    assert "execute_dependency_preparation" not in source
    assert "DependencyCommandRunner" not in source
    assert "subprocess" not in source


def test_preconditions_fail_before_any_durable_write(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(producer, "parse_canonical_utc", lambda value: value)
    monkeypatch.setattr(producer, "_require_current_authorization", lambda *a, **k: None)

    def blocked(*_args, **_kwargs):
        raise producer.FirstPublicationProducerError("dependency-preparation-required")

    monkeypatch.setattr(producer, "_require_ready_dependencies", blocked)
    for name in (
        "append_checkpoint",
        "append_resume_plan",
        "append_route_decision",
        "append_dependency_readiness",
        "append_pre_publication_evidence",
    ):
        monkeypatch.setattr(
            producer, name, lambda *_a, _name=name, **_k: events.append(_name)
        )

    with pytest.raises(producer.FirstPublicationProducerError):
        producer.produce_first_publication_evidence("/tmp/store", _request())
    assert events == []


def test_success_composes_existing_owners_in_order_and_stops_before_publication(
    monkeypatch,
) -> None:
    events: list[str] = []
    checkpoint = SimpleNamespace(
        checkpoint_id="agent-os.execution-checkpoint:" + "a" * 64,
        repository="Blummer92/agent-os",
        issue_number=1428,
        execution_id="execution-1428",
        source_sha="a" * 40,
        tested_sha="a" * 40,
    )
    resume = SimpleNamespace(plan_id="resume-plan:" + "b" * 64)
    route = SimpleNamespace(decision_id="executor-route-decision:" + "c" * 64)
    dependency = SimpleNamespace(evidence_id="dependency-readiness:" + "d" * 64)
    capsule = SimpleNamespace(capsule_id="pre-publication-evidence:" + "e" * 64)
    authorization = SimpleNamespace(authorization_id="authorization:" + "f" * 64)
    request = _request()
    object.__setattr__(request, "authorization", authorization)

    monkeypatch.setattr(producer, "parse_canonical_utc", lambda value: value)
    monkeypatch.setattr(producer, "_require_current_authorization", lambda *a, **k: None)
    monkeypatch.setattr(producer, "_require_ready_dependencies", lambda *a, **k: None)
    monkeypatch.setattr(
        producer,
        "construct_execution_checkpoint",
        lambda **_kwargs: events.append("construct-checkpoint") or checkpoint,
    )
    monkeypatch.setattr(
        producer, "append_checkpoint", lambda *_a: events.append("persist-checkpoint")
    )
    monkeypatch.setattr(
        producer, "binding_snapshot_from_checkpoint", lambda *_a: object()
    )
    monkeypatch.setattr(
        producer,
        "plan_resume",
        lambda **_kwargs: events.append("plan-resume") or resume,
    )
    monkeypatch.setattr(
        producer, "append_resume_plan", lambda *_a: events.append("persist-resume")
    )
    monkeypatch.setattr(
        producer,
        "_select_route",
        lambda *_a, **_k: events.append("select-route") or route,
    )
    monkeypatch.setattr(
        producer, "append_route_decision", lambda *_a: events.append("persist-route")
    )
    monkeypatch.setattr(
        producer,
        "append_dependency_readiness",
        lambda *_a: events.append("persist-dependency") or dependency,
    )
    monkeypatch.setattr(
        producer,
        "build_pre_publication_evidence",
        lambda **_kwargs: events.append("build-capsule") or capsule,
    )
    monkeypatch.setattr(
        producer,
        "append_pre_publication_evidence",
        lambda *_a: events.append("persist-capsule"),
    )

    result = producer.produce_first_publication_evidence("/tmp/store", request)

    assert events == [
        "construct-checkpoint",
        "persist-checkpoint",
        "plan-resume",
        "persist-resume",
        "select-route",
        "persist-route",
        "persist-dependency",
        "build-capsule",
        "persist-capsule",
    ]
    assert result.checkpoint_id == checkpoint.checkpoint_id
    assert result.resume_plan_id == resume.plan_id
    assert result.route_decision_id == route.decision_id
    assert result.dependency_readiness_id == dependency.evidence_id
    assert result.pre_publication_evidence_id == capsule.capsule_id
    assert result.publication_invoked is False
    assert result.scheduler_invoked is False


def test_result_authority_flags_are_not_present() -> None:
    fields = producer.FirstPublicationProducerResult.__dataclass_fields__
    assert "execution_authorized" not in fields
    assert "publication_authorized" not in fields
    assert "github_writes_authorized" not in fields
    assert "merge_authorized" not in fields
