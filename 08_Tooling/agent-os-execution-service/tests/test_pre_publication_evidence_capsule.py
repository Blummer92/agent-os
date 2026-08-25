from __future__ import annotations

import ast
import inspect
import json
from dataclasses import asdict, dataclass, replace
from types import SimpleNamespace

import pytest

import agent_os_execution_service.pre_publication_evidence_capsule as capsule_module
import agent_os_execution_service.pre_publication_evidence_store as store_module
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from scripts.agent_os_issue_acceptance.approval_records import ApprovalState
from scripts.agent_os_execution_checkpoint.store import (
    CheckpointNotFound,
    CheckpointStoreIntegrityConflict,
)


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


def _patch_nested_transports(monkeypatch):
    monkeypatch.setattr(capsule_module, "CandidatePacket", FakePacket)
    monkeypatch.setattr(capsule_module, "ApprovalRecord", FakeApproval)
    monkeypatch.setattr(capsule_module, "RequiredEnvironmentSpec", FakeSpec)
    monkeypatch.setattr(
        capsule_module,
        "serialize_candidate_packet",
        lambda value: {
            "phase": value.phase.value,
            "repository": value.repository,
            "issue_number": value.issue_number,
            "invocation_id": value.invocation_id,
            "candidate_ref": value.candidate_ref,
            "base_branch": value.base_branch,
            "base_sha": value.base_sha,
            "candidate_sha": value.candidate_sha,
            "source_sha": value.source_sha,
            "tested_sha": value.tested_sha,
            "stage_identities": [list(item) for item in value.stage_identities],
            "allowed_files": list(value.allowed_files),
            "forbidden_paths": list(value.forbidden_paths),
            "required_tests": list(value.required_tests),
            "evidence_completeness": value.evidence_completeness,
            "disposition": value.disposition,
        },
    )
    monkeypatch.setattr(
        capsule_module,
        "deserialize_candidate_packet",
        lambda value: FakePacket(
            phase=CandidatePacketPhase(value["phase"]),
            repository=value["repository"],
            issue_number=value["issue_number"],
            invocation_id=value["invocation_id"],
            candidate_ref=value["candidate_ref"],
            base_branch=value["base_branch"],
            base_sha=value["base_sha"],
            candidate_sha=value["candidate_sha"],
            source_sha=value["source_sha"],
            tested_sha=value["tested_sha"],
            stage_identities=tuple(tuple(item) for item in value["stage_identities"]),
            allowed_files=tuple(value["allowed_files"]),
            forbidden_paths=tuple(value["forbidden_paths"]),
            required_tests=tuple(value["required_tests"]),
            evidence_completeness=value["evidence_completeness"],
            disposition=value["disposition"],
        ),
    )
    monkeypatch.setattr(
        capsule_module,
        "serialize_approval_record",
        lambda value: json.dumps(
            {
                "approval_id": value.approval_id,
                "approval_revision": value.approval_revision,
                "state": value.state.value,
                "binding": asdict(value.binding),
            },
            default=list,
        ),
    )
    monkeypatch.setattr(
        capsule_module,
        "reconstruct_approval_record",
        lambda value: FakeApproval(
            approval_id=value["approval_id"],
            approval_revision=value["approval_revision"],
            state=ApprovalState(value["state"]),
            binding=FakeBinding(
                **{
                    **value["binding"],
                    "allowed_files": tuple(value["binding"]["allowed_files"]),
                    "forbidden_paths": tuple(value["binding"]["forbidden_paths"]),
                    "required_tests": tuple(value["binding"]["required_tests"]),
                }
            ),
        ),
    )
    monkeypatch.setattr(
        capsule_module,
        "required_environment_spec_payload",
        lambda value: {
            "required_validation_command_ids": list(
                value.required_validation_command_ids
            )
        },
    )
    monkeypatch.setattr(
        capsule_module,
        "reconstruct_required_environment_spec",
        lambda value: FakeSpec(tuple(value["required_validation_command_ids"])),
    )


