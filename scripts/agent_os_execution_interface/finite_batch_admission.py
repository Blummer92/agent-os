from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


@dataclass(frozen=True, slots=True)
class FiniteBatchAdmission:
    requested_count: int
    delivered_count: int
    reconciled_candidate_count: int
    population_exhausted: bool
    shared_blocker: bool
    completion_admissible: bool
    next_action: str
    reason_codes: tuple[str, ...]
    mutation_authorized: Literal[False] = field(default=False, init=False)


def evaluate_finite_batch_admission(
    *,
    requested_count: int,
    delivered_count: int,
    reconciled_candidate_count: int,
    population_exhausted: bool,
    shared_blocker: bool,
) -> FiniteBatchAdmission:
    for name, value in (
        ("requested_count", requested_count),
        ("delivered_count", delivered_count),
        ("reconciled_candidate_count", reconciled_candidate_count),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if requested_count < 1:
        raise ValueError("requested_count must be positive")
    if delivered_count > requested_count:
        raise ValueError("delivered_count cannot exceed requested_count")
    if type(population_exhausted) is not bool or type(shared_blocker) is not bool:
        raise TypeError("terminal evidence must use built-in bool")

    if delivered_count == requested_count:
        return _result(requested_count, delivered_count, reconciled_candidate_count, population_exhausted, shared_blocker, True, "report-requested-count-delivered", ("requested-count-satisfied",))
    if shared_blocker:
        return _result(requested_count, delivered_count, reconciled_candidate_count, population_exhausted, shared_blocker, True, "report-shared-terminal-blocker-and-shortfall", ("shared-terminal-blocker", "requested-count-shortfall"))
    if population_exhausted:
        return _result(requested_count, delivered_count, reconciled_candidate_count, population_exhausted, shared_blocker, True, "report-proven-population-exhaustion-and-shortfall", ("candidate-population-exhausted", "requested-count-shortfall"))
    return _result(requested_count, delivered_count, reconciled_candidate_count, population_exhausted, shared_blocker, False, "continue-candidate-cursor", ("requested-count-not-satisfied", "population-not-exhausted"))


def _result(requested, delivered, reconciled, exhausted, blocker, admissible, action, reasons):
    return FiniteBatchAdmission(requested, delivered, reconciled, exhausted, blocker, admissible, action, reasons)


class BatchCandidateDisposition(str, Enum):
    """#2602 per-candidate dispositions for the finite batch cursor.

    ``blocked-item-local`` is terminal for exactly one candidate and
    non-terminal for the parent batch: the cursor must advance past it to the
    next admissible candidate. A shared stop is never inherited from one
    candidate's claim -- it is proven only when every remaining candidate
    carries the same canonical blocker key.
    """

    ADMISSIBLE = "admissible"
    DELIVERED = "delivered"
    BLOCKED_ITEM_LOCAL = "blocked-item-local"
    BLOCKED_SHARED = "blocked-shared"


@dataclass(frozen=True, slots=True)
class BatchCandidate:
    """One candidate's disposition evidence in the frozen batch order."""

    candidate_id: str
    disposition: BatchCandidateDisposition
    reason_code: str
    #: Canonical blocker identity, required exactly when disposition is
    #: ``blocked-shared``. Shared stops are proven by key agreement across all
    #: remaining candidates, never by one candidate's assertion.
    shared_blocker_key: str | None = None

    def __post_init__(self) -> None:
        if type(self.candidate_id) is not str or not self.candidate_id.strip():
            raise ValueError("candidate_id must be non-empty exact text")
        if type(self.disposition) is not BatchCandidateDisposition:
            raise TypeError("disposition must be an exact BatchCandidateDisposition")
        if type(self.reason_code) is not str or not self.reason_code.strip():
            raise ValueError("reason_code must be non-empty exact text")
        if self.shared_blocker_key is not None and (
            type(self.shared_blocker_key) is not str
            or not self.shared_blocker_key.strip()
        ):
            raise ValueError("shared_blocker_key must be non-empty exact text when supplied")
        if self.disposition is BatchCandidateDisposition.BLOCKED_SHARED:
            if self.shared_blocker_key is None:
                raise ValueError("blocked-shared requires one canonical shared_blocker_key")
        elif self.shared_blocker_key is not None:
            raise ValueError("shared_blocker_key is evidence only for blocked-shared")


@dataclass(frozen=True, slots=True)
class BatchItemCursorTransition:
    """One explicit item-local-blocker cursor advance for a finite batch (#2602)."""

    admission: FiniteBatchAdmission
    #: Candidates marked non-admissible by an item-local blocker. Exactly these
    #: items are held; every other candidate keeps its own disposition.
    blocked_item_local: tuple[str, ...]
    #: Cursor position: the first still-admissible candidate in the frozen
    #: batch order, or ``None`` when the admission is terminal.
    next_candidate_id: str | None
    #: True only when every remaining candidate carries the same canonical
    #: shared blocker key -- a proven shared stop, never a single claim.
    shared_blocker_proven: bool
    mutation_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.admission) is not FiniteBatchAdmission:
            raise TypeError("admission must be an exact FiniteBatchAdmission")
        if type(self.blocked_item_local) is not tuple:
            raise TypeError("blocked_item_local must be an exact tuple")
        if any(type(item) is not str for item in self.blocked_item_local):
            raise TypeError("blocked_item_local must contain exact text")
        if self.next_candidate_id is not None and (
            type(self.next_candidate_id) is not str or not self.next_candidate_id.strip()
        ):
            raise ValueError("next_candidate_id must be None or non-empty exact text")
        if type(self.shared_blocker_proven) is not bool:
            raise TypeError("shared_blocker_proven must use built-in bool")
        if self.admission.completion_admissible and self.next_candidate_id is not None:
            raise ValueError("a terminal admission must not name a next candidate")


