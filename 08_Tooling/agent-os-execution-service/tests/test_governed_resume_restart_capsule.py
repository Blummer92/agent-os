from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

import agent_os_execution_service.governed_resume_restart_capsule as capsule_module
from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyArtifactIdentity,
    DependencyEcosystem,
    DependencyInstallMode,
    RequiredEnvironmentSpec,
)
from scripts.agent_os_execution_checkpoint.store import CheckpointStoreIntegrityConflict

_REQUIRED_TESTS = ("pytest-focused", "structural")


def _required_environment_spec(
    *, manifest_sha: str = "a" * 64, command_ids: tuple[str, ...] = _REQUIRED_TESTS
) -> RequiredEnvironmentSpec:
    return RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
        runtime_requirement="python>=3.11",
        dependency_manifest_identity=DependencyArtifactIdentity(
            relative_path="requirements-dev.txt", sha256=manifest_sha
        ),
        lock_or_constraints_identity=DependencyArtifactIdentity(
            relative_path="constraints.txt", sha256="b" * 64
        ),
        install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity="pypi.org/simple",
        required_validation_command_ids=tuple(sorted(command_ids)),
    )


@dataclass(frozen=True)
class FakeCandidatePacket:
    packet_id: str
    label: str


@dataclass(frozen=True)
class FakeApprovalRecord:
    approval_id: str


def _patch_nested_transports(monkeypatch):
    monkeypatch.setattr(capsule_module, "CandidatePacket", FakeCandidatePacket)
    monkeypatch.setattr(capsule_module, "ApprovalRecord", FakeApprovalRecord)
    monkeypatch.setattr(
        capsule_module,
        "serialize_candidate_packet",
        lambda value: {"packet_id": value.packet_id, "label": value.label},
    )
    monkeypatch.setattr(
        capsule_module,
        "deserialize_candidate_packet",
        lambda value: FakeCandidatePacket(value["packet_id"], value["label"]),
    )
    monkeypatch.setattr(
        capsule_module,
        "serialize_approval_record",
        lambda value: json.dumps({"approval_id": value.approval_id}),
    )
    monkeypatch.setattr(
        capsule_module,
        "reconstruct_approval_record",
        lambda value: FakeApprovalRecord(value["approval_id"]),
    )


def _bundle_json(bundle_id: str) -> str:
    return json.dumps(
        {
            "bundle_id": bundle_id,
            "authoritative": False,
            "execution_authorized": False,
            "merge_authorized": False,
            "attestation_verified": False,
            "side_effects_performed": False,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _capsule(monkeypatch):
    _patch_nested_transports(monkeypatch)
    return capsule_module.GovernedResumeRestartCapsule(
        schema_name=capsule_module.CAPSULE_SCHEMA_NAME,
        schema_version=capsule_module.CAPSULE_SCHEMA_VERSION,
        handoff_id="executor-handoff:" + "a" * 64,
        candidate_packet=FakeCandidatePacket("candidate-packet:" + "b" * 64, "current"),
        approval_record=FakeApprovalRecord("approval:" + "c" * 64),
        required_environment_spec=_required_environment_spec(),
        validation_bundle_json=_bundle_json("validation-evidence-bundle:" + "d" * 64),
        validation_plan_id="validation-plan:" + "e" * 64,
        validation_bundle_id="validation-evidence-bundle:" + "d" * 64,
        advisory_result_id="advisory-evidence:" + "f" * 64,
        advisory_render_id="advisory-render:" + "1" * 64,
        candidate_branch="agent/1303-test",
        workspace_request_id="workspace-request:test",
        invalidation_events=(),
        created_at="2026-08-20T20:00:00Z",
        expires_at="2026-08-20T22:00:00Z",
        evaluated_at="2026-08-20T20:30:00Z",
    )


def test_restart_capsule_round_trips_and_is_idempotent(tmp_path, monkeypatch):
    capsule = _capsule(monkeypatch)
    first = capsule_module.append_restart_capsule(tmp_path, capsule)
    second = capsule_module.append_restart_capsule(tmp_path, capsule)
    loaded = capsule_module.load_restart_capsule(tmp_path, capsule.handoff_id)

    assert first.capsule_id == capsule.capsule_id
    assert first.already_present is False
    assert second.already_present is True
    assert loaded == capsule
    assert loaded.execution_authorized is False
    assert loaded.github_writes_authorized is False
    assert loaded.merge_authorized is False
    assert loaded.issue_closure_authorized is False
    assert loaded.external_writes_authorized is False


def test_restart_capsule_tamper_fails_closed(tmp_path, monkeypatch):
    capsule = _capsule(monkeypatch)
    outcome = capsule_module.append_restart_capsule(tmp_path, capsule)
    payload = json.loads(outcome.path.read_text())
    payload["candidate_packet"]["label"] = "tampered"
    outcome.path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))

    with pytest.raises(CheckpointStoreIntegrityConflict):
        capsule_module.load_restart_capsule(tmp_path, capsule.handoff_id)


