"""Deterministic duplicate reconciliation for visual-asset intake evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .models import AssetIntakeResult

_HEX_DIGITS = frozenset("0123456789abcdef")


class DuplicateDisposition(str, Enum):
    EXACT_EXISTING = "EXACT_EXISTING"
    NORMALIZED_EXISTING = "NORMALIZED_EXISTING"
    NO_DUPLICATE_FOUND = "NO_DUPLICATE_FOUND"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    stable_identity: str
    original_sha256: str | None = None
    normalized_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class DuplicateReconciliationResult:
    disposition: DuplicateDisposition
    matched_identity: str | None
    matched_candidate_count: int
    reason_codes: tuple[str, ...]
    execution_authorized: bool = False
    external_write_authorized: bool = False
    approval_authorized: bool = False
    classroom_readiness_authorized: bool = False
    production_authorized: bool = False


def reconcile_duplicate(
    intake_result: AssetIntakeResult,
    candidates: Iterable[DuplicateCandidate],
) -> DuplicateReconciliationResult:
    """Reconcile exact/normalized duplicate evidence without assigning identity."""
    try:
        received = tuple(candidates)
    except TypeError:
        return _invalid()
    if any(type(item) is not DuplicateCandidate or not _valid_candidate(item) for item in received):
        return _invalid()
    ordered = tuple(sorted(received, key=lambda item: item.stable_identity))

    exact = tuple(item for item in ordered if item.original_sha256 == intake_result.original_sha256)
    if exact:
        return _matched(exact, DuplicateDisposition.EXACT_EXISTING, "duplicate-exact-original")

    normalized = tuple(item for item in ordered if item.normalized_sha256 == intake_result.normalized_sha256)
    if normalized:
        return _matched(normalized, DuplicateDisposition.NORMALIZED_EXISTING, "duplicate-exact-normalized")

    return _result(DuplicateDisposition.NO_DUPLICATE_FOUND, None, 0, ("duplicate-no-exact-match",))


def _valid_candidate(candidate: DuplicateCandidate) -> bool:
    return (
        type(candidate.stable_identity) is str
        and bool(candidate.stable_identity.strip())
        and _valid_sha(candidate.original_sha256)
        and _valid_sha(candidate.normalized_sha256)
    )


def _valid_sha(value: str | None) -> bool:
    return value is None or (
        type(value) is str and len(value) == 64 and all(character in _HEX_DIGITS for character in value)
    )


def _invalid() -> DuplicateReconciliationResult:
    return _result(DuplicateDisposition.INVALID, None, 0, ("duplicate-candidate-invalid",))


def _matched(
    candidates: tuple[DuplicateCandidate, ...],
    disposition: DuplicateDisposition,
    reason: str,
) -> DuplicateReconciliationResult:
    identities = tuple(sorted({item.stable_identity for item in candidates}))
    if len(identities) != 1:
        return _result(
            DuplicateDisposition.MANUAL_REVIEW_REQUIRED,
            None,
            len(candidates),
            ("duplicate-conflicting-stable-identities", reason),
        )
    return _result(disposition, identities[0], len(candidates), (reason,))


def _result(
    disposition: DuplicateDisposition,
    matched_identity: str | None,
    matched_candidate_count: int,
    reason_codes: tuple[str, ...],
) -> DuplicateReconciliationResult:
    return DuplicateReconciliationResult(
        disposition=disposition,
        matched_identity=matched_identity,
        matched_candidate_count=matched_candidate_count,
        reason_codes=reason_codes,
    )
