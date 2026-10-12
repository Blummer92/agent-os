"""Pure-local pre-merge mergeability evidence classifier for #3402.

Normalizes already-read candidate evidence into bounded, fail-closed
dispositions. The caller performs all actual re-reads, merge admission,
authorization, validation, and other I/O. This module performs none.
This foundational classifier does not implement validation polling.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class MergeCandidateDisposition(str, Enum):
    PROCEED = "proceed"
    REREAD_MERGEABILITY = "reread_mergeability"
    BLOCKED_ITEM_LOCAL = "blocked_item_local"
    CEILING_EXCEEDED = "ceiling_exceeded"


DISPOSITIONS = frozenset(disposition.value for disposition in MergeCandidateDisposition)

REASON_CODES = frozenset(
    {
        "pr-closed",
        "pr-not-ready",
        "head-sha-changed",
        "checks-failing",
        "aggregate-failed",
        "aggregate-state-unknown",
        "aggregate-not-terminal",
        "mergeability-false-transient",
        "mergeability-false-persistent",
        "mergeability-state-unknown",
        "mergeability-reacquire-budget-exhausted",
        "all-evidence-green",
    }
)

AggregateState = Literal["success", "in_progress", "failed", "unknown"]
_AGGREGATE_STATES = frozenset({"success", "in_progress", "failed", "unknown"})


@dataclass(frozen=True, slots=True)
class MergeCandidateEvidence:
    """Normalized pre-merge evidence for one batch-canary candidate.

    ``reacquires_remaining`` bounds mergeability re-reads (#3402);
    ``polls_remaining`` is an unused input reserved for follow-on validation.
    ``mergeable``
    is None when the provider has not computed it yet. ``head_sha_stable``
    is False when a later read observed a different head SHA, making this
    evidence stale.
    """

    pr_open: bool
    is_draft: bool
    mergeable: bool | None
    aggregate: AggregateState
    head_sha: str
    head_sha_stable: bool
    checks_failing: bool
    reacquires_remaining: int
    polls_remaining: int

    def __post_init__(self) -> None:
        if type(self.pr_open) is not bool:
            raise TypeError("pr_open must use built-in bool")
        if type(self.is_draft) is not bool:
            raise TypeError("is_draft must use built-in bool")
        if self.mergeable is not None and type(self.mergeable) is not bool:
            raise TypeError("mergeable must be built-in bool or None")
        if type(self.aggregate) is not str or self.aggregate not in _AGGREGATE_STATES:
            raise ValueError(
                "aggregate must be one of 'success', 'in_progress', 'failed', 'unknown'"
            )
        if type(self.head_sha) is not str or not self.head_sha.strip():
            raise ValueError("head_sha must be a non-empty string")
        if type(self.head_sha_stable) is not bool:
            raise TypeError("head_sha_stable must use built-in bool")
        if type(self.checks_failing) is not bool:
            raise TypeError("checks_failing must use built-in bool")
        if type(self.reacquires_remaining) is not int:
            raise TypeError("reacquires_remaining must use built-in int")
        if self.reacquires_remaining < 0:
            raise ValueError("reacquires_remaining must be non-negative")
        if type(self.polls_remaining) is not int:
            raise TypeError("polls_remaining must use built-in int")
        if self.polls_remaining < 0:
            raise ValueError("polls_remaining must be non-negative")


@dataclass(frozen=True, slots=True)
class MergeCandidateClassification:
    """The disposition for one classification of one candidate's evidence."""

    disposition: MergeCandidateDisposition
    reason_codes: tuple[str, ...]
    head_sha: str

    def __post_init__(self) -> None:
        if type(self.disposition) is not MergeCandidateDisposition:
            raise TypeError("disposition must be MergeCandidateDisposition")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty tuple")
        if any(type(code) is not str or code not in REASON_CODES for code in self.reason_codes):
            raise ValueError("reason_codes must use the closed REASON_CODES vocabulary")
        if type(self.head_sha) is not str or not self.head_sha.strip():
            raise ValueError("head_sha must be a non-empty string")


def classify_merge_candidate_evidence(
    evidence: MergeCandidateEvidence,
) -> MergeCandidateClassification:
    """Classify one candidate's pre-merge evidence into a disposition.

    Pure function: deterministic, no I/O, no retrieval, no mutation, and no
    merge authorization. Callers re-read fresh evidence and classify again
    for each bounded wait or re-read step.
    """
    if type(evidence) is not MergeCandidateEvidence:
        raise TypeError("evidence must be MergeCandidateEvidence")

    if not evidence.pr_open:
        return _blocked(evidence, "pr-closed")
    if evidence.is_draft:
        return _blocked(evidence, "pr-not-ready")
    if not evidence.head_sha_stable:
        return _blocked(evidence, "head-sha-changed")
    if evidence.checks_failing:
        return _blocked(evidence, "checks-failing")
    if evidence.aggregate == "failed":
        return _blocked(evidence, "aggregate-failed")
    if evidence.aggregate == "unknown":
        return _blocked(evidence, "aggregate-state-unknown")
    if evidence.aggregate == "in_progress":
        return _blocked(evidence, "aggregate-not-terminal")

    # aggregate == "success" from here on.
    if evidence.mergeable is True:
        return _classified(evidence, MergeCandidateDisposition.PROCEED, "all-evidence-green")
    if evidence.mergeable is False:
        if evidence.reacquires_remaining > 0:
            return _classified(
                evidence,
                MergeCandidateDisposition.REREAD_MERGEABILITY,
                "mergeability-false-transient",
            )
        # Re-reads proved the false: the item is blocked locally.
        return _blocked(evidence, "mergeability-false-persistent")
    # mergeable is None: the provider has not computed it yet.
    if evidence.reacquires_remaining > 0:
        return _classified(
            evidence,
            MergeCandidateDisposition.REREAD_MERGEABILITY,
            "mergeability-state-unknown",
        )
    return _classified(
        evidence,
        MergeCandidateDisposition.CEILING_EXCEEDED,
        "mergeability-reacquire-budget-exhausted",
    )


def _blocked(evidence: MergeCandidateEvidence, reason_code: str) -> MergeCandidateClassification:
    return _classified(evidence, MergeCandidateDisposition.BLOCKED_ITEM_LOCAL, reason_code)


def _classified(
    evidence: MergeCandidateEvidence,
    disposition: MergeCandidateDisposition,
    reason_code: str,
) -> MergeCandidateClassification:
    return MergeCandidateClassification(
        disposition=disposition,
        reason_codes=(reason_code,),
        head_sha=evidence.head_sha,
    )
