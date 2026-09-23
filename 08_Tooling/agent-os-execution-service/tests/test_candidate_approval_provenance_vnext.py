from __future__ import annotations

import inspect
import json
from dataclasses import dataclass

import pytest

import agent_os_execution_service.candidate_approval_provenance as provenance_module
import agent_os_execution_service.fresh_pre_validation as fresh_module
from scripts.agent_os_candidate_packet.approval_stage import ApprovalCandidateContext
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from scripts.agent_os_issue_acceptance.approval_records import ApprovalKind


@dataclass(frozen=True)
class FakePacket:
    phase: CandidatePacketPhase
    evidence_completeness: str = "complete"
    disposition: str = "verified"
    packet_id: str = "candidate-packet:test"


@dataclass(frozen=True)
class FakeProposalStage:
    marker: str = "canonical-proposal-stage"


def _patch_transports(monkeypatch):
    monkeypatch.setattr(provenance_module, "CandidatePacket", FakePacket)
    monkeypatch.setattr(provenance_module, "RepositoryProposalStageResult", FakeProposalStage)
    monkeypatch.setattr(
        provenance_module,
        "serialize_candidate_packet",
        lambda packet: {
            "phase": packet.phase.value,
            "evidence_completeness": packet.evidence_completeness,
            "disposition": packet.disposition,
            "packet_id": packet.packet_id,
        },
    )
    monkeypatch.setattr(
        provenance_module,
        "deserialize_candidate_packet",
        lambda payload: FakePacket(
            phase=CandidatePacketPhase(payload["phase"]),
            evidence_completeness=payload["evidence_completeness"],
            disposition=payload["disposition"],
            packet_id=payload["packet_id"],
        ),
    )
    monkeypatch.setattr(
        provenance_module,
        "repository_proposal_stage_result_to_dict",
        lambda stage: {"marker": stage.marker},
    )
    monkeypatch.setattr(
        provenance_module,
        "repository_proposal_stage_result_from_dict",
        lambda payload: FakeProposalStage(marker=payload["marker"]),
    )


def _context():
    return ApprovalCandidateContext(
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id="candidate-preparer",
        decision_id="candidate-preparation:1985",
        decision_at="2026-09-12T14:00:00Z",
    )


def test_vnext_round_trip_retains_exact_canonical_proposal_material(monkeypatch):
    _patch_transports(monkeypatch)
    value = provenance_module.build_candidate_approval_provenance(
        approval_ready_packet=FakePacket(CandidatePacketPhase.APPROVAL_READY),
        candidate_context=_context(),
        repository_proposal_stage_result=FakeProposalStage(),
    )
    assert value.schema_version == provenance_module.SCHEMA_VERSION
    raw = provenance_module.serialize_candidate_approval_provenance(value)
    rebuilt = provenance_module.deserialize_candidate_approval_provenance(raw)
    assert rebuilt == value
    assert rebuilt.repository_proposal_stage_result == FakeProposalStage()
    assert rebuilt.evidence_id == value.evidence_id


def test_legacy_v1_payload_remains_readable_and_identity_stable(monkeypatch):
    _patch_transports(monkeypatch)
    value = provenance_module.build_candidate_approval_provenance(
        approval_ready_packet=FakePacket(CandidatePacketPhase.APPROVAL_READY),
        candidate_context=_context(),
    )
    assert value.schema_version == provenance_module.LEGACY_SCHEMA_VERSION
    raw = provenance_module.serialize_candidate_approval_provenance(value)
    payload = json.loads(raw)
    assert "repository_proposal_stage_result" not in payload
    assert provenance_module.deserialize_candidate_approval_provenance(raw) == value


def test_vnext_nested_stage_tamper_fails_closed(monkeypatch):
    _patch_transports(monkeypatch)
    value = provenance_module.build_candidate_approval_provenance(
        approval_ready_packet=FakePacket(CandidatePacketPhase.APPROVAL_READY),
        candidate_context=_context(),
        repository_proposal_stage_result=FakeProposalStage(),
    )
    payload = json.loads(provenance_module.serialize_candidate_approval_provenance(value))
    payload["repository_proposal_stage_result"]["marker"] = "tampered"
    with pytest.raises(ValueError, match="evidence_id mismatch"):
        provenance_module.deserialize_candidate_approval_provenance(
            json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )


def test_fresh_seam_delegates_to_existing_753_and_pre_validation_owners() -> None:
    source = inspect.getsource(fresh_module.prepare_fresh_pre_validation)
    assert "prepare_approval_projection(" in source
    assert "prepare_pre_validation_stage(" in source
    assert "candidate-provenance-drift" in source
    assert "candidate-currentness-binding-mismatch" in source
    for forbidden in (
        "subprocess",
        "requests.",
        "google.cloud",
        "sqlite3",
        "execution_authorized=True",
        "ApprovalRecord(",
    ):
        assert forbidden not in inspect.getsource(fresh_module)


def test_existing_store_namespace_and_no_new_discovery_mechanism() -> None:
    source = inspect.getsource(provenance_module)
    assert provenance_module.STORE_NAMESPACE == "pre-publication-producer-evidence"
    for forbidden in ("latest", "index.json", "sqlite3", "glob("):
        assert forbidden not in source
