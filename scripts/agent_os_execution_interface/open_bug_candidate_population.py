"""Open-only bounded bug candidate population for finite implementation batches (#2609).

This module is a pure projection over canonical GitHub issue snapshots supplied by
the existing host/provider. It owns no retrieval, cache, scheduler, readiness,
authorization, mutation, or persistence. Closed history is rejected before lane
selection and may only be consumed separately as supporting lineage evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class OpenBugCandidate:
    issue_number: int
    title: str
    state: Literal["open"] = field(default="open", init=False)


@dataclass(frozen=True, slots=True)
class OpenBugCandidatePopulation:
    requested_count: int
    open_candidates: tuple[OpenBugCandidate, ...]
    rejected_closed_issue_numbers: tuple[int, ...]
    rejected_unknown_issue_numbers: tuple[int, ...]
    population_shortfall: int
    population_exhausted: bool
    mutation_authorized: Literal[False] = field(default=False, init=False)


def build_open_bug_candidate_population(
    *,
    requested_count: int,
    canonical_issue_snapshots: Sequence[Mapping[str, object]],
) -> OpenBugCandidatePopulation:
    """Select at most ``requested_count`` canonical open bug snapshots.

    Callers must enumerate from GitHub's open issue population first. This
    defense-in-depth projection still rejects a candidate that closed between
    enumeration and canonical readback. It never substitutes closed history or
    unknown state to pad the requested count.
    """
    if type(requested_count) is not int or requested_count < 1:
        raise ValueError("requested_count must be a positive built-in integer")
    if not isinstance(canonical_issue_snapshots, Sequence) or isinstance(
        canonical_issue_snapshots, (str, bytes)
    ):
        raise TypeError("canonical_issue_snapshots must be a sequence")

    selected: list[OpenBugCandidate] = []
    closed: list[int] = []
    unknown: list[int] = []
    seen: set[int] = set()

    for snapshot in canonical_issue_snapshots:
        if not isinstance(snapshot, Mapping):
            raise TypeError("each canonical issue snapshot must be a mapping")
        number = _issue_number(snapshot.get("issue_number"))
        if number in seen:
            raise ValueError("canonical issue snapshots must be unique")
        seen.add(number)
        state = snapshot.get("state")
        if state == "closed":
            closed.append(number)
            continue
        if state != "open":
            unknown.append(number)
            continue
        if not _is_bug(snapshot):
            continue
        if len(selected) < requested_count:
            selected.append(OpenBugCandidate(number, _title(snapshot.get("title"))))

    shortfall = max(0, requested_count - len(selected))
    return OpenBugCandidatePopulation(
        requested_count=requested_count,
        open_candidates=tuple(selected),
        rejected_closed_issue_numbers=tuple(closed),
        rejected_unknown_issue_numbers=tuple(unknown),
        population_shortfall=shortfall,
        population_exhausted=shortfall > 0,
    )


def _is_bug(snapshot: Mapping[str, object]) -> bool:
    labels = snapshot.get("labels", ())
    if type(labels) not in (list, tuple):
        return False
    normalized: set[str] = set()
    for value in labels:
        if type(value) is str:
            normalized.add(value)
        elif isinstance(value, Mapping) and type(value.get("name")) is str:
            normalized.add(str(value["name"]))
    return "type:bug" in normalized


def _issue_number(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("issue_number must be a positive built-in integer")
    return value


def _title(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("title must be non-empty text")
    return value.strip()


__all__ = [
    "OpenBugCandidate",
    "OpenBugCandidatePopulation",
    "build_open_bug_candidate_population",
]