def test_restart_capsule_rejects_authority_in_validation_payload(monkeypatch):
    _patch_nested_transports(monkeypatch)
    bundle = json.loads(_bundle_json("validation-evidence-bundle:" + "d" * 64))
    bundle["execution_authorized"] = True
    with pytest.raises(ValueError, match="execution_authorized"):
        capsule_module.GovernedResumeRestartCapsule(
            schema_name=capsule_module.CAPSULE_SCHEMA_NAME,
            schema_version=capsule_module.CAPSULE_SCHEMA_VERSION,
            handoff_id="executor-handoff:" + "a" * 64,
            candidate_packet=FakeCandidatePacket("candidate-packet:" + "b" * 64, "current"),
            approval_record=FakeApprovalRecord("approval:" + "c" * 64),
            required_environment_spec=_required_environment_spec(),
            validation_bundle_json=json.dumps(bundle),
            validation_plan_id="validation-plan:" + "e" * 64,
            validation_bundle_id="validation-evidence-bundle:" + "d" * 64,
            advisory_result_id="advisory-evidence:" + "f" * 64,
            advisory_render_id="advisory-render:" + "1" * 64,
            candidate_branch="agent/1303-test",
            workspace_request_id="workspace-request:test",
            invalidation_events=(),
            created_at="2026-08-20T20:00:00Z",
            expires_at="2026-08-20T22:00:00Z",
            evaluated_at="2026-08-20T20:30:00Z",
        )


def _descriptor(**overrides):
    fields = {
        "schema_name": "agent-os.governed-invocation-descriptor",
        "schema_version": "1.0",
        "repository": "Blummer92/agent-os",
        "issue_number": 1320,
        "issue_or_handoff_identity": "issue:1320",
        "handoff_id": "executor-handoff:" + "a" * 64,
        "route_decision_id": "route-decision:" + "2" * 64,
        "execution_service_request_fingerprint": "request:" + "3" * 64,
        "authorization_id": "authorization:" + "4" * 64,
        "source_ref": "refs/heads/agent/1320-structured-evidence-spec",
        "source_sha": "5" * 40,
        "checkpoint_id": "checkpoint:" + "6" * 64,
        "resume_plan_id": "resume-plan:" + "7" * 64,
        "environment_profile_id": "environment-profile:" + "8" * 64,
        "environment_health_evidence_id": "environment-health:" + "9" * 64,
        "required_environment_id": _required_environment_spec().required_environment_id,
        "dependency_readiness_evidence_id": "dependency-readiness:" + "0" * 64,
        "execution_surface_id": "execution-surface:test",
        "workspace_identity": "workspace:test",
        "workflow_runtime_identity": "workflow-runtime:test",
        "candidate_packet_id": "candidate-packet:" + "b" * 64,
        "runtime_configuration_fingerprint": "runtime-configuration:" + "c" * 64,
        "execution_id": "execution:" + "d" * 64,
        "invocation_id": "invocation:" + "e" * 64,
    }
    fields.update(overrides)
    return capsule_module.GovernedInvocationDescriptor(**fields)


# --- AOS-GCE2F (#1320) required-environment persistence/recovery ---------------


def test_persisted_spec_round_trips_through_the_canonical_model(tmp_path, monkeypatch):
    capsule = _capsule(monkeypatch)
    capsule_module.append_restart_capsule(tmp_path, capsule)

    loaded = capsule_module.load_restart_capsule(tmp_path, capsule.handoff_id)

    spec = loaded.required_environment_spec
    assert type(spec) is RequiredEnvironmentSpec
    assert spec == capsule.required_environment_spec
    assert (
        spec.required_environment_id
        == capsule.required_environment_spec.required_environment_id
    )


def test_capsule_identity_changes_when_the_required_environment_changes(monkeypatch):
    baseline = _capsule(monkeypatch)
    changed = _required_environment_spec(manifest_sha="f" * 64)

    assert (
        changed.required_environment_id
        != baseline.required_environment_spec.required_environment_id
    )
    other = capsule_module.GovernedResumeRestartCapsule(
        schema_name=baseline.schema_name,
        schema_version=baseline.schema_version,
        handoff_id=baseline.handoff_id,
        candidate_packet=baseline.candidate_packet,
        approval_record=baseline.approval_record,
        required_environment_spec=changed,
        validation_bundle_json=baseline.validation_bundle_json,
        validation_plan_id=baseline.validation_plan_id,
        validation_bundle_id=baseline.validation_bundle_id,
        advisory_result_id=baseline.advisory_result_id,
        advisory_render_id=baseline.advisory_render_id,
        candidate_branch=baseline.candidate_branch,
        workspace_request_id=baseline.workspace_request_id,
        invalidation_events=baseline.invalidation_events,
        created_at=baseline.created_at,
        expires_at=baseline.expires_at,
        evaluated_at=baseline.evaluated_at,
    )
    assert other.capsule_id != baseline.capsule_id


