"""Open-only candidate admission for bounded existing-backlog bug missions.

This module is deliberately pure: canonical GitHub issue state is supplied by the
caller and no issue-state cache, synchronization worker, or second backlog store
is introduced. Closed history may be retained as supporting evidence, but only
open issues can consume an actionable candidate lane.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class CandidateState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BugCandidate:
    issue_number: int
    state: CandidateState
    is_bug: bool = True
    historical_dependency: bool = False

    def __post_init__(self) -> None:
        if type(self.issue_number) is not int or self.issue_number <= 0:
            raise ValueError("issue_number must be a positive integer")
        if not isinstance(self.state, CandidateState):
            raise TypeError("state must be CandidateState")


@dataclass(frozen=True, slots=True)
class OpenBugSelection:
    selected_issue_numbers: tuple[int, ...]
    rejected_closed: tuple[int, ...]
    rejected_unknown: tuple[int, ...]
    rejected_non_bug: tuple[int, ...]
    historical_issue_numbers: tuple[int, ...]
    requested_count: int
    population_exhausted: bool

    @property
    def delivered_population_count(self) -> int:
        return len(self.selected_issue_numbers)


def select_open_bug_candidates(
    candidates: Iterable[BugCandidate], *, requested_count: int
) -> OpenBugSelection:
    """Select at most ``requested_count`` actionable bugs from canonical open state.

    The input order is the caller's already-ranked backlog order. A candidate
    that closes before lane lock is rejected and the next open candidate is
    considered. Unknown state fails closed. Historical dependencies are never
    actionable lanes, regardless of their historical state.
    """

    if type(requested_count) is not int or requested_count <= 0:
        raise ValueError("requested_count must be a positive integer")

    selected: list[int] = []
    rejected_closed: list[int] = []
    rejected_unknown: list[int] = []
    rejected_non_bug: list[int] = []
    historical: list[int] = []
    seen: set[int] = set()

    for candidate in candidates:
        if not isinstance(candidate, BugCandidate):
            raise TypeError("candidates must contain BugCandidate values")
        if candidate.issue_number in seen:
            continue
        seen.add(candidate.issue_number)

        if candidate.historical_dependency:
            historical.append(candidate.issue_number)
            continue
        if not candidate.is_bug:
            rejected_non_bug.append(candidate.issue_number)
            continue
        if candidate.state is CandidateState.CLOSED:
            rejected_closed.append(candidate.issue_number)
            continue
        if candidate.state is CandidateState.UNKNOWN:
            rejected_unknown.append(candidate.issue_number)
            continue
        if len(selected) < requested_count:
            selected.append(candidate.issue_number)

    return OpenBugSelection(
        selected_issue_numbers=tuple(selected),
        rejected_closed=tuple(rejected_closed),
        rejected_unknown=tuple(rejected_unknown),
        rejected_non_bug=tuple(rejected_non_bug),
        historical_issue_numbers=tuple(historical),
        requested_count=requested_count,
        population_exhausted=len(selected) < requested_count,
    )
