"""Focused AOS-AUTO1F blocker/failure-vocabulary tests for the #755 compiler."""

from __future__ import annotations

import pytest

from scripts.agent_os_candidate_packet.blockers import (
    FAILURE_SCHEMA_NAME,
    FAILURE_SCHEMA_VERSION,
    RUNTIME_REASON_CODES,
    build_failure,
)
from scripts.agent_os_candidate_packet.models import (
    CandidatePacketCompilationFailure,
    CandidatePacketPhase,
    FailureClass,
)


def test_build_failure_rejects_unknown_reason_code() -> None:
    with pytest.raises(ValueError, match="unsupported compiler reason_code"):
        build_failure(
            requested_phase=CandidatePacketPhase.APPROVAL_READY, reason_code="not-a-real-reason"
        )


def test_build_failure_populates_fixed_metadata_deterministically() -> None:
    first = build_failure(
        requested_phase=CandidatePacketPhase.APPROVAL_READY, reason_code="approval-stage.missing"
    )
    second = build_failure(
        requested_phase=CandidatePacketPhase.EXECUTION_CANDIDATE, reason_code="approval-stage.missing"
    )

    assert isinstance(first, CandidatePacketCompilationFailure)
    assert first.schema_name == FAILURE_SCHEMA_NAME
    assert first.schema_version == FAILURE_SCHEMA_VERSION
    assert first.failure_class is FailureClass.MISSING_MODEL
    assert first.remediation_owner == "integration-manager"
    assert first.failed_stage == "approval"
    # Metadata is fixed by reason code, independent of requested phase.
    assert first.failure_class == second.failure_class
    assert first.remediation_owner == second.remediation_owner
    assert first.requested_phase is not second.requested_phase


def test_authorization_required_codes_set_external_authorization_flag() -> None:
    failure = build_failure(
        requested_phase=CandidatePacketPhase.EXECUTION_CANDIDATE, reason_code="approval-stage.rejected"
    )

    assert failure.failure_class is FailureClass.AUTHORIZATION_REQUIRED
    assert failure.external_authorization_required is True
    assert failure.human_judgment_required is False
    assert failure.connected_capability_required is False


def test_manual_judgment_codes_set_human_judgment_flag() -> None:
    failure = build_failure(
        requested_phase=CandidatePacketPhase.APPROVAL_READY, reason_code="proposal.needs-decision"
    )

    assert failure.failure_class is FailureClass.MANUAL_JUDGMENT_REQUIRED
    assert failure.human_judgment_required is True
    assert failure.remediation_owner == "repository-owner"


def test_external_capability_codes_set_connected_capability_flag() -> None:
    failure = build_failure(
        requested_phase=CandidatePacketPhase.EXECUTION_CANDIDATE,
        reason_code="execution-packet.runtime-capability-unavailable",
    )

    assert failure.failure_class is FailureClass.EXTERNAL_CAPABILITY_REQUIRED
    assert failure.connected_capability_required is True
    assert failure.remediation_owner == "github-service-agent"


def test_build_failure_carries_optional_identity_diagnostics() -> None:
    failure = build_failure(
        requested_phase=CandidatePacketPhase.APPROVAL_READY,
        reason_code="cross-binding.repository-mismatch",
        failed_field="repository",
        expected_identity="owner/repo",
        observed_identity="other/repo",
    )

    assert failure.failed_field == "repository"
    assert failure.expected_identity == "owner/repo"
    assert failure.observed_identity == "other/repo"


def test_runtime_reason_codes_are_exactly_the_closed_metadata_table() -> None:
    for reason_code in RUNTIME_REASON_CODES:
        failure = build_failure(
            requested_phase=CandidatePacketPhase.APPROVAL_READY, reason_code=reason_code
        )
        assert failure.reason_code == reason_code
        assert isinstance(failure.failure_class, FailureClass)
        assert failure.remediation_owner


def test_every_failure_fixes_authority_and_construction_flags_false() -> None:
    for reason_code in RUNTIME_REASON_CODES:
        failure = build_failure(
            requested_phase=CandidatePacketPhase.APPROVAL_READY, reason_code=reason_code
        )
        assert failure.packet_constructed is False
        assert failure.execution_authorized is False
        assert failure.merge_authorized is False
        assert failure.automatic_retry is False
        assert failure.side_effects_performed is False
