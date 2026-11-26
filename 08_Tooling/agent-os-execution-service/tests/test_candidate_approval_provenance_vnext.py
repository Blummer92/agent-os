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


@pytest.mark.parametrize("field,value", [
    ("extra", "unexpected"), ("planning-handoff", ""), ("source", "different-source"),
    ("proposal", None),
])
def test_fresh_provenance_rejects_weak_stage_identity_before_delegating(monkeypatch, field, value):
    from types import SimpleNamespace
    from scripts.agent_os_candidate_packet.proposal_stage import RepositoryProposalStageStatus

    _patch_transports(monkeypatch)
    provenance = provenance_module.build_candidate_approval_provenance(
        approval_ready_packet=FakePacket(CandidatePacketPhase.APPROVAL_READY),
        candidate_context=_context(), repository_proposal_stage_result=FakeProposalStage(),
    )
    proposal = SimpleNamespace(repository="Blummer92/agent-os", base_branch="main",
                               evaluated_repository_sha="a" * 40, proposal_id="proposal", handoff_digest="plan")
    proof = SimpleNamespace(evidence_id="repository")
    upstream = SimpleNamespace(status=RepositoryProposalStageStatus.ELIGIBLE, proposal=proposal,
                               issueplan_current_state_evidence=SimpleNamespace(evidence_id="issueplan", source_snapshot=SimpleNamespace(source_revision="source")),
                               repository_state_evidence=proof, planning_binding=object())
    actual = {"source":"source", "issueplan":"issueplan", "repository-evidence":"repository",
              "proposal":"proposal", "planning-handoff":"plan", "approval-candidate":"approval@1"}
    actual[field] = value
    packet = SimpleNamespace(stage_identities=tuple(actual.items()), repository=proposal.repository,
                             base_branch=proposal.base_branch, base_sha=proposal.evaluated_repository_sha)
    object.__setattr__(provenance, "repository_proposal_stage_result", upstream)
    object.__setattr__(provenance, "approval_ready_packet", packet)
    monkeypatch.setattr(fresh_module, "prepare_approval_projection", lambda *_args, **_kw: pytest.fail(
        "malformed provenance must not reach approval projection"
    ))
    with pytest.raises(fresh_module.FreshPreValidationError, match="candidate-provenance-drift"):
        fresh_module.prepare_fresh_pre_validation(
            provenance=provenance, approval_decision=object(),
            candidate_inputs=SimpleNamespace(repository_state_evidence=proof),
            evaluated_at="2026-09-12T14:00:00Z", projected_at="2026-09-12T14:00:00Z",
        )


def test_real_preapproval_packet_binds_the_fresh_projection(monkeypatch):
    from types import SimpleNamespace
    from tests.agent_os_candidate_packet.test_first_packet_approval_lifecycle import _approval_ready, _candidate_context, _decision

    ready = _approval_ready()
    stage = ready.proposal_stage_result
    value = provenance_module.build_candidate_approval_provenance(
        approval_ready_packet=ready.packet, candidate_context=_candidate_context(), repository_proposal_stage_result=stage,
    )
    monkeypatch.setattr(fresh_module, "prepare_pre_validation_stage",
                        lambda *_: SimpleNamespace(disposition=fresh_module.ValidationStageDisposition.GO))
    observed = fresh_module.prepare_fresh_pre_validation(
        provenance=value, approval_decision=_decision(), evaluated_at="2026-10-08T00:07:30Z",
        projected_at="2026-10-08T00:07:30Z",
        candidate_inputs=SimpleNamespace(repository_state_evidence=stage.repository_state_evidence),
    )
    assert observed.approval_stage_result.projection.proposal_id == stage.proposal.proposal_id
    assert observed.execution_authorized is False and observed.side_effects_performed is False
