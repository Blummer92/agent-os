"""Pure-local pre-merge evidence classifier for one batch-canary candidate.

Classifies already-read, normalized evidence about a single merge candidate
into a closed-vocabulary disposition. It performs no retrieval, validation,
merge, scheduling, repair, or external mutation -- the same philosophy as
``batch_repair_continuation.py`` ("performs no retrieval, repair, scheduling,
validation, merge...").

This module does NOT duplicate ``merge_authorization.py`` (which owns
authorization records) or ``finite_batch_admission.py`` (which owns batch
counts): it classifies evidence freshness/readiness only. Callers supply the
evidence; the classifier decides only what the next bounded action is, and
never authorizes a merge.

Soft-absorbs the bounded-behavior evidence behind #3402 (mergeability
transient-false: bounded re-read, never treat a single false as terminal) and
#3431 (validation in_progress: bounded poll wait, never merge early and never
stop terminally). The issues stay open; nothing here closes them.

Disposition precedence (first match wins; fail-closed throughout):

1. PR closed -> ``blocked_item_local`` (``pr-closed``)
2. PR draft -> ``blocked_item_local`` (``pr-not-ready``)
3. Head SHA moved between reads -> ``blocked_item_local`` (``head-sha-changed``);
   stale evidence must never proceed.
4. A check is failing -> ``blocked_item_local`` (``checks-failing``)
5. Aggregate failed -> ``blocked_item_local`` (``aggregate-failed``)
6. Aggregate state unknown -> ``blocked_item_local`` (``aggregate-state-unknown``)
7. Aggregate in_progress and poll budget remains -> ``wait_reacquire_validation``
   (``validation-in-progress``); poll budget exhausted -> ``ceiling_exceeded``
   (``validation-poll-budget-exhausted``)
8. Aggregate success:
   - mergeable=true -> ``proceed`` (``all-evidence-green``)
   - mergeable=false and re-read budget remains -> ``reread_mergeability``
     (``mergeability-false-transient``); budget exhausted -> ``blocked_item_local``
     (``mergeability-false-persistent``): re-reads proved the false, so the
     item is blocked locally, not the loop.
   - mergeable=None (not yet computed) and re-read budget remains ->
     ``reread_mergeability`` (``mergeability-state-unknown``); budget
     exhausted -> ``ceiling_exceeded`` (``mergeability-reacquire-budget-
     exhausted``): the bounded loop produced no verdict, so the loop stops
     fail-closed with precise evidence.

Closed vocabularies: ``DISPOSITIONS`` and ``REASON_CODES``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class MergeCandidateDisposition(str, Enum):
    PROCEED = "proceed"
    WAIT_REACQUIRE_VALIDATION = "wait_reacquire_validation"
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
        "validation-in-progress",
        "validation-poll-budget-exhausted",
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
    ``polls_remaining`` bounds validation-run polls (#3431). ``mergeable``
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
        if evidence.polls_remaining > 0:
            return _classified(
                evidence,
                MergeCandidateDisposition.WAIT_REACQUIRE_VALIDATION,
                "validation-in-progress",
            )
        return _classified(
            evidence,
            MergeCandidateDisposition.CEILING_EXCEEDED,
            "validation-poll-budget-exhausted",
        )

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
