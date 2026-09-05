from decimal import Decimal

import pytest

from scripts.agent_os_work_scanner.gradebook_reader import (
    Editability,
    EvidenceProvenance,
    GradebookReaderResult,
    ReaderFreshness,
    ReaderStatus,
    normalize_reader_record,
)
from scripts.agent_os_work_scanner.grading_decision import IdentityEvidence, IdentityResolution
from scripts.agent_os_work_scanner.synthetic_gradebook import FixtureMode, SyntheticGradebookFixture


def identity(resolution: IdentityResolution, resolved_id: str | None, ref: str) -> IdentityEvidence:
    return IdentityEvidence(resolution, resolved_id, (ref,), Decimal("1" if resolution == IdentityResolution.RESOLVED else "0.5"))


def result(**overrides: object) -> GradebookReaderResult:
    values = {
        "platform": "synthetic-lms",
        "course_id": "course-01",
        "student": identity(IdentityResolution.RESOLVED, "student-01", "student:student-01"),
        "assignment": identity(IdentityResolution.RESOLVED, "assignment-01", "assignment:assignment-01"),
        "visible_score": "8",
        "visible_feedback": "Synthetic feedback A",
        "editability": Editability.EDITABLE,
        "freshness": ReaderFreshness.CURRENT,
        "provenance": EvidenceProvenance(("fixture:v1",), ('[data-testid="student-student-01"]',)),
        "status": ReaderStatus.READ_SUCCESS,
        "confidence": Decimal("1"),
    }
    values.update(overrides)
    return GradebookReaderResult(**values)


def test_successful_read_from_1128_fixture_is_deterministic_and_non_authorizing() -> None:
    fixture = SyntheticGradebookFixture()
    grade = fixture.visible_grade("student-01", "assignment-01")
    first = result(visible_score=grade["score"], visible_feedback=grade["comment"])
    second = result(visible_score=grade["score"], visible_feedback=grade["comment"])
    assert first.reader_evidence_id == second.reader_evidence_id
    assert first.to_record()["write_authorized"] is False


def test_not_found_and_ambiguity_are_explicit() -> None:
    fixture = SyntheticGradebookFixture()
    assert fixture.match_student("missing").status == "not-found"
    assert fixture.match_assignment("missing").status == "not-found"
    student = identity(IdentityResolution.AMBIGUOUS, None, "student:ambiguous")
    assignment = identity(IdentityResolution.AMBIGUOUS, None, "assignment:ambiguous")
    assert result(student=student, status=ReaderStatus.AMBIGUOUS_STUDENT).status == ReaderStatus.AMBIGUOUS_STUDENT
    assert result(assignment=assignment, status=ReaderStatus.AMBIGUOUS_ASSIGNMENT).status == ReaderStatus.AMBIGUOUS_ASSIGNMENT


def test_read_only_state_is_evidence_not_write_authority() -> None:
    fixture = SyntheticGradebookFixture()
    fixture.set_mode(FixtureMode.READ_ONLY)
    reader = result(editability=Editability.READ_ONLY, status=ReaderStatus.READ_ONLY)
    assert fixture.mode.value == "read-only"
    assert reader.write_authorized is False


def test_stale_state_and_selector_drift_are_distinct() -> None:
    stale = result(freshness=ReaderFreshness.STALE, status=ReaderStatus.STALE_STATE)
    drift = result(status=ReaderStatus.SELECTOR_DRIFT)
    assert stale.status != drift.status
    assert stale.freshness == ReaderFreshness.STALE


def test_authentication_required_and_unsupported_page_are_finite_statuses() -> None:
    assert result(status=ReaderStatus.AUTHENTICATION_REQUIRED).status.value == "authentication-required"
    assert result(status=ReaderStatus.UNSUPPORTED_PAGE).status.value == "unsupported-page"


def test_malformed_adapter_record_fails_closed() -> None:
    with pytest.raises(ValueError, match="malformed gradebook reader record"):
        normalize_reader_record({"platform": "synthetic-lms"})


def test_normalization_round_trip_preserves_identity_and_evidence() -> None:
    original = result()
    record = original.to_record()
    record.pop("reader_evidence_id")
    record.pop("write_authorized")
    normalized = normalize_reader_record(record)
    assert normalized.reader_evidence_id == original.reader_evidence_id
    assert normalized.student.resolved_id == "student-01"
    assert normalized.assignment.resolved_id == "assignment-01"


def test_success_status_rejects_ambiguous_or_stale_evidence() -> None:
    with pytest.raises(ValueError, match="resolved student"):
        result(student=identity(IdentityResolution.AMBIGUOUS, None, "student:ambiguous"))
    with pytest.raises(ValueError, match="current evidence"):
        result(freshness=ReaderFreshness.STALE)


def test_reader_identity_evidence_uses_grading_decision_contract_type() -> None:
    reader = result()
    assert isinstance(reader.student, IdentityEvidence)
    assert isinstance(reader.assignment, IdentityEvidence)


def test_reader_has_no_grade_mutation_surface() -> None:
    reader = result()
    forbidden = ("begin_grade_write", "confirm_grade_write", "write_grade", "submit")
    for name in forbidden:
        assert not hasattr(reader, name)
