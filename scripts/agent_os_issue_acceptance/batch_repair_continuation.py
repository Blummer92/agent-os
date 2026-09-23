"""Pure-local continuation projection for a finite bulk PR repair batch.

This module records per-candidate dispositions and delegates terminal admission to
the existing finite-batch contract. It performs no retrieval, repair, scheduling,
validation, merge, lesson selection, or external mutation.

Failed repair retries remain owned by the existing CKR6 failed-repair lesson
re-entry seam. This projection consumes normalized evidence matching the canonical
``RepairRetryBoundaryPlan`` shape for the exact failed attempt; it never
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
class RepairRetryBoundaryEvidence:
    """Normalized evidence from the canonical CKR6 RepairRetryBoundaryPlan."""

    failed_attempt_id: str
    mutation_admissible: bool
    blocking_attempt_id: str | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.failed_attempt_id) is not str or not self.failed_attempt_id.strip():
            raise ValueError("failed_attempt_id must be a non-empty string")
        if type(self.mutation_admissible) is not bool:
            raise TypeError("mutation_admissible must use built-in bool")
        if self.blocking_attempt_id is not None and (
            type(self.blocking_attempt_id) is not str or not self.blocking_attempt_id.strip()
        ):
            raise ValueError("blocking_attempt_id must be a non-empty string when supplied")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty tuple")
        if any(type(code) is not str or not code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must contain non-empty strings")
        if self.mutation_admissible and self.blocking_attempt_id is not None:
            raise ValueError("admitted retry boundary cannot retain a blocking attempt")
        if not self.mutation_admissible and self.blocking_attempt_id != self.failed_attempt_id:
            raise ValueError("blocked retry boundary must identify the exact failed attempt")


@dataclass(frozen=True, slots=True)
class RepairCandidateEvidence:
    pull_request_number: int
    disposition: RepairDisposition
    reason_code: str
    shared_blocker: bool = False
    failed_repair_attempt_id: str | None = None
    retry_boundary: RepairRetryBoundaryEvidence | None = None
    retry_mutation_performed: bool = False
    shared_blocker_key: str | None = None
    shared_repair_owner: str | None = None
    shared_repair_available: bool = False
    shared_repair_completed: bool = False

    def __post_init__(self) -> None:
        if type(self.pull_request_number) is not int or self.pull_request_number < 1:
            raise ValueError("pull_request_number must be a positive integer")
        if type(self.disposition) is not RepairDisposition:
            raise TypeError("disposition must be RepairDisposition")
        if type(self.reason_code) is not str or not self.reason_code.strip():
            raise ValueError("reason_code must be non-empty")
        if type(self.shared_blocker) is not bool:
            raise TypeError("shared_blocker must use built-in bool")
        if type(self.retry_mutation_performed) is not bool:
            raise TypeError("retry_mutation_performed must use built-in bool")
        if type(self.shared_repair_available) is not bool:
            raise TypeError("shared_repair_available must use built-in bool")
        if type(self.shared_repair_completed) is not bool:
            raise TypeError("shared_repair_completed must use built-in bool")
        if self.failed_repair_attempt_id is not None and (
            type(self.failed_repair_attempt_id) is not str or not self.failed_repair_attempt_id.strip()
        ):
            raise ValueError("failed_repair_attempt_id must be a non-empty string when supplied")
        if self.retry_boundary is not None and type(self.retry_boundary) is not RepairRetryBoundaryEvidence:
            raise TypeError("retry_boundary must be RepairRetryBoundaryEvidence or None")
        if self.retry_boundary is not None:
            if self.failed_repair_attempt_id is None:
                raise ValueError("retry boundary must bind to one failed repair attempt")
            if self.retry_boundary.failed_attempt_id != self.failed_repair_attempt_id:
                raise ValueError("retry boundary must bind to the exact failed repair attempt")
        if self.retry_mutation_performed:
            if self.failed_repair_attempt_id is None or self.retry_boundary is None:
                raise ValueError("retry mutation requires exact failed-attempt CKR6 boundary evidence")
            if not self.retry_boundary.mutation_admissible:
                raise ValueError("retry mutation cannot occur while CKR6 retry boundary blocks mutation")
        if self.disposition is RepairDisposition.REPAIRED and self.failed_repair_attempt_id is not None:
            if not self.retry_mutation_performed:
                raise ValueError("failed repair cannot become repaired without an admitted retry mutation")

        shared_metadata_present = (
            self.shared_blocker_key is not None
            or self.shared_repair_owner is not None
            or self.shared_repair_available
            or self.shared_repair_completed
        )
        if not self.shared_blocker and shared_metadata_present:
            raise ValueError("shared repair metadata requires shared_blocker=true")
        if self.shared_blocker_key is not None and (
            type(self.shared_blocker_key) is not str or not self.shared_blocker_key.strip()
        ):
            raise ValueError("shared_blocker_key must be a non-empty string when supplied")
        if self.shared_repair_owner is not None and (
            type(self.shared_repair_owner) is not str or not self.shared_repair_owner.strip()
        ):
            raise ValueError("shared_repair_owner must be a non-empty string when supplied")
        if self.shared_repair_completed and not self.shared_repair_available:
            raise ValueError("completed shared repair must remain available as canonical repair evidence")
        if self.shared_repair_available and (
            self.shared_blocker_key is None or self.shared_repair_owner is None
        ):
            raise ValueError(
                "repairable shared blocker requires shared_blocker_key and shared_repair_owner"
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
    lesson_reentry_required_pull_requests: tuple[int, ...]
    lesson_reentry_admitted_pull_requests: tuple[int, ...]
    lesson_reentry_blocked_pull_requests: tuple[int, ...]
    shared_blocker_pull_requests: tuple[int, ...]
    shared_blocker_key: str | None
    shared_repair_owner: str | None
    shared_repair_available: bool
    shared_repair_completed: bool
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
    shared_signature: tuple[str | None, str | None, bool, bool] | None = None
    if shared:
        signatures = {
            (
                item.shared_blocker_key,
                item.shared_repair_owner,
                item.shared_repair_available,
                item.shared_repair_completed,
            )
            for item in shared
        }
        if len(signatures) != 1:
            raise ValueError(
                "all current shared blockers must identify one canonical blocker and repair state"
            )
        shared_signature = next(iter(signatures))

    repaired = _by_disposition(evidence, RepairDisposition.REPAIRED)
    blocked = _by_disposition(evidence, RepairDisposition.BLOCKED)
    deferred = _by_disposition(evidence, RepairDisposition.DEFERRED)
    reacquire = _by_disposition(evidence, RepairDisposition.REACQUIRE)
    terminal = _by_disposition(evidence, RepairDisposition.ALREADY_TERMINAL)
    lesson_required = tuple(
        item.pull_request_number
        for item in evidence
        if item.failed_repair_attempt_id is not None and item.retry_boundary is None
    )
    lesson_admitted = tuple(
        item.pull_request_number
        for item in evidence
        if item.retry_boundary is not None and item.retry_boundary.mutation_admissible
    )
    lesson_blocked = tuple(
        item.pull_request_number
        for item in evidence
        if item.retry_boundary is not None and not item.retry_boundary.mutation_admissible
    )
    shared_pull_requests = tuple(item.pull_request_number for item in shared)
    shared_blocker_key = shared_signature[0] if shared_signature is not None else None
    shared_repair_owner = shared_signature[1] if shared_signature is not None else None
    shared_repair_available = shared_signature[2] if shared_signature is not None else False
    shared_repair_completed = shared_signature[3] if shared_signature is not None else False
    repairable_shared_blocker = bool(shared) and shared_repair_available
    terminal_shared_blocker = bool(shared) and not shared_repair_available
    remaining = tuple(number for number in requested if number not in set(visited))

    # A candidate parked on a repairable shared blocker is reconciled but not
    # delivered: the batch still owes it the shared repair and a revalidation
    # pass, so it must not count toward the requested delivery total. Without
    # this, `delivered_count == requested_count` short-circuits
    # `evaluate_finite_batch_admission` to `completion_admissible=True` before
    # `population_exhausted` is ever consulted, which would report a batch whose
    # next action is still `advance-shared-repair` as complete.
    shared_pending = shared_pull_requests if repairable_shared_blocker else ()

    # The same reasoning covers every candidate-local disposition, which the
    # subtraction above did not reach: blocked, deferred, reacquire, and
    # already-terminal candidates advance traversal and deliver nothing. Reading
    # `delivered_count` off `visited` made a batch of three item-local blocks
    # report `requested-count-satisfied` with nothing repaired (#2349). Count
    # what was delivered instead of subtracting from what was seen.
    delivered = tuple(number for number in repaired if number not in set(shared_pending))

    # Deferred and reacquire candidates still carry an executable next action,
    # so the bounded population is not exhausted while any remain. The loop's
    # own terminal chain below already says `revisit-deferred-or-stale-
    # candidates` for exactly this state; binding exhaustion to the same
    # evidence stops the canonical owner from contradicting it.
    admission = evaluate_finite_batch_admission(
        requested_count=len(requested),
        delivered_count=len(delivered),
        reconciled_candidate_count=len(visited),
        population_exhausted=(
            not remaining
            and not repairable_shared_blocker
            and not deferred
            and not reacquire
        ),
        shared_blocker=terminal_shared_blocker,
    )

    if repairable_shared_blocker and shared_repair_completed:
        next_action = "reacquire-shared-repair-candidates"
    elif repairable_shared_blocker:
        next_action = "advance-shared-repair"
    elif terminal_shared_blocker:
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
        lesson_required,
        lesson_admitted,
        lesson_blocked,
        shared_pull_requests,
        shared_blocker_key,
        shared_repair_owner,
        shared_repair_available,
        shared_repair_completed,
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
