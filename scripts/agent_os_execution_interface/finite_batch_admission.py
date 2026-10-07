from __future__ import annotations

from dataclasses import dataclass, field
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