def evaluate_batch_item_cursor(
    *,
    requested_count: int,
    candidates: tuple[BatchCandidate, ...],
) -> BatchItemCursorTransition:
    """Advance the finite batch cursor past item-local blockers (#2602).

    This is the executable form of AGENTS.md rule 7's cursor semantics and the
    repair for the #2602 fresh reproduction (three-item batch #3249/#3250/#3297:
    #3250's item-local material owner decision stopped the batch instead of
    the cursor advancing to the independent lanes).

    The transition is explicit and bounded:

    - an item-local decision/capability blocker marks ONLY that candidate
      non-admissible (``blocked-item-local``) and the cursor advances to the
      next admissible candidate in the frozen batch order;
    - a shared blocker is *proven* only when every remaining candidate carries
      the same canonical ``shared_blocker_key`` and zero candidates remain
      admissible; one candidate's claim never stops the batch;
    - terminal admission is delegated unchanged to
      :func:`evaluate_finite_batch_admission`, so the batch is terminal only
      when the requested count is delivered, the reconciled population is
      exhausted, or a genuine shared blocker is proven.

    No router, Scheduler, executor authority, writer, retry engine, or state
    store is introduced; #1237 keeps same-lineage rerouting, #2220 keeps
    mission continuation, #2460 keeps publication fallback safety. Raises
    ``ValueError`` on contradictory blocker evidence (fail closed).
    """
    if type(requested_count) is not int or requested_count < 1:
        raise ValueError("requested_count must be a positive built-in integer")
    if type(candidates) is not tuple or not candidates:
        raise ValueError("candidates must be a non-empty tuple")
    if any(type(item) is not BatchCandidate for item in candidates):
        raise TypeError("candidates must contain exact BatchCandidate evidence")

    candidate_ids = tuple(item.candidate_id for item in candidates)
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("each candidate may be dispositioned at most once per cursor")

    shared = tuple(
        item
        for item in candidates
        if item.disposition is BatchCandidateDisposition.BLOCKED_SHARED
    )
    shared_keys = {item.shared_blocker_key for item in shared}
    if len(shared_keys) > 1:
        raise ValueError(
            "blocked-shared evidence carries conflicting blocker keys; no canonical "
            "shared blocker is proven"
        )

    delivered = tuple(
        item.candidate_id
        for item in candidates
        if item.disposition is BatchCandidateDisposition.DELIVERED
    )
    admissible = tuple(
        item
        for item in candidates
        if item.disposition is BatchCandidateDisposition.ADMISSIBLE
    )
    blocked_item_local = tuple(
        item.candidate_id
        for item in candidates
        if item.disposition is BatchCandidateDisposition.BLOCKED_ITEM_LOCAL
    )
    # A shared blocker is proven across ALL remaining candidates, never from
    # one item's claim: every non-delivered candidate must carry the same
    # canonical key and zero candidates may remain admissible.
    shared_blocker_proven = bool(shared) and not admissible
    population_exhausted = not admissible

    admission = evaluate_finite_batch_admission(
        requested_count=requested_count,
        delivered_count=len(delivered),
        reconciled_candidate_count=len(candidates) - len(admissible),
        population_exhausted=population_exhausted,
        shared_blocker=shared_blocker_proven,
    )

    next_candidate_id = admissible[0].candidate_id if admissible else None
    return BatchItemCursorTransition(
        admission=admission,
        blocked_item_local=blocked_item_local,
        next_candidate_id=next_candidate_id,
        shared_blocker_proven=shared_blocker_proven,
    )
