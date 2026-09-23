from scripts.agent_os_work_scanner.gradebook_reader import ReaderFreshness, ReaderStatus
from scripts.agent_os_work_scanner.grading_decision import IdentityResolution
from scripts.agent_os_work_scanner.schoology_gradebook_adapter import (
    SchoologyGradebookSnapshot,
    SchoologyIdentityCandidate,
    SchoologyPageState,
    normalize_schoology_snapshot,
)


def candidate(kind: str, identity_id: str) -> SchoologyIdentityCandidate:
    return SchoologyIdentityCandidate(identity_id, f"schoology:{kind}:{identity_id}")


def snapshot(**overrides: object) -> SchoologyGradebookSnapshot:
    values = {
        "course_id": "course-01",
        "student_candidates": (candidate("student", "student-01"),),
        "assignment_candidates": (candidate("assignment", "assignment-01"),),
        "visible_score": "8",
        "visible_feedback": "Synthetic Schoology-like feedback",
        "editable": True,
        "freshness": ReaderFreshness.CURRENT,
        "evidence_refs": ("schoology:synthetic:grade-row",),
        "selector_refs": ('[data-synthetic-role="grade-row"]',),
    }
    values.update(overrides)
    return SchoologyGradebookSnapshot(**values)


def test_schoology_success_normalizes_into_provider_neutral_reader() -> None:
    reader = normalize_schoology_snapshot(snapshot())
    assert reader.platform == "schoology"
    assert reader.status == ReaderStatus.READ_SUCCESS
    assert reader.student.resolved_id == "student-01"
    assert reader.assignment.resolved_id == "assignment-01"
    assert reader.write_authorized is False


def test_schoology_ambiguous_student_and_assignment_fail_closed() -> None:
    students = (candidate("student", "student-01"), candidate("student", "student-02"))
    assignments = (candidate("assignment", "assignment-01"), candidate("assignment", "assignment-02"))
    student_reader = normalize_schoology_snapshot(snapshot(student_candidates=students))
    assignment_reader = normalize_schoology_snapshot(snapshot(assignment_candidates=assignments))
    assert student_reader.status == ReaderStatus.AMBIGUOUS_STUDENT
    assert student_reader.student.resolution == IdentityResolution.AMBIGUOUS
    assert assignment_reader.status == ReaderStatus.AMBIGUOUS_ASSIGNMENT
    assert assignment_reader.assignment.resolution == IdentityResolution.AMBIGUOUS


def test_schoology_missing_target_is_not_found() -> None:
    reader = normalize_schoology_snapshot(snapshot(student_candidates=()))
    assert reader.status == ReaderStatus.NOT_FOUND
    assert reader.student.resolution == IdentityResolution.NOT_FOUND


def test_schoology_read_only_and_stale_states_are_explicit() -> None:
    read_only = normalize_schoology_snapshot(snapshot(editable=False))
    stale = normalize_schoology_snapshot(snapshot(freshness=ReaderFreshness.STALE))
    assert read_only.status == ReaderStatus.READ_ONLY
    assert read_only.write_authorized is False
    assert stale.status == ReaderStatus.STALE_STATE


def test_schoology_selector_drift_precedes_normal_success() -> None:
    reader = normalize_schoology_snapshot(snapshot(selector_drift=True))
    assert reader.status == ReaderStatus.SELECTOR_DRIFT


def test_schoology_authentication_and_unsupported_page_are_explicit() -> None:
    auth = normalize_schoology_snapshot(snapshot(page_state=SchoologyPageState.AUTHENTICATION_REQUIRED))
    unsupported = normalize_schoology_snapshot(snapshot(page_state=SchoologyPageState.UNSUPPORTED_PAGE))
    assert auth.status == ReaderStatus.AUTHENTICATION_REQUIRED
    assert unsupported.status == ReaderStatus.UNSUPPORTED_PAGE


def test_schoology_unknown_freshness_fails_closed() -> None:
    reader = normalize_schoology_snapshot(snapshot(freshness=ReaderFreshness.UNKNOWN))
    assert reader.status == ReaderStatus.READER_ERROR


def test_schoology_adapter_has_no_write_surface() -> None:
    reader = normalize_schoology_snapshot(snapshot())
    for name in ("write_grade", "submit", "confirm_grade_write", "begin_grade_write"):
        assert not hasattr(reader, name)
