from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

import agent_os_execution_service.governed_resume_restart_capsule as capsule_module
from scripts.agent_os_execution_checkpoint.store import CheckpointStoreIntegrityConflict


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