def _bundle_json(bundle_id: str, *, source_sha: str = "b" * 40) -> str:
    return json.dumps(
        {
            "bundle_id": bundle_id,
            "base_sha": "a" * 40,
            "source_head_sha": source_sha,
            "tested_sha": "c" * 40,
            "invocation_id": "invocation-1412",
            "approval_id": "approval:" + "d" * 64,
            "plan_id": "validation-plan:" + "e" * 64,
            "authoritative": False,
            "execution_authorized": False,
            "merge_authorized": False,
            "attestation_verified": False,
            "side_effects_performed": False,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _capsule(monkeypatch, **overrides):
    _patch_nested_transports(monkeypatch)
    approval_id = "approval:" + "d" * 64
    revision = "approval-revision:" + "f" * 64
    packet = FakePacket(
        phase=CandidatePacketPhase.EXECUTION_CANDIDATE,
        repository="Blummer92/agent-os",
        issue_number=1412,
        invocation_id="invocation-1412",
        candidate_ref="agent/1412-pre-publication-evidence-capsule",
        base_branch="main",
        base_sha="a" * 40,
        candidate_sha="b" * 40,
        source_sha="b" * 40,
        tested_sha="c" * 40,
        stage_identities=(("approval-decision", f"{approval_id}@{revision}"),),
        allowed_files=("08_Tooling/agent-os-execution-service",),
        forbidden_paths=(".github/workflows",),
        required_tests=("pytest-focused",),
    )
    approval = FakeApproval(
        approval_id=approval_id,
        approval_revision=revision,
        state=ApprovalState.APPROVED,
        binding=FakeBinding(
            repository=packet.repository,
            base_branch=packet.base_branch,
            evaluated_repository_sha=packet.candidate_sha,
            tested_repository_sha=packet.tested_sha,
            allowed_files=packet.allowed_files,
            forbidden_paths=packet.forbidden_paths,
            required_tests=packet.required_tests,
        ),
    )
    values = dict(
        schema_name=capsule_module.CAPSULE_SCHEMA_NAME,
        schema_version=capsule_module.CAPSULE_SCHEMA_VERSION,
        candidate_packet=packet,
        approval_record=approval,
        required_environment_spec=FakeSpec(packet.required_tests),
        validation_bundle_json=_bundle_json("validation-bundle:" + "1" * 64),
        validation_plan_id="validation-plan:" + "e" * 64,
        validation_bundle_id="validation-bundle:" + "1" * 64,
        advisory_result_id="advisory-result:" + "2" * 64,
        advisory_render_id="advisory-render:" + "3" * 64,
        candidate_branch=packet.candidate_ref,
        workspace_request_id="workspace-request:1412",
        invalidation_events=(),
        checkpoint_id="agent-os.execution-checkpoint:" + "4" * 64,
        created_at="2026-08-25T23:00:00Z",
        expires_at="2026-08-26T00:00:00Z",
        evaluated_at="2026-08-25T23:10:00Z",
    )
    values.update(overrides)
    return capsule_module.PrePublicationEvidenceCapsule(**values)


def test_capsule_identity_round_trip_and_authority_are_deterministic(monkeypatch):
    capsule = _capsule(monkeypatch)
    duplicate = _capsule(monkeypatch)
    rebuilt = capsule_module.deserialize_pre_publication_evidence(
        capsule_module.serialize_pre_publication_evidence(capsule)
    )
    assert duplicate.capsule_id == capsule.capsule_id
    assert rebuilt == capsule
    assert rebuilt.execution_authorized is False
    assert rebuilt.publication_authorized is False
    assert rebuilt.merge_authorized is False
    assert rebuilt.external_writes_authorized is False


def test_capsule_rejects_future_schema_and_true_authority(monkeypatch):
    capsule = _capsule(monkeypatch)
    payload = json.loads(capsule_module.serialize_pre_publication_evidence(capsule))
    payload["schema_version"] = "9.0"
    with pytest.raises(ValueError, match="unsupported"):
        capsule_module.deserialize_pre_publication_evidence(json.dumps(payload))
    payload = json.loads(capsule_module.serialize_pre_publication_evidence(capsule))
    payload["publication_authorized"] = True
    with pytest.raises(ValueError, match="publication_authorized"):
        capsule_module.deserialize_pre_publication_evidence(json.dumps(payload))


def test_capsule_rejects_tampered_content_identity(monkeypatch):
    capsule = _capsule(monkeypatch)
    payload = json.loads(capsule_module.serialize_pre_publication_evidence(capsule))
    payload["workspace_request_id"] = "workspace-request:tampered"
    with pytest.raises(ValueError, match="capsule_id"):
        capsule_module.deserialize_pre_publication_evidence(json.dumps(payload))


def test_capsule_rejects_approval_and_validation_binding_drift(monkeypatch):
    baseline = _capsule(monkeypatch)
    bad_approval = replace(
        baseline.approval_record,
        binding=replace(
            baseline.approval_record.binding,
            tested_repository_sha="9" * 40,
        ),
    )
    with pytest.raises(ValueError, match="approval record"):
        _capsule(monkeypatch, approval_record=bad_approval)
    with pytest.raises(ValueError, match="validation bundle"):
        _capsule(
            monkeypatch,
            validation_bundle_json=_bundle_json(
                "validation-bundle:" + "1" * 64, source_sha="9" * 40
            ),
        )


def test_store_requires_exact_durable_checkpoint_before_write(tmp_path, monkeypatch):
    capsule = _capsule(monkeypatch)
    monkeypatch.setattr(
        store_module,
        "load_checkpoint_by_id",
        lambda *_args: (_ for _ in ()).throw(
            CheckpointNotFound(capsule.checkpoint_id)
        ),
    )
    with pytest.raises(CheckpointNotFound):
        store_module.append_pre_publication_evidence(tmp_path, capsule)
    assert not (tmp_path / store_module.STORE_NAMESPACE).exists()


def test_store_round_trip_is_idempotent_and_tamper_fails_closed(tmp_path, monkeypatch):
    capsule = _capsule(monkeypatch)
    durable = SimpleNamespace(
        checkpoint_id=capsule.checkpoint_id,
        repository=capsule.candidate_packet.repository,
        issue_number=capsule.candidate_packet.issue_number,
        invocation_id=capsule.candidate_packet.invocation_id,
        branch=capsule.candidate_branch,
        source_sha=capsule.candidate_packet.candidate_sha,
        tested_sha=capsule.candidate_packet.tested_sha,
    )
    monkeypatch.setattr(store_module, "load_checkpoint_by_id", lambda *_args: durable)
    first = store_module.append_pre_publication_evidence(tmp_path, capsule)
    second = store_module.append_pre_publication_evidence(tmp_path, capsule)
    assert first.already_present is False
    assert second.already_present is True
    assert (
        store_module.load_pre_publication_evidence(tmp_path, capsule.capsule_id)
        == capsule
    )
    payload = json.loads(first.path.read_text())
    payload["workspace_request_id"] = "workspace-request:tampered"
    first.path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    with pytest.raises(CheckpointStoreIntegrityConflict):
        store_module.load_pre_publication_evidence(tmp_path, capsule.capsule_id)


def test_exactly_one_persistence_owner_and_no_external_side_effect_surface():
    capsule_source = inspect.getsource(capsule_module)
    store_source = inspect.getsource(store_module)
    assert "def append_pre_publication_evidence" not in capsule_source
    assert "def load_pre_publication_evidence" not in capsule_source
    assert store_source.count("def append_pre_publication_evidence") == 1
    assert store_source.count("def load_pre_publication_evidence") == 1
    assert store_module.STORE_NAMESPACE == "pre-publication-producer-evidence"
    for source in (capsule_source, store_source):
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not [
            name
            for name in imports
            if name.startswith(
                ("subprocess", "requests", "httpx", "github", "google.cloud", "paramiko")
            )
        ]
        for banned in (
            "Scheduler(",
            "acquire_lease",
            "retry",
            "execution_authorized=True",
            "publication_authorized=True",
        ):
            assert banned not in source
