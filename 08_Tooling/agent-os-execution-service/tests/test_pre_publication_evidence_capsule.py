from __future__ import annotations

import ast
import inspect
import json
from dataclasses import asdict, dataclass, replace

import pytest

import agent_os_execution_service.pre_publication_evidence_capsule as capsule_module
import agent_os_execution_service.pre_publication_evidence_store as store_module
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from scripts.agent_os_execution_checkpoint.store import CheckpointStoreIntegrityConflict
from scripts.agent_os_issue_acceptance.approval_records import ApprovalState


@dataclass(frozen=True)
class FakePacket:
    phase: CandidatePacketPhase
    repository: str
    issue_number: int
    invocation_id: str
    candidate_ref: str
    base_branch: str
    base_sha: str
    candidate_sha: str
    source_sha: str
    tested_sha: str
    stage_identities: tuple[tuple[str, str], ...]
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_tests: tuple[str, ...]
    evidence_completeness: str = "complete"
    disposition: str = "verified"


@dataclass(frozen=True)
class FakeBinding:
    repository: str
    base_branch: str
    evaluated_repository_sha: str
    tested_repository_sha: str
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_tests: tuple[str, ...]


@dataclass(frozen=True)
class FakeApproval:
    approval_id: str
    approval_revision: str
    state: ApprovalState
    binding: FakeBinding


@dataclass(frozen=True)
class FakeSpec:
    required_validation_command_ids: tuple[str, ...]


@dataclass(frozen=True)
class FakeCheckpoint:
    checkpoint_id: str
    repository: str
    issue_number: int
    invocation_id: str
    execution_id: str
    branch: str
    source_sha: str
    tested_sha: str


def _patch_nested_transports(monkeypatch):
    monkeypatch.setattr(capsule_module, "CandidatePacket", FakePacket)
    monkeypatch.setattr(capsule_module, "ApprovalRecord", FakeApproval)
    monkeypatch.setattr(capsule_module, "RequiredEnvironmentSpec", FakeSpec)
    monkeypatch.setattr(capsule_module, "ExecutionCheckpoint", FakeCheckpoint)
    monkeypatch.setattr(capsule_module, "serialize_candidate_packet", lambda value: asdict(value) | {"phase": value.phase.value})
    monkeypatch.setattr(capsule_module, "deserialize_candidate_packet", lambda value: FakePacket(**{**value, "phase": CandidatePacketPhase(value["phase"]), "stage_identities": tuple(tuple(x) for x in value["stage_identities"]), "allowed_files": tuple(value["allowed_files"]), "forbidden_paths": tuple(value["forbidden_paths"]), "required_tests": tuple(value["required_tests"])}))
    monkeypatch.setattr(capsule_module, "serialize_approval_record", lambda value: json.dumps({"approval_id": value.approval_id, "approval_revision": value.approval_revision, "state": value.state.value, "binding": asdict(value.binding)}, default=list))
    monkeypatch.setattr(capsule_module, "reconstruct_approval_record", lambda value: FakeApproval(value["approval_id"], value["approval_revision"], ApprovalState(value["state"]), FakeBinding(**{**value["binding"], "allowed_files": tuple(value["binding"]["allowed_files"]), "forbidden_paths": tuple(value["binding"]["forbidden_paths"]), "required_tests": tuple(value["binding"]["required_tests"])})))
    monkeypatch.setattr(capsule_module, "required_environment_spec_payload", lambda value: {"required_validation_command_ids": list(value.required_validation_command_ids)})
    monkeypatch.setattr(capsule_module, "reconstruct_required_environment_spec", lambda value: FakeSpec(tuple(value["required_validation_command_ids"])))


def _bundle_json(bundle_id: str) -> str:
    return json.dumps({"bundle_id": bundle_id, "base_sha": "a" * 40, "source_head_sha": "b" * 40, "tested_sha": "c" * 40, "invocation_id": "invocation-1799", "approval_id": "approval:" + "d" * 64, "plan_id": "validation-plan:" + "e" * 64, "authoritative": False, "execution_authorized": False, "merge_authorized": False, "attestation_verified": False, "side_effects_performed": False}, sort_keys=True, separators=(",", ":"))


