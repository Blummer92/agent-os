"""T4 (#887) — dependency and blocker taxonomy checker."""
from pathlib import Path

from scripts.agent_os_issue_acceptance.checks import dependency_blocker
from scripts.agent_os_issue_acceptance.models import Status

_FIXTURES = Path(__file__).parent / "fixtures" / "dependency_blocker"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text()


# --- empty body ---------------------------------------------------------


def test_empty_body_is_manual_review_for_all_checks():
    results = dependency_blocker.check("")
    assert [r.status for r in results] == [Status.MANUAL_REVIEW] * 3


# --- parent reference -----------------------------------------------------


def test_missing_parent_section_is_warn():
    body = _load("missing_parent.md")
    result = dependency_blocker.check_parent_reference(body)
    assert result.status == Status.WARN


def test_parent_section_without_reference_is_warn():
    body = _load("parent_no_reference.md")
    result = dependency_blocker.check_parent_reference(body)
    assert result.status == Status.WARN


def test_parent_section_with_reference_is_pass():
    body = _load("blocked_with_unblock.md")
    result = dependency_blocker.check_parent_reference(body)
    assert result.status == Status.PASS
    assert "#164" in result.evidence[0]


# --- related references ----------------------------------------------------


def test_missing_related_section_is_warn():
    body = _load("missing_parent.md")
    result = dependency_blocker.check_related_references(body)
    assert result.status == Status.WARN


def test_related_section_with_references_is_pass():
    body = _load("blocked_with_unblock.md")
    result = dependency_blocker.check_related_references(body)
    assert result.status == Status.PASS


# --- blocker state -----------------------------------------------------


def test_no_blocker_language_is_pass():
    body = _load("no_blocker.md")
    result = dependency_blocker.check_blocker_state(body)
    assert result.status == Status.PASS


def test_blocked_with_unblock_condition_is_pass():
    body = _load("blocked_with_unblock.md")
    result = dependency_blocker.check_blocker_state(body)
    assert result.status == Status.PASS


def test_blocked_without_unblock_condition_is_manual_review():
    body = _load("blocked_ambiguous.md")
    result = dependency_blocker.check_blocker_state(body)
    assert result.status == Status.MANUAL_REVIEW


# --- aggregate check --------------------------------------------------------


def test_check_returns_three_results_in_order():
    body = _load("blocked_with_unblock.md")
    results = dependency_blocker.check(body)
    assert [r.name for r in results] == [
        "parent reference",
        "related references",
        "blocker state",
    ]
