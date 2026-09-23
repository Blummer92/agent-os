"""Focused AOS-AUTO1F model tests for the #755 candidate-packet compiler."""

from __future__ import annotations

import pytest

from scripts.agent_os_candidate_packet.models import (
    COMPILER_SCHEMA_NAME,
    COMPILER_SCHEMA_VERSION,
    PACKET_SCHEMA_NAME,
    PACKET_SCHEMA_VERSION,
    CandidatePacket,
    CandidatePacketCompilationFailure,
    CandidatePacketCompilerInput,
    CandidatePacketPhase,
    FailureClass,
    candidate_packet_id,
    compute_candidate_packet_fingerprint,
    deserialize_candidate_packet,
    serialize_candidate_packet,
)
from tests.agent_os_candidate_packet.test_compiler import (
    _common_kwargs,
    _pending_approval,
    _pipeline,
)


def _minimal_input(**overrides) -> CandidatePacketCompilerInput:
    readiness, planning, proposal = _pipeline()
    kwargs = _common_kwargs(readiness, planning, proposal)
    kwargs["requested_phase"] = CandidatePacketPhase.APPROVAL_READY
    kwargs["approval_stage_result"] = _pending_approval(proposal)
    kwargs.update(overrides)
    return CandidatePacketCompilerInput(**kwargs)


def _packet_fields(**overrides) -> dict:
    values = dict(
        schema_name=PACKET_SCHEMA_NAME,
        schema_version=PACKET_SCHEMA_VERSION,
        phase=CandidatePacketPhase.APPROVAL_READY,
        repository="blummer92/agent-os",
        issue_number=750,
        invocation_id="candidate-packet-755",
        candidate_ref="agent/750-candidate-packet",
        base_branch="main",
        base_sha="b" * 40,
        candidate_sha="b" * 40,
        source_sha="b" * 40,
        tested_sha="b" * 40,
        evaluator_sha="a" * 40,
        external_build_sha=None,
        freshness_boundary="main@41ebab11",
        stage_identities=(("source", "github-issue-v1:" + "0" * 64),),
        stage_payload_digests=(("readiness", "candidate-packet-stage:readiness:" + "1" * 64),),
        provenance_manifest=("source:github-issue-v1:" + "0" * 64,),
        invalidation_manifest=("source-revision:source,readiness",),
        allowed_files=("scripts/agent_os_candidate_packet",),
        forbidden_paths=(),
        expected_changed_paths=(),
        required_tests=(),
        command_identities=(),
        argv_bindings=(),
        per_command_timeout_seconds=None,
        total_timeout_seconds=None,
        max_output_bytes=None,
        approval_boundary_summary="pending-candidate-only:no-human-decision-claimed",
        execution_authorization_boundary_summary="not-applicable:approval-ready-phase",
        evidence_completeness="complete",
        disposition="verified",
    )
    values.update(overrides)
    return values


def _packet(**overrides) -> CandidatePacket:
    fields = _packet_fields(**overrides)
    digest = compute_candidate_packet_fingerprint(fields)
    return CandidatePacket(packet_id=f"candidate-packet:{digest}", evaluated_at="2026-08-06T05:00:00Z", **fields)


# --------------------------------------------------------------------------
# CandidatePacketCompilerInput.
# --------------------------------------------------------------------------


def test_compiler_input_holds_fixed_authority_flags_false() -> None:
    compiler_input = _minimal_input()

    assert compiler_input.execution_authorized is False
    assert compiler_input.merge_authorized is False
    assert compiler_input.automatic_retry is False
    assert compiler_input.side_effects_performed is False


def test_compiler_input_rejects_malformed_repository() -> None:
    with pytest.raises(ValueError, match="owner/repository"):
        _minimal_input(repository="not-owner-slash-repo")


def test_compiler_input_rejects_non_hex_sha() -> None:
    with pytest.raises(ValueError, match="hex digest"):
        _minimal_input(base_sha="not-a-sha" + "0" * 31)


def test_compiler_input_rejects_uppercase_sha() -> None:
    with pytest.raises(ValueError, match="hex digest"):
        _minimal_input(base_sha="B" * 40)


def test_compiler_input_rejects_wrong_readiness_type() -> None:
    with pytest.raises(TypeError, match="readiness_stage_result"):
        _minimal_input(readiness_stage_result=object())


def test_compiler_input_accepts_none_approval_and_execution_packet() -> None:
    compiler_input = _minimal_input(approval_stage_result=None)

    assert compiler_input.approval_stage_result is None
    assert compiler_input.execution_packet_stage_result is None


def test_compiler_input_authority_fields_are_not_constructible() -> None:
    readiness, planning, proposal = _pipeline()
    kwargs = _common_kwargs(readiness, planning, proposal)
    kwargs["requested_phase"] = CandidatePacketPhase.APPROVAL_READY
    kwargs["approval_stage_result"] = _pending_approval(proposal)
    with pytest.raises(TypeError):
        CandidatePacketCompilerInput(**kwargs, execution_authorized=True)


# --------------------------------------------------------------------------
# CandidatePacket identity and round trip.
# --------------------------------------------------------------------------


