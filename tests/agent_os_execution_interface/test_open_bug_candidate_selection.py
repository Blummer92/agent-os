import pytest

from scripts.agent_os_execution_interface.open_bug_candidate_selection import (
    BugCandidate,
    CandidateState,
    select_open_bug_candidates,
)


def test_closed_2598_shaped_candidate_never_consumes_open_lane() -> None:
    result = select_open_bug_candidates(
        [
            BugCandidate(2607, CandidateState.OPEN),
            BugCandidate(2598, CandidateState.CLOSED),
            BugCandidate(2609, CandidateState.OPEN),
        ],
        requested_count=2,
    )
    assert result.selected_issue_numbers == (2607, 2609)
    assert result.rejected_closed == (2598,)
    assert result.population_exhausted is False


def test_candidate_that_closed_before_lane_lock_is_replaced_from_remaining_open_pool() -> None:
    ranked = [
        BugCandidate(100, CandidateState.CLOSED),
        BugCandidate(101, CandidateState.OPEN),
        BugCandidate(102, CandidateState.OPEN),
    ]
    result = select_open_bug_candidates(ranked, requested_count=2)
    assert result.selected_issue_numbers == (101, 102)
    assert result.rejected_closed == (100,)


def test_unknown_state_fails_closed_and_does_not_count_as_open() -> None:
    result = select_open_bug_candidates(
        [BugCandidate(200, CandidateState.UNKNOWN), BugCandidate(201, CandidateState.OPEN)],
        requested_count=2,
    )
    assert result.selected_issue_numbers == (201,)
    assert result.rejected_unknown == (200,)
    assert result.population_exhausted is True


def test_closed_historical_dependency_is_retained_only_as_supporting_evidence() -> None:
    result = select_open_bug_candidates(
        [
            BugCandidate(2214, CandidateState.CLOSED, historical_dependency=True),
            BugCandidate(2609, CandidateState.OPEN),
        ],
        requested_count=1,
    )
    assert result.selected_issue_numbers == (2609,)
    assert result.historical_issue_numbers == (2214,)
    assert result.rejected_closed == ()


def test_insufficient_open_pool_reports_exhaustion_without_padding_from_closed_history() -> None:
    result = select_open_bug_candidates(
        [
            BugCandidate(300, CandidateState.OPEN),
            BugCandidate(301, CandidateState.CLOSED),
            BugCandidate(302, CandidateState.CLOSED, historical_dependency=True),
        ],
        requested_count=3,
    )
    assert result.selected_issue_numbers == (300,)
    assert result.population_exhausted is True


def test_non_bug_and_duplicate_records_cannot_pad_requested_count() -> None:
    result = select_open_bug_candidates(
        [
            BugCandidate(400, CandidateState.OPEN, is_bug=False),
            BugCandidate(401, CandidateState.OPEN),
            BugCandidate(401, CandidateState.OPEN),
        ],
        requested_count=2,
    )
    assert result.selected_issue_numbers == (401,)
    assert result.rejected_non_bug == (400,)
    assert result.population_exhausted is True


def test_requested_count_must_be_positive() -> None:
    with pytest.raises(ValueError):
        select_open_bug_candidates([], requested_count=0)
