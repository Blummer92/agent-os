"""Pure-local continuation projection for a finite bulk PR repair batch.

This module records per-candidate dispositions and delegates terminal admission to
the existing finite-batch contract. It performs no retrieval, repair, scheduling,
validation, merge, lesson selection, or external mutation.

Failed repair retries remain owned by the existing CKR6 failed-repair lesson
re-entry seam. This projection only accepts caller-supplied evidence that the
current failed attempt's retry boundary admitted another mutation; it never
reimplements lesson retrieval or mutation authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from scripts.agent_os_execution_interface.finite_batch_admission import (
    FiniteBatchAdmission,
    evaluate_finite_batch_admission,
)


class RepairDisposition(str, Enum):
    REPAIRED = "repaired"
    BLOCKED = "blocked"
    DEFERRED = "deferred"
    REACQUIRE = "reacquire"
    ALREADY_TERMINAL = "already-terminal"


@dataclass(frozen=True, slots=True)
class RepairCandidateEvidence:
    pull_request_number: int
    disposition: RepairDisposition
    reason_code: str
    shared_blocker: bool = False
    failed_repair_attempt_id: str | None = None
    retry_lesson_boundary_admitted: bool = False

    def __post_init__(self) -> None:
        if type(self.pull_request_number) is not int or self.pull_request_number < 1:
            raise ValueError("pull_request_number must be a positive integer")
        if type(self.disposition) is not RepairDisposition:
            raise TypeError("disposition must be RepairDisposition")
        if type(self.reason_code) is not str or not self.reason_code.strip():
            raise ValueError("reason_code must be non-empty")
        if type(self.shared_blocker) is not bool:
            raise TypeError("shared_blocker must use built-in bool")
        if self.failed_repair_attempt_id is not None:
            if type(self.failed_repair_attempt_id) is not str or not self.failed_repair_attempt_id.strip():
                raise ValueError("failed_repair_attempt_id must be a non-empty string when supplied")
        if type(self.retry_lesson_boundary_admitted) is not bool:
            raise TypeError("retry_lesson_boundary_admitted must use built-in bool")
        if self.retry_lesson_boundary_admitted and self.failed_repair_attempt_id is None:
            raise ValueError("retry lesson admission must bind to one failed repair attempt")
        if (
            self.disposition is RepairDisposition.REPAIRED
            and self.failed_repair_attempt_id is not None
            and not self.retry_lesson_boundary_admitted
        ):
            raise ValueError(
                "failed repair retry cannot be recorded as repaired before CKR6 retry lesson boundary admission"
            )


@dataclass(frozen=True, slots=True)
class BulkRepairContinuation:
    requested_pull_requests: tuple[int, ...]
    visited_pull_requests: tuple[int, ...]
    repaired_pull_requests: tuple[int, ...]
    blocked_pull_requests: tuple[int, ...]
    deferred_pull_requests: tuple[int, ...]
    reacquire_pull_requests: tuple[int, ...]
    already_terminal_pull_requests: tuple[int, ...]
    lesson_reentry_pull_requests: tuple[int, ...]
    remaining_pull_requests: tuple[int, ...]
    evidence: tuple[RepairCandidateEvidence, ...]
    finite_admission: FiniteBatchAdmission
    next_action: str
    mutation_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def evaluate_bulk_repair_continuation(
    *,
    requested_pull_requests: tuple[int, ...],
    evidence: tuple[RepairCandidateEvidence, ...],
) -> BulkRepairContinuation:
    requested = _targets(requested_pull_requests)
    if type(evidence) is not tuple or any(type(item) is not RepairCandidateEvidence for item in evidence):
        raise TypeError("evidence must be a tuple of RepairCandidateEvidence")

    visited = tuple(item.pull_request_number for item in evidence)
    if len(set(visited)) != len(visited):
        raise ValueError("each PR may be dispositioned at most once per projection")
    if any(number not in requested for number in visited):
        raise ValueError("evidence contains a PR outside the frozen target set")

    shared = tuple(item for item in evidence if item.shared_blocker)
    if len(shared) > 1:
        raise ValueError("at most one current shared blocker may terminate the projection")

    repaired = _by_disposition(evidence, RepairDisposition.REPAIRED)
    blocked = _by_disposition(evidence, RepairDisposition.BLOCKED)
    deferred = _by_disposition(evidence, RepairDisposition.DEFERRED)
    reacquire = _by_disposition(evidence, RepairDisposition.REACQUIRE)
    terminal = _by_disposition(evidence, RepairDisposition.ALREADY_TERMINAL)
    lesson_reentry = tuple(
        item.pull_request_number
        for item in evidence
        if item.failed_repair_attempt_id is not None
    )
    remaining = tuple(number for number in requested if number not in set(visited))

    admission = evaluate_finite_batch_admission(
        requested_count=len(requested),
        delivered_count=len(visited),
        reconciled_candidate_count=len(visited),
        population_exhausted=not remaining,
        shared_blocker=bool(shared),
    )

    if shared:
        next_action = "halt-shared-blocker"
    elif remaining:
        next_action = "reacquire-next-candidate"
    elif deferred or reacquire:
        next_action = "revisit-deferred-or-stale-candidates"
    else:
        next_action = "report-complete-repair-batch"

    return BulkRepairContinuation(
        requested,
        visited,
        repaired,
        blocked,
        deferred,
        reacquire,
        terminal,
        lesson_reentry,
        remaining,
        evidence,
        admission,
        next_action,
    )


def _targets(values: tuple[int, ...]) -> tuple[int, ...]:
    if type(values) is not tuple or not values:
        raise ValueError("requested_pull_requests must be a non-empty tuple")
    if any(type(value) is not int or value < 1 for value in values):
        raise ValueError("requested_pull_requests must contain positive integers")
    if len(set(values)) != len(values):
        raise ValueError("requested_pull_requests must be unique")
    return values


def _by_disposition(
    evidence: tuple[RepairCandidateEvidence, ...], disposition: RepairDisposition
) -> tuple[int, ...]:
    return tuple(item.pull_request_number for item in evidence if item.disposition is disposition)