def _capsule(monkeypatch, *, version="1.1", phase="source", checkpoint_id=None, execution_id="execution-1799", **overrides):
    _patch_nested_transports(monkeypatch)
    approval_id = "approval:" + "d" * 64
    revision = "approval-revision:" + "f" * 64
    packet = FakePacket(CandidatePacketPhase.EXECUTION_CANDIDATE, "Blummer92/agent-os", 1799, "invocation-1799", "agent/1799-pre-publication-two-phase-envelope", "main", "a" * 40, "b" * 40, "b" * 40, "c" * 40, (("approval-decision", f"{approval_id}@{revision}"),), ("08_Tooling/agent-os-execution-service",), (".github/workflows",), ("pytest-focused",))
    approval = FakeApproval(approval_id, revision, ApprovalState.APPROVED, FakeBinding(packet.repository, packet.base_branch, packet.candidate_sha, packet.tested_sha, packet.allowed_files, packet.forbidden_paths, packet.required_tests))
    values = dict(schema_name=capsule_module.CAPSULE_SCHEMA_NAME, schema_version=version, candidate_packet=packet, approval_record=approval, required_environment_spec=FakeSpec(packet.required_tests), validation_bundle_json=_bundle_json("validation-bundle:" + "1" * 64), validation_plan_id="validation-plan:" + "e" * 64, validation_bundle_id="validation-bundle:" + "1" * 64, advisory_result_id="advisory-result:" + "2" * 64, advisory_render_id="advisory-render:" + "3" * 64, candidate_branch=packet.candidate_ref, workspace_request_id="workspace-request:1799", invalidation_events=(), checkpoint_id=checkpoint_id, created_at="2026-09-03T14:00:00Z", expires_at="2026-09-03T15:00:00Z", evaluated_at="2026-09-03T14:10:00Z", phase=phase, execution_id=execution_id)
    values.update(overrides)
    return capsule_module.PrePublicationEvidenceCapsule(**values)


def _checkpoint(capsule, **overrides):
    values = dict(checkpoint_id="agent-os.execution-checkpoint:" + "4" * 64, repository=capsule.candidate_packet.repository, issue_number=capsule.candidate_packet.issue_number, invocation_id=capsule.candidate_packet.invocation_id, execution_id=capsule.execution_id, branch=capsule.candidate_branch, source_sha=capsule.candidate_packet.candidate_sha, tested_sha=capsule.candidate_packet.tested_sha)
    values.update(overrides)
    return FakeCheckpoint(**values)


def test_source_phase_round_trip_is_deterministic_and_non_authorizing(monkeypatch):
    source = _capsule(monkeypatch)
    rebuilt = capsule_module.deserialize_pre_publication_evidence(capsule_module.serialize_pre_publication_evidence(source))
    assert rebuilt == source
    assert rebuilt.checkpoint_id is None
    assert rebuilt.phase == capsule_module.SOURCE_PHASE
    assert rebuilt.execution_authorized is False
    assert rebuilt.publication_authorized is False
    assert rebuilt.merge_authorized is False
    assert rebuilt.external_writes_authorized is False


def test_source_phase_rejects_checkpoint_and_tamper(monkeypatch):
    with pytest.raises(ValueError, match="must not carry checkpoint"):
        _capsule(monkeypatch, checkpoint_id="agent-os.execution-checkpoint:" + "4" * 64)
    source = _capsule(monkeypatch)
    payload = json.loads(capsule_module.serialize_pre_publication_evidence(source))
    payload["workspace_request_id"] = "tampered"
    with pytest.raises(ValueError, match="capsule_id"):
        capsule_module.deserialize_pre_publication_evidence(json.dumps(payload))


def test_bind_source_to_checkpoint_is_deterministic_and_preserves_evidence(monkeypatch):
    source = _capsule(monkeypatch)
    checkpoint = _checkpoint(source)
    first = capsule_module.bind_source_capsule_to_checkpoint(source, checkpoint)
    second = capsule_module.bind_source_capsule_to_checkpoint(source, checkpoint)
    assert first == second
    assert first.phase == capsule_module.CHECKPOINT_BOUND_PHASE
    assert first.checkpoint_id == checkpoint.checkpoint_id
    assert first.candidate_packet == source.candidate_packet
    assert first.approval_record == source.approval_record
    assert first.required_environment_spec == source.required_environment_spec
    assert first.validation_bundle_json == source.validation_bundle_json
    assert first.workspace_request_id == source.workspace_request_id
    assert first.invalidation_events == source.invalidation_events


