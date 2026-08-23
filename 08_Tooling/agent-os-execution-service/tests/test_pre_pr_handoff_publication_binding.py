from __future__ import annotations

import inspect
from types import SimpleNamespace

import agent_os_execution_service.handoff_publication as publication


def _route(
    *,
    operation: str = "pre-pr-developer-loop",
    capabilities: tuple[object, ...] = ("checkout", "test-execution"),
    evidence_stale: bool = False,
    evidence_contradictory: bool = False,
    environment_health_evidence_id: str = "environment-health:current",
):
    return SimpleNamespace(
        requested_operation=operation,
        required_capabilities=capabilities,
        evidence_stale=evidence_stale,
        evidence_contradictory=evidence_contradictory,
        environment_health_evidence_id_or_none=environment_health_evidence_id,
    )


def _runtime_configuration():
    return SimpleNamespace(required_environment_spec=object())


def _projection(
    *,
    capabilities: tuple[object, ...] = ("checkout", "test-execution"),
    evidence_stale: bool = False,
    evidence_contradictory: bool = False,
    environment_health_evidence_id: str = "environment-health:current",
):
    return SimpleNamespace(
        required_capabilities=capabilities,
        evidence_stale=evidence_stale,
        evidence_contradictory=evidence_contradictory,
        environment_health_evidence_id=environment_health_evidence_id,
    )


def test_non_pre_pr_operation_does_not_invoke_1278_projection(monkeypatch) -> None:
    monkeypatch.setattr(
        publication,
        "project_pre_pr_runtime_capabilities",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected projection")),
    )

    assert publication._pre_pr_runtime_projection_matches(
        route_decision=_route(operation="implement-handoff-publication"),
        runtime_configuration=_runtime_configuration(),
        dependency_readiness=object(),
        evaluated_at="2026-08-21T17:00:00Z",
    )


def test_missing_mandatory_runtime_capability_fails_projection_binding(monkeypatch) -> None:
    route = _route(capabilities=("checkout",))
    monkeypatch.setattr(
        publication,
        "project_pre_pr_runtime_capabilities",
        lambda **kwargs: _projection(
            capabilities=tuple((*kwargs["base_required_capabilities"], "test-execution"))
        ),
    )

    assert not publication._pre_pr_runtime_projection_matches(
        route_decision=route,
        runtime_configuration=_runtime_configuration(),
        dependency_readiness=object(),
        evaluated_at="2026-08-21T17:00:00Z",
    )


def test_projection_binding_preserves_legitimate_additional_capabilities(monkeypatch) -> None:
    route = _route(capabilities=("checkout", "generated-artifact-inspection", "test-execution"))
    captured = {}

    def project(**kwargs):
        captured.update(kwargs)
        return _projection(capabilities=kwargs["base_required_capabilities"])

    monkeypatch.setattr(publication, "project_pre_pr_runtime_capabilities", project)

    assert publication._pre_pr_runtime_projection_matches(
        route_decision=route,
        runtime_configuration=_runtime_configuration(),
        dependency_readiness=object(),
        evaluated_at="2026-08-21T17:00:00Z",
    )
    assert captured["base_required_capabilities"] == route.required_capabilities


def test_stale_or_contradictory_projection_drift_fails_closed(monkeypatch) -> None:
    route = _route()
    monkeypatch.setattr(
        publication,
        "project_pre_pr_runtime_capabilities",
        lambda **_kwargs: _projection(evidence_stale=True),
    )
    assert not publication._pre_pr_runtime_projection_matches(
        route_decision=route,
        runtime_configuration=_runtime_configuration(),
        dependency_readiness=object(),
        evaluated_at="2026-08-21T17:00:00Z",
    )

    monkeypatch.setattr(
        publication,
        "project_pre_pr_runtime_capabilities",
        lambda **_kwargs: _projection(evidence_contradictory=True),
    )
    assert not publication._pre_pr_runtime_projection_matches(
        route_decision=route,
        runtime_configuration=_runtime_configuration(),
        dependency_readiness=object(),
        evaluated_at="2026-08-21T17:00:00Z",
    )


def test_environment_health_identity_drift_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        publication,
        "project_pre_pr_runtime_capabilities",
        lambda **_kwargs: _projection(
            environment_health_evidence_id="environment-health:different"
        ),
    )

    assert not publication._pre_pr_runtime_projection_matches(
        route_decision=_route(),
        runtime_configuration=_runtime_configuration(),
        dependency_readiness=object(),
        evaluated_at="2026-08-21T17:00:00Z",
    )


def test_publication_checks_projection_after_route_gate_and_before_artifact_build() -> None:
    source = inspect.getsource(publication.publish_governed_handoff)

    route_gate = source.index("route-not-governed-runner")
    projection_gate = source.index("_pre_pr_runtime_projection_matches")
    handoff_build = source.index("build_executor_handoff")
    route_persistence = source.index("append_route_decision")

    assert route_gate < projection_gate < handoff_build < route_persistence