def test_candidate_packet_id_is_deterministic_for_identical_fields() -> None:
    first = _packet()
    second = _packet()

    assert first.packet_id == second.packet_id
    assert candidate_packet_id(first) == candidate_packet_id(second)


def test_candidate_packet_id_excludes_evaluated_at() -> None:
    first = _packet()
    fields = _packet_fields()
    digest = compute_candidate_packet_fingerprint(fields)
    second = CandidatePacket(
        packet_id=f"candidate-packet:{digest}", evaluated_at="2099-01-01T00:00:00Z", **fields
    )

    assert first.packet_id == second.packet_id
    assert first.evaluated_at != second.evaluated_at


def test_candidate_packet_id_changes_with_freshness_boundary() -> None:
    first = _packet()
    second = _packet(freshness_boundary="main@deadbeef")

    assert first.packet_id != second.packet_id


def test_tampered_packet_id_is_rejected_at_construction() -> None:
    fields = _packet_fields()
    with pytest.raises(ValueError, match="does not match"):
        CandidatePacket(packet_id="candidate-packet:" + "0" * 64, evaluated_at="2026-08-06T05:00:00Z", **fields)


def test_approval_ready_packet_cannot_carry_command_evidence() -> None:
    with pytest.raises(ValueError, match="approval-ready packets cannot carry command"):
        _packet(command_identities=("some-command",))


def test_approval_ready_packet_cannot_carry_runtime_bounds() -> None:
    with pytest.raises(ValueError, match="approval-ready packets cannot carry runtime bounds"):
        _packet(per_command_timeout_seconds=30)


def test_serialize_and_deserialize_round_trip_exactly() -> None:
    packet = _packet()
    payload = serialize_candidate_packet(packet)
    rebuilt = deserialize_candidate_packet(payload)

    assert rebuilt == packet
    assert serialize_candidate_packet(rebuilt) == payload
    assert payload["execution_authorized"] is False
    assert payload["merge_authorized"] is False
    assert payload["automatic_retry"] is False
    assert payload["side_effects_performed"] is False


def test_deserialize_rejects_unsupported_field() -> None:
    payload = serialize_candidate_packet(_packet())
    bad = {**payload, "surprise": 1}

    with pytest.raises(ValueError, match="unsupported field"):
        deserialize_candidate_packet(bad)


def test_deserialize_rejects_missing_field() -> None:
    payload = serialize_candidate_packet(_packet())
    bad = dict(payload)
    del bad["approval_boundary_summary"]

    with pytest.raises(ValueError, match="missing field"):
        deserialize_candidate_packet(bad)


def test_deserialize_rejects_tampered_packet_id() -> None:
    payload = serialize_candidate_packet(_packet())
    bad = {**payload, "packet_id": "candidate-packet:" + "9" * 64}

    with pytest.raises(ValueError, match="does not match"):
        deserialize_candidate_packet(bad)


def test_deserialize_rejects_true_authority_flags() -> None:
    payload = serialize_candidate_packet(_packet())
    for name in ("execution_authorized", "merge_authorized", "automatic_retry", "side_effects_performed"):
        bad = {**payload, name: True}
        with pytest.raises(ValueError, match=f"{name} must be false"):
            deserialize_candidate_packet(bad)


def test_deserialize_rejects_unsupported_phase() -> None:
    payload = serialize_candidate_packet(_packet())
    bad = {**payload, "phase": "not-a-real-phase"}

    with pytest.raises(ValueError):
        deserialize_candidate_packet(bad)


# --------------------------------------------------------------------------
# CandidatePacketCompilationFailure.
# --------------------------------------------------------------------------


def test_compilation_failure_holds_fixed_authority_flags_false() -> None:
    failure = CandidatePacketCompilationFailure(
        schema_name="agent-os-candidate-packet-compilation-failure",
        schema_version="1.0",
        requested_phase=CandidatePacketPhase.APPROVAL_READY,
        failure_class=FailureClass.MISSING_MODEL,
        reason_code="approval-stage.missing",
        failed_stage="approval",
        remediation_owner="integration-manager",
        human_judgment_required=False,
        external_authorization_required=False,
        connected_capability_required=False,
    )

    assert failure.packet_constructed is False
    assert failure.execution_authorized is False
    assert failure.merge_authorized is False
    assert failure.automatic_retry is False
    assert failure.side_effects_performed is False


def test_compilation_failure_rejects_non_boolean_flags() -> None:
    with pytest.raises(TypeError):
        CandidatePacketCompilationFailure(
            schema_name="agent-os-candidate-packet-compilation-failure",
            schema_version="1.0",
            requested_phase=CandidatePacketPhase.APPROVAL_READY,
            failure_class=FailureClass.MISSING_MODEL,
            reason_code="approval-stage.missing",
            failed_stage="approval",
            remediation_owner="integration-manager",
            human_judgment_required=1,
            external_authorization_required=False,
            connected_capability_required=False,
        )


def test_schema_constants_are_stable() -> None:
    assert COMPILER_SCHEMA_NAME == "agent-os-candidate-packet-compiler"
    assert COMPILER_SCHEMA_VERSION == "1.0"
    assert PACKET_SCHEMA_NAME == "agent-os-candidate-packet"
    assert PACKET_SCHEMA_VERSION == "1.0"
