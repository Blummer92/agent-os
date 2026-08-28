"""Offline tests for the #1217 installed-entrypoint production factory."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import agent_os_execution_service.production_governed_resume_factory as factory
from agent_os_execution_service.production_governed_resume_factory import (
    ProductionGovernedResumeFactoryError,
    _rebuild_advisory_result,
    build_production_governed_resume_bindings_for_handoff,
)
from scripts.agent_os_execution_capabilities.approved_projection import (
    GovernedProjectionEvidenceResult,
)
from scripts.agent_os_execution_capabilities.models import (
    RepositoryEvidenceType,
    RepositoryIdentity,
)
from scripts.agent_os_remote_validation.advisory_gate import (
    evaluate_advisory_pre_pr_evidence,
)
from scripts.agent_os_remote_validation.evidence_bundle import (
    build_validation_evidence_bundle,
    serialize_validation_evidence_bundle,
)
from scripts.agent_os_remote_validation.models import ValidationPlan
from scripts.agent_os_remote_validation.selector import (
    compute_command_set_digest,
    validation_plan_id,
)

HANDOFF_ID = "executor-handoff:" + "a" * 64
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
FINGERPRINT = "3" * 64
INVOCATION_ID = "invocation:test"


def _validation_fixture():
    identity = RepositoryIdentity(
        host="github.com", owner="Blummer92", repository="agent-os"
    )
    plan = ValidationPlan(
        selector_version="1.0.0",
        repository="Blummer92/agent-os",
        pull_request=1,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        profile="static",
        commands=(),
        command_set_digest=compute_command_set_digest("1.0.0", ()),
        reason_codes=("profile.documentation-static",),
        remote_build_required=False,
    )
    plan_id = validation_plan_id(plan)
    projection = GovernedProjectionEvidenceResult(
        status="accepted",
        schema_version="1.0",
        projection_id="projection:test",
        proposal_id="proposal:test",
        approval_id="approval:test",
        repository_identity=identity,
        base_branch="main",
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        evaluated_sha=BASE_SHA,
        tested_sha=HEAD_SHA,
        repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        repository_state_evidence_id="repository-state:test",
        implementation_contract_fingerprint=FINGERPRINT,
        reason_codes=(),
        details=(),
    )
    expectations = dict(
        expected_repository=identity,
        expected_pull_request=1,
        expected_base_branch="main",
        expected_base_sha=BASE_SHA,
        expected_source_head_sha=HEAD_SHA,
        expected_tested_sha=HEAD_SHA,
        expected_repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        expected_projection_id="projection:test",
        expected_proposal_id="proposal:test",
        expected_approval_id="approval:test",
        expected_repository_state_evidence_id="repository-state:test",
        expected_implementation_contract_fingerprint=FINGERPRINT,
        expected_selector_version="1.0.0",
        expected_profile="static",
        expected_command_set_digest=plan.command_set_digest,
        expected_plan_id=plan_id,
        runner_id="runner:test",
        invocation_id=INVOCATION_ID,
        started_at="2026-08-21T12:00:00Z",
        completed_at="2026-08-21T12:00:01Z",
    )
    bundle = build_validation_evidence_bundle(projection, plan, (), **expectations)
    advisory = evaluate_advisory_pre_pr_evidence(
        projection,
        plan,
        (),
        current_base_sha=BASE_SHA,
        current_source_head_sha=HEAD_SHA,
        expected_bundle_id=bundle.bundle_id,
        **expectations,
    )
    payload = serialize_validation_evidence_bundle(bundle)
    descriptor = SimpleNamespace(
        invocation_id=INVOCATION_ID,
        repository="Blummer92/agent-os",
        source_sha=HEAD_SHA,
    )
    capsule = SimpleNamespace(
        validation_plan_id=plan_id,
        validation_bundle_id=bundle.bundle_id,
        advisory_result_id=advisory.result_id,
        validation_bundle_payload=lambda: payload,
    )
    return descriptor, capsule, advisory


def test_rebuild_advisory_uses_canonical_bundle_and_expected_identity():
    descriptor, capsule, expected = _validation_fixture()

    rebuilt = _rebuild_advisory_result(descriptor, capsule)

    assert rebuilt == expected
    assert rebuilt.status == "passed"
    assert rebuilt.result_id == capsule.advisory_result_id


def test_rebuild_advisory_fails_closed_on_capsule_identity_drift():
    descriptor, capsule, _ = _validation_fixture()
    capsule.advisory_result_id = "advisory-evidence:" + "f" * 64

    with pytest.raises(
        ProductionGovernedResumeFactoryError,
        match="rebuilt advisory identity",
    ):
        _rebuild_advisory_result(descriptor, capsule)


def test_factory_consumes_canonical_runtime_request_into_1319(monkeypatch, tmp_path):
    descriptor = SimpleNamespace(
        handoff_id=HANDOFF_ID,
        repository="Blummer92/agent-os",
        issue_number=1217,
        candidate_packet_id="candidate-packet:test",
        invocation_id=INVOCATION_ID,
        source_sha=HEAD_SHA,
        required_environment_id="required-environment:test",
        dependency_readiness_evidence_id="dependency-readiness:test",
    )
    packet = SimpleNamespace(
        packet_id=descriptor.candidate_packet_id,
        repository=descriptor.repository,
        issue_number=descriptor.issue_number,
        invocation_id=descriptor.invocation_id,
        candidate_sha=descriptor.source_sha,
    )
    spec = SimpleNamespace(required_environment_id=descriptor.required_environment_id)
    capsule = SimpleNamespace(
        handoff_id=HANDOFF_ID,
        candidate_packet=packet,
        required_environment_spec=spec,
        validation_plan_id="validation-plan:test",
    )
    request = SimpleNamespace(invocation_descriptor=descriptor, restart_capsule=capsule)
    loaded = SimpleNamespace(request=request, source="runtime-execution-request")
    configuration = SimpleNamespace(checkpoint_store_root=tmp_path)
    readiness = object()
    advisory = object()
    transport = object()
    verifier = object()
    bindings = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(factory, "load_production_host_configuration", lambda: configuration)
    monkeypatch.setattr(factory, "canonical_evaluated_at", lambda: "2026-08-21T12:00:00Z")

    def load_runtime(root, handoff):
        captured["runtime_load"] = (root, handoff)
        return loaded

    monkeypatch.setattr(factory, "load_runtime_execution_request_or_legacy", load_runtime)
    monkeypatch.setattr(factory, "_bind_descriptor_and_capsule", lambda *args: None)
    monkeypatch.setattr(factory, "load_dependency_readiness", lambda root, identity: readiness)
    monkeypatch.setattr(factory, "_rebuild_advisory_result", lambda *args: advisory)
    monkeypatch.setattr(
        factory,
        "LiveRepositoryEvidenceReader",
        lambda **kwargs: captured.setdefault("reader_kwargs", kwargs) or object(),
    )
    monkeypatch.setattr(
        factory,
        "build_host_github_read_transport_from_environment",
        lambda: transport,
    )
    monkeypatch.setattr(factory, "build_subprocess_verifier_runner", lambda: verifier)

    class _Bootstrap:
        def governed_resume_bindings(self, *, cancelled):
            captured["cancelled"] = cancelled
            return bindings

    def build_bootstrap(**kwargs):
        captured["bootstrap_kwargs"] = kwargs
        return _Bootstrap()

    monkeypatch.setattr(factory, "build_production_host_bootstrap", build_bootstrap)

    result = build_production_governed_resume_bindings_for_handoff(HANDOFF_ID)

    assert result is bindings
    assert captured["runtime_load"] == (tmp_path, HANDOFF_ID)
    reader_kwargs = captured["reader_kwargs"]
    assert reader_kwargs["repository"] == descriptor.repository
    assert reader_kwargs["issue_number"] == descriptor.issue_number
    assert reader_kwargs["dependency_readiness"] is readiness
    assert reader_kwargs["validation_result"] is advisory
    assert reader_kwargs["expected_validation_plan_id"] == capsule.validation_plan_id
    bootstrap_kwargs = captured["bootstrap_kwargs"]
    assert bootstrap_kwargs["issue_transport"] is transport
    assert bootstrap_kwargs["authorization_transport"] is transport
    assert bootstrap_kwargs["run_verifier"] is verifier
    assert bootstrap_kwargs["runtime_request"] is request
    assert captured["cancelled"]() is False


def test_factory_fails_closed_when_canonical_or_legacy_runtime_load_fails(
    monkeypatch, tmp_path
):
    configuration = SimpleNamespace(checkpoint_store_root=tmp_path)
    monkeypatch.setattr(factory, "load_production_host_configuration", lambda: configuration)
    monkeypatch.setattr(factory, "canonical_evaluated_at", lambda: "2026-08-21T12:00:00Z")

    def fail_load(root, handoff):
        raise ValueError("canonical runtime request integrity failure")

    monkeypatch.setattr(factory, "load_runtime_execution_request_or_legacy", fail_load)

    with pytest.raises(
        ProductionGovernedResumeFactoryError,
        match="production governed-resume composition failed closed",
    ):
        build_production_governed_resume_bindings_for_handoff(HANDOFF_ID)