def test_capsule_rejects_a_non_canonical_required_environment(monkeypatch):
    _patch_nested_transports(monkeypatch)
    with pytest.raises(TypeError, match="required_environment_spec"):
        capsule_module.GovernedResumeRestartCapsule(
            schema_name=capsule_module.CAPSULE_SCHEMA_NAME,
            schema_version=capsule_module.CAPSULE_SCHEMA_VERSION,
            handoff_id="executor-handoff:" + "a" * 64,
            candidate_packet=FakeCandidatePacket("candidate-packet:" + "b" * 64, "current"),
            approval_record=FakeApprovalRecord("approval:" + "c" * 64),
            required_environment_spec={"required_environment_id": "required-environment:x"},
            validation_bundle_json=_bundle_json("validation-evidence-bundle:" + "d" * 64),
            validation_plan_id="validation-plan:" + "e" * 64,
            validation_bundle_id="validation-evidence-bundle:" + "d" * 64,
            advisory_result_id="advisory-evidence:" + "f" * 64,
            advisory_render_id="advisory-render:" + "1" * 64,
            candidate_branch="agent/1320-test",
            workspace_request_id="workspace-request:test",
            invalidation_events=(),
            created_at="2026-08-20T20:00:00Z",
            expires_at="2026-08-20T22:00:00Z",
            evaluated_at="2026-08-20T20:30:00Z",
        )


def test_tampered_spec_payload_fails_closed(tmp_path, monkeypatch):
    capsule = _capsule(monkeypatch)
    outcome = capsule_module.append_restart_capsule(tmp_path, capsule)
    payload = json.loads(outcome.path.read_text())
    payload["required_environment_spec"]["runtime_requirement"] = "python>=3.13"
    outcome.path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))

    with pytest.raises(CheckpointStoreIntegrityConflict):
        capsule_module.load_restart_capsule(tmp_path, capsule.handoff_id)


def test_spec_payload_field_drift_fails_closed(tmp_path, monkeypatch):
    capsule = _capsule(monkeypatch)
    outcome = capsule_module.append_restart_capsule(tmp_path, capsule)
    payload = json.loads(outcome.path.read_text())
    del payload["required_environment_spec"]["approved_source_identity"]
    outcome.path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))

    with pytest.raises(CheckpointStoreIntegrityConflict):
        capsule_module.load_restart_capsule(tmp_path, capsule.handoff_id)


def test_reader_returns_the_exact_spec_the_descriptor_asserts(tmp_path, monkeypatch):
    capsule = _capsule(monkeypatch)
    capsule_module.append_restart_capsule(tmp_path, capsule)
    read = capsule_module.build_required_environment_spec_reader(tmp_path)

    spec = read(_descriptor())

    assert spec == capsule.required_environment_spec


def test_reader_fails_closed_on_a_mismatched_environment_identity(tmp_path, monkeypatch):
    capsule = _capsule(monkeypatch)
    capsule_module.append_restart_capsule(tmp_path, capsule)
    read = capsule_module.build_required_environment_spec_reader(tmp_path)
    descriptor = _descriptor(
        required_environment_id=_required_environment_spec(
            manifest_sha="f" * 64
        ).required_environment_id
    )

    with pytest.raises(CheckpointStoreIntegrityConflict):
        read(descriptor)


def test_reader_fails_closed_when_no_capsule_is_persisted(tmp_path):
    read = capsule_module.build_required_environment_spec_reader(tmp_path)

    with pytest.raises(capsule_module.RestartCapsuleNotFound):
        read(_descriptor())


def test_reader_requires_an_exact_descriptor(tmp_path):
    read = capsule_module.build_required_environment_spec_reader(tmp_path)

    with pytest.raises(TypeError, match="GovernedInvocationDescriptor"):
        read({"handoff_id": "executor-handoff:" + "a" * 64})


def test_recovered_spec_is_declarative_and_carries_no_readiness_or_authority(
    tmp_path, monkeypatch
):
    capsule = _capsule(monkeypatch)
    capsule_module.append_restart_capsule(tmp_path, capsule)
    spec = capsule_module.build_required_environment_spec_reader(tmp_path)(_descriptor())

    for name in (
        "preparation_status",
        "cache_state",
        "resolved_dependency_identity",
        "observed_at",
        "expires_at",
        "execution_authorized",
        "dependency_readiness_evidence_id",
    ):
        assert not hasattr(spec, name), f"spec must not carry runtime readiness {name}"
    loaded = capsule_module.load_restart_capsule(tmp_path, capsule.handoff_id)
    assert loaded.execution_authorized is False
    assert loaded.repository_implementation_authorized is False
    assert loaded.merge_authorized is False
    assert loaded.external_writes_authorized is False
