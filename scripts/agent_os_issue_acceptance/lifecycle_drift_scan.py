from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

MAX_DRIFT_CANDIDATES = 50


@dataclass(frozen=True, slots=True)
class LifecycleDriftEvidence:
    issue_number: int
    issue_state: str
    lifecycle_stage: str
    labels: tuple[str, ...] = ()
    conflicting_primary_claim: bool = False
    parent_or_meta: bool = False
    stale: bool = False


@dataclass(frozen=True, slots=True)
class LifecycleDriftCandidate:
    issue_number: int
    reason_code: str


@dataclass(frozen=True, slots=True)
class LifecycleDriftScanResult:
    candidates: tuple[LifecycleDriftCandidate, ...]
    outstanding_count: int
    excluded_issue_numbers: tuple[int, ...]
    side_effects_performed: bool = False


def scan_lifecycle_drift(evidence: Iterable[LifecycleDriftEvidence], *, limit: int = MAX_DRIFT_CANDIDATES) -> LifecycleDriftScanResult:
    if type(limit) is not int or limit < 1 or limit > MAX_DRIFT_CANDIDATES:
        raise ValueError("limit is outside the bounded drift-scan range")
    candidates = []
    excluded = []
    for item in sorted(tuple(evidence), key=lambda value: value.issue_number):
        if item.conflicting_primary_claim or item.parent_or_meta or item.stale:
            excluded.append(item.issue_number)
            continue
        reason = None
        if item.issue_state == "open" and item.lifecycle_stage == "merged":
            reason = "reconciliation.merged-pr-open-issue"
        elif item.issue_state == "closed" and any(label.startswith("status:") for label in item.labels):
            reason = "reconciliation.closed-with-ready-label"
        if reason is not None:
            candidates.append(LifecycleDriftCandidate(item.issue_number, reason))
    selected = tuple(candidates[:limit])
    return LifecycleDriftScanResult(selected, max(0, len(candidates) - len(selected)), tuple(sorted(excluded)))