@pytest.mark.parametrize("field,value", [("repository", "other/repo"), ("issue_number", 999), ("invocation_id", "other"), ("execution_id", "other"), ("branch", "other"), ("source_sha", "9" * 40), ("tested_sha", "8" * 40)])
def test_bind_source_rejects_checkpoint_binding_drift(monkeypatch, field, value):
    source = _capsule(monkeypatch)
    with pytest.raises(ValueError, match="does not bind"):
        capsule_module.bind_source_capsule_to_checkpoint(source, _checkpoint(source, **{field: value}))


def test_legacy_v1_round_trip_and_identity_remain_valid(monkeypatch):
    legacy = _capsule(monkeypatch, version="1.0", phase="checkpoint-bound", checkpoint_id="agent-os.execution-checkpoint:" + "4" * 64, execution_id=None)
    payload = capsule_module.serialize_pre_publication_evidence(legacy)
    decoded = json.loads(payload)
    assert "phase" not in decoded
    assert "execution_id" not in decoded
    assert capsule_module.deserialize_pre_publication_evidence(payload) == legacy
    assert legacy.capsule_id.startswith("pre-publication-evidence:")


def test_future_version_and_phase_fail_closed(monkeypatch):
    source = _capsule(monkeypatch)
    payload = json.loads(capsule_module.serialize_pre_publication_evidence(source))
    payload["schema_version"] = "9.0"
    with pytest.raises(ValueError, match="unsupported"):
        capsule_module.deserialize_pre_publication_evidence(json.dumps(payload))
    with pytest.raises(ValueError, match="phase"):
        _capsule(monkeypatch, phase="future")


def test_source_store_is_idempotent_and_publication_loader_rejects_it(tmp_path, monkeypatch):
    source = _capsule(monkeypatch)
    first = store_module.append_pre_publication_evidence(tmp_path, source)
    second = store_module.append_pre_publication_evidence(tmp_path, source)
    assert first.already_present is False
    assert second.already_present is True
    assert store_module.load_source_pre_publication_evidence(tmp_path, source.capsule_id) == source
    with pytest.raises(CheckpointStoreIntegrityConflict, match="not publishable"):
        store_module.load_pre_publication_evidence(tmp_path, source.capsule_id)


def test_checkpoint_bound_store_requires_matching_durable_checkpoint(tmp_path, monkeypatch):
    source = _capsule(monkeypatch)
    checkpoint = _checkpoint(source)
    bound = capsule_module.bind_source_capsule_to_checkpoint(source, checkpoint)
    monkeypatch.setattr(store_module, "load_checkpoint_by_id", lambda *_args: checkpoint)
    first = store_module.append_pre_publication_evidence(tmp_path, bound)
    assert store_module.load_pre_publication_evidence(tmp_path, bound.capsule_id) == bound
    monkeypatch.setattr(store_module, "load_checkpoint_by_id", lambda *_args: replace(checkpoint, source_sha="9" * 40))
    with pytest.raises(CheckpointStoreIntegrityConflict, match="does not bind"):
        store_module.append_pre_publication_evidence(tmp_path, replace(bound, capsule_id=""))
    assert first.path.parent.name == store_module.STORE_NAMESPACE


def test_no_second_store_or_external_authority_surface():
    capsule_source = inspect.getsource(capsule_module)
    store_source = inspect.getsource(store_module)
    assert store_module.STORE_NAMESPACE == "pre-publication-producer-evidence"
    assert "SingleIssuePilotInput" in capsule_source
    assert "serialize_single_issue_pilot" not in capsule_source
    assert "serialize_single_issue_pilot" not in store_source
    for source in (capsule_source, store_source):
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not [name for name in imports if name.startswith(("subprocess", "requests", "httpx", "github", "google.cloud", "paramiko"))]
        for banned in ("Scheduler(", "acquire_lease", "execution_authorized=True", "publication_authorized=True"):
            assert banned not in source
