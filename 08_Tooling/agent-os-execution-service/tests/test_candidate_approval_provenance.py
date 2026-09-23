from __future__ import annotations

import inspect
import json
from dataclasses import dataclass

import pytest

import agent_os_execution_service.candidate_approval_provenance as module
from scripts.agent_os_candidate_packet.approval_stage import ApprovalCandidateContext
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from scripts.agent_os_issue_acceptance.approval_records import ApprovalKind


@dataclass(frozen=True)
class FakePacket:
    phase: CandidatePacketPhase
    evidence_completeness: str = "complete"
    disposition: str = "verified"
    packet_id: str = "candidate-packet:test"


def patch_packet_transport(monkeypatch):
    monkeypatch.setattr(module, "CandidatePacket", FakePacket)
    monkeypatch.setattr(
        module,
        "serialize_candidate_packet",
        lambda packet: {
            "phase": packet.phase.value,
            "evidence_completeness": packet.evidence_completeness,
            "disposition": packet.disposition,
            "packet_id": packet.packet_id,
        },
    )
    monkeypatch.setattr(
        module,
        "deserialize_candidate_packet",
        lambda payload: FakePacket(
            phase=CandidatePacketPhase(payload["phase"]),
            evidence_completeness=payload["evidence_completeness"],
            disposition=payload["disposition"],
            packet_id=payload["packet_id"],
        ),
    )


def context(authorizer="candidate-preparer"):
    return ApprovalCandidateContext(
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id=authorizer,
        decision_id="candidate-preparation:1982",
        decision_at="2026-09-11T21:30:00Z",
    )


def test_candidate_provenance_round_trip_is_content_addressed_and_non_authorizing(monkeypatch):
    patch_packet_transport(monkeypatch)
    evidence = module.build_candidate_approval_provenance(
        approval_ready_packet=FakePacket(CandidatePacketPhase.APPROVAL_READY),
        candidate_context=context(),
    )
    raw = module.serialize_candidate_approval_provenance(evidence)
    rebuilt = module.deserialize_candidate_approval_provenance(raw)
    assert rebuilt == evidence
    assert evidence.evidence_id.startswith("pre-publication-evidence:")
    payload = json.loads(raw)
    assert payload["candidate_context"]["authorizer_id"] == "candidate-preparer"
    for name in (
        "repository_implementation_authorized",
        "execution_authorized",
        "publication_authorized",
        "github_writes_authorized",
        "merge_authorized",
        "external_writes_authorized",
    ):
        assert payload[name] is False


def test_candidate_provenance_rejects_execution_candidate_and_incomplete_packet(monkeypatch):
    patch_packet_transport(monkeypatch)
    with pytest.raises(ValueError, match="APPROVAL_READY"):
        module.build_candidate_approval_provenance(
            approval_ready_packet=FakePacket(CandidatePacketPhase.EXECUTION_CANDIDATE),
            candidate_context=context(),
        )
    with pytest.raises(ValueError, match="complete verified"):
        module.build_candidate_approval_provenance(
            approval_ready_packet=FakePacket(
                CandidatePacketPhase.APPROVAL_READY, evidence_completeness="partial"
            ),
            candidate_context=context(),
        )


def test_candidate_provenance_uses_existing_pre_publication_namespace_only() -> None:
    source = inspect.getsource(module)
    assert module.STORE_NAMESPACE == "pre-publication-producer-evidence"
    assert "checkpoint_store_root" not in inspect.signature(
        module.build_candidate_approval_provenance
    ).parameters
    for forbidden in (
        "sqlite3",
        "requests.",
        "google.cloud",
        "latest",
        "execution_authorized=True",
        "merge_authorized=True",
    ):
        assert forbidden not in source
