from __future__ import annotations

import pytest

from scripts.agent_os_execution_interface.open_bug_candidate_population import (
    build_open_bug_candidate_population,
)


def issue(number: int, *, state: object = "open", bug: bool = True) -> dict[str, object]:
    return {
        "issue_number": number,
        "title": f"issue {number}",
        "state": state,
        "labels": ["type:bug"] if bug else ["type:tooling"],
    }


def test_closed_2598_shape_is_rejected_before_lane_lock_and_next_open_bug_replaces_it() -> None:
    result = build_open_bug_candidate_population(
        requested_count=2,
        canonical_issue_snapshots=[
            issue(2598, state="closed"),
            issue(2609),
            issue(2591),
        ],
    )
    assert [candidate.issue_number for candidate in result.open_candidates] == [2609, 2591]
    assert result.rejected_closed_issue_numbers == (2598,)
    assert result.population_shortfall == 0
    assert result.population_exhausted is False
    assert result.mutation_authorized is False


def test_concurrently_closed_candidate_does_not_consume_requested_count() -> None:
    result = build_open_bug_candidate_population(
        requested_count=1,
        canonical_issue_snapshots=[issue(10, state="closed"), issue(11)],
    )
    assert [candidate.issue_number for candidate in result.open_candidates] == [11]
    assert result.rejected_closed_issue_numbers == (10,)


def test_unknown_state_is_never_promoted_to_open() -> None:
    result = build_open_bug_candidate_population(
        requested_count=1,
        canonical_issue_snapshots=[issue(10, state=None), issue(11)],
    )
    assert [candidate.issue_number for candidate in result.open_candidates] == [11]
    assert result.rejected_unknown_issue_numbers == (10,)


def test_non_bug_open_history_does_not_consume_bug_lane() -> None:
    result = build_open_bug_candidate_population(
        requested_count=1,
        canonical_issue_snapshots=[issue(10, bug=False), issue(11)],
    )
    assert [candidate.issue_number for candidate in result.open_candidates] == [11]


def test_insufficient_open_pool_reports_honest_shortfall_without_closed_padding() -> None:
    result = build_open_bug_candidate_population(
        requested_count=3,
        canonical_issue_snapshots=[issue(1), issue(2, state="closed")],
    )
    assert [candidate.issue_number for candidate in result.open_candidates] == [1]
    assert result.rejected_closed_issue_numbers == (2,)
    assert result.population_shortfall == 2
    assert result.population_exhausted is True


def test_duplicate_canonical_issue_snapshot_is_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        build_open_bug_candidate_population(
            requested_count=1,
            canonical_issue_snapshots=[issue(1), issue(1)],
        )


def test_requested_count_and_snapshot_types_fail_closed() -> None:
    with pytest.raises(ValueError, match="requested_count"):
        build_open_bug_candidate_population(requested_count=0, canonical_issue_snapshots=[])
    with pytest.raises(TypeError, match="sequence"):
        build_open_bug_candidate_population(requested_count=1, canonical_issue_snapshots="bad")
