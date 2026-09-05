from decimal import Decimal

import pytest

from scripts.agent_os_work_scanner.synthetic_gradebook import (
    FixtureMode,
    ReadOnlyFixtureError,
    RecoverableFixtureError,
    StaleFixtureError,
    SyntheticGradebookFixture,
)


def test_fixture_reset_and_digest_are_deterministic() -> None:
    fixture = SyntheticGradebookFixture()
    digest = fixture.digest
    fixture.begin_grade_write("student-02", "assignment-01", Decimal("7"), "Synthetic update")
    fixture.confirm_grade_write()
    assert fixture.visible_grade("student-02", "assignment-01")["score"] == "7"

    fixture.reset()
    assert fixture.digest == digest
    assert fixture.visible_grade("student-02", "assignment-01")["score"] is None
    assert fixture.confirmation_modal is False


def test_semantic_student_and_assignment_matching_supports_ambiguity() -> None:
    fixture = SyntheticGradebookFixture()
    assert fixture.match_student("Beta").status == "resolved"
    assert fixture.match_student("Learner Al").status == "ambiguous"
    assert fixture.match_assignment("Lighting").status == "resolved"
    assert fixture.match_assignment("Composition Study").status == "ambiguous"
    assert fixture.match_assignment("missing").status == "not-found"


def test_single_grade_write_requires_confirmation_and_has_visible_readback() -> None:
    fixture = SyntheticGradebookFixture()
    fixture.begin_grade_write("student-02", "assignment-01", Decimal("7.5"), "Synthetic feedback")
    assert fixture.confirmation_modal is True
    assert fixture.visible_grade("student-02", "assignment-01")["score"] is None

    result = fixture.confirm_grade_write()
    assert result["score"] == "7.5"
    assert result["comment"] == "Synthetic feedback"
    assert fixture.visible_grade("student-02", "assignment-01") == result


def test_read_only_mode_rejects_writes() -> None:
    fixture = SyntheticGradebookFixture()
    fixture.set_mode(FixtureMode.READ_ONLY)
    with pytest.raises(ReadOnlyFixtureError):
        fixture.begin_grade_write("student-01", "assignment-01", Decimal("9"))


def test_stale_visible_state_rejects_writes() -> None:
    fixture = SyntheticGradebookFixture()
    fixture.set_stale()
    with pytest.raises(StaleFixtureError):
        fixture.begin_grade_write("student-01", "assignment-01", Decimal("9"))


def test_selector_drift_is_deterministic_and_distinguishable() -> None:
    fixture = SyntheticGradebookFixture()
    stable = fixture.stable_selector("student", "student-01")
    fragile = fixture.fragile_selector("student", "student-01")
    assert "data-testid" in stable
    assert "generated" in fragile

    fixture.set_selector_drift()
    assert fixture.stable_selector("student", "student-01") != stable
    assert "missing" in fixture.stable_selector("student", "student-01")


def test_recoverable_error_fails_once_then_allows_retry() -> None:
    fixture = SyntheticGradebookFixture()
    fixture.set_recoverable_error()
    with pytest.raises(RecoverableFixtureError):
        fixture.begin_grade_write("student-01", "assignment-01", Decimal("9"))

    fixture.begin_grade_write("student-01", "assignment-01", Decimal("9"))
    assert fixture.confirm_grade_write()["score"] == "9"


def test_pagination_and_filtering_are_deterministic() -> None:
    fixture = SyntheticGradebookFixture()
    first = fixture.list_students(page=1, page_size=2)
    second = fixture.list_students(page=2, page_size=2)
    filtered = fixture.list_students(query="Alpha")
    assert [row["id"] for row in first] == ["student-01", "student-02"]
    assert [row["id"] for row in second] == ["student-03"]
    assert [row["id"] for row in filtered] == ["student-01"]


def test_fixture_contains_numeric_missing_comment_and_rubric_states() -> None:
    fixture = SyntheticGradebookFixture()
    graded = fixture.visible_grade("student-01", "assignment-01")
    missing = fixture.visible_grade("student-02", "assignment-01")
    assert graded["score"] == "8"
    assert graded["comment"]
    assert len(graded["rubric"]) == 2
    assert missing["score"] is None


def test_fixture_module_has_no_network_surface() -> None:
    fixture = SyntheticGradebookFixture()
    serialized = repr(fixture.state).lower()
    for forbidden in ("http://", "https://", "cookie", "token", "credential", "schoology", "powerschool"):
        assert forbidden not in serialized
