"""AOS-AUTO1H ``LiveRepositoryEvidenceReader`` truthful-UNAVAILABLE tests (#1155)."""

from __future__ import annotations

from scripts.agent_os_candidate_packet.stage_models import (
    DependencyEvidence,
    EvidenceStatus,
    ValidationEvidence,
)
from scripts.agent_os_candidate_packet_live_input.repository_reader import (
    DEPENDENCY_NO_STRUCTURED_SOURCE_REASON,
    VALIDATION_NO_STRUCTURED_SOURCE_REASON,
    LiveRepositoryEvidenceReader,
)

_REPOSITORY = "Blummer92/agent-os"
_ISSUE_NUMBER = 1155


def test_dependency_evidence_is_always_unavailable_with_exact_reason_code() -> None:
    reader = LiveRepositoryEvidenceReader()

    result = reader.read_dependency_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert isinstance(result, DependencyEvidence)
    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (DEPENDENCY_NO_STRUCTURED_SOURCE_REASON,)


def test_validation_evidence_is_always_unavailable_with_exact_reason_code() -> None:
    reader = LiveRepositoryEvidenceReader()

    result = reader.read_validation_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert isinstance(result, ValidationEvidence)
    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (VALIDATION_NO_STRUCTURED_SOURCE_REASON,)


def test_dependency_evidence_never_reports_resolved_clear() -> None:
    reader = LiveRepositoryEvidenceReader()
    for issue_number in (1, 42, 91105, 1155):
        result = reader.read_dependency_evidence(_REPOSITORY, issue_number)
        assert result.status is not EvidenceStatus.RESOLVED_CLEAR


def test_validation_evidence_never_reports_resolved_clear() -> None:
    reader = LiveRepositoryEvidenceReader()
    for issue_number in (1, 42, 91105, 1155):
        result = reader.read_validation_evidence(_REPOSITORY, issue_number)
        assert result.status is not EvidenceStatus.RESOLVED_CLEAR


def test_reader_execution_authorized_is_always_false() -> None:
    assert LiveRepositoryEvidenceReader().execution_authorized is False
