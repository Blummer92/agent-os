"""Shared satisfaction-snapshot validation core (#3680 Option B; #3690 CR-1).

The satisfaction record is produced by the reporting domain
(``criterion_satisfaction``), which approval-domain modules must not import
(architecture dependency-direction contract). The producer therefore hands
over a plain mapping of exactly::

    {repository, issue_number, issue_body_digest, status,
     criteria: [{index, identity, disposition, reason_code, evidence}]}

This module is the single strict validator for that mapping. Its two
approval-domain consumers — ``lifecycle_reconciliation`` (post-merge
reporting) and ``closure_admission_actions`` (the closure judgment packet)
— previously carried copies of this code with identical validation rules
and messages (the closure copy lacked only the read-only
``unsatisfied_criteria`` convenience property), pinned together only by a
cross-module consistency test. #3690 CR-1 consolidates the
validation core here. Each consumer keeps its own serializer and its own
trust boundary: the reconciliation block adds the ``closure_ready``
reporting signal; the closure receipt block does not (its exact key set is
part of the hashed receipt core). Neither serializer lives here.

Validation rules (unchanged from the consolidated copies):

* key sets are exact; types are exact built-ins (a bool is not an index or
  an issue number; criteria and evidence must be exact lists on the mapping
  path and exact tuples on the frozen classes);
* the digest is a 64-char lowercase hex string; criterion indexes are
  1..N contiguous, unique, and in order;
* the declared status must equal the status derived from the criteria under
  the #3678 projector's own rule, so a forged or inconsistent ``complete``
  claim is rejected;
* the frozen classes validate their own fields at construction, so an
  already-built instance is necessarily valid and direct construction cannot
  bypass the mapping rules.

The envelope identity (``repository`` / ``issue_number``) is part of the
snapshot; each owning consumer rejects a snapshot naming an issue other than
the authoritative identity it holds. The identity binding detects
cross-issue attachment; it does not authenticate that the criteria or digest
were produced from that issue's body — provenance remains the producer's and
QA's responsibility. A snapshot is evidence for QA judgment only; it never
carries or confers any authorization. This module performs no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "SATISFACTION_CRITERION_KEYS",
    "SATISFACTION_DISPOSITIONS",
    "SATISFACTION_KEYS",
    "SATISFACTION_STATUSES",
    "SatisfactionCriterionSnapshot",
    "SatisfactionSnapshot",
    "derived_satisfaction_status",
    "validate_satisfaction_snapshot",
]

SATISFACTION_STATUSES = frozenset({"complete", "incomplete", "manual-review"})
SATISFACTION_DISPOSITIONS = frozenset({
    "satisfied", "unsatisfied", "stale", "missing", "contradicted",
    "manual-review",
})
SATISFACTION_KEYS = frozenset({
    "repository", "issue_number", "issue_body_digest", "status", "criteria",
})
SATISFACTION_CRITERION_KEYS = frozenset({
    "index", "identity", "disposition", "reason_code", "evidence",
})
_HEX_DIGITS = frozenset("0123456789abcdef")


def derived_satisfaction_status(
    criteria: tuple[SatisfactionCriterionSnapshot, ...],
) -> str:
    """The one status derivation, mirroring the #3678 projector exactly."""
    if not criteria:
        return "manual-review"
    if all(item.disposition == "satisfied" for item in criteria):
        return "complete"
    if any(item.disposition == "manual-review" for item in criteria):
        return "manual-review"
    return "incomplete"


@dataclass(frozen=True, slots=True)
class SatisfactionCriterionSnapshot:
    index: int
    identity: str
    disposition: str
    reason_code: str
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        # Construction itself enforces the per-criterion rules the mapping
        # path applies, so no instance can be inconsistent.
        if type(self.index) is not int:
            raise TypeError("satisfaction criterion index must be a built-in int")
        if self.index < 1:
            raise ValueError("satisfaction criterion index must be positive")
        if type(self.identity) is not str or not self.identity:
            raise TypeError(
                "satisfaction criterion identity must be a non-empty string"
            )
        if (
            type(self.disposition) is not str
            or self.disposition not in SATISFACTION_DISPOSITIONS
        ):
            raise ValueError("satisfaction criterion disposition is unsupported")
        if type(self.reason_code) is not str or not self.reason_code:
            raise TypeError(
                "satisfaction criterion reason_code must be a non-empty string"
            )
        if (
            type(self.evidence) is not tuple
            or not self.evidence
            or any(type(pointer) is not str or not pointer for pointer in self.evidence)
        ):
            raise TypeError(
                "satisfaction criterion evidence must be a non-empty tuple "
                "of non-empty string pointers"
            )


@dataclass(frozen=True, slots=True)
class SatisfactionSnapshot:
    """One immutable, validated satisfaction evidence snapshot."""

    repository: str
    issue_number: int
    issue_body_digest: str
    status: str
    criteria: tuple[SatisfactionCriterionSnapshot, ...]

    def __post_init__(self) -> None:
        # Construction itself enforces the same rules
        # ``validate_satisfaction_snapshot`` applies to caller mappings
        # (exact built-in types, digest format, status vocabulary,
        # contiguous 1..N criterion indexes, and declared status equal to
        # the status derived from the criteria). Any existing instance is
        # therefore necessarily valid, and the mapping path's pass-through
        # of an already-built instance is sound.
        if type(self.repository) is not str or not self.repository:
            raise TypeError("satisfaction repository must be a non-empty string")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise TypeError(
                "satisfaction issue_number must be a positive built-in integer"
            )
        if (
            type(self.issue_body_digest) is not str
            or len(self.issue_body_digest) != 64
            or any(ch not in _HEX_DIGITS for ch in self.issue_body_digest)
        ):
            raise ValueError(
                "satisfaction issue_body_digest must be a 64-char "
                "lowercase hex digest"
            )
        if type(self.status) is not str or self.status not in SATISFACTION_STATUSES:
            raise ValueError("satisfaction status is unsupported")
        if type(self.criteria) is not tuple or any(
            type(item) is not SatisfactionCriterionSnapshot
            for item in self.criteria
        ):
            raise TypeError(
                "satisfaction criteria must be a tuple of criterion snapshots"
            )
        for position, item in enumerate(self.criteria, start=1):
            if item.index != position:
                raise ValueError(
                    "satisfaction criterion indexes must be 1..N contiguous, "
                    "unique, and in order"
                )
        if self.status != derived_satisfaction_status(self.criteria):
            raise ValueError("satisfaction status disagrees with its criteria")

    @property
    def complete(self) -> bool:
        return self.status == "complete"

    @property
    def unsatisfied_criteria(self) -> tuple[SatisfactionCriterionSnapshot, ...]:
        """Every criterion that does not hold satisfied (named, never hidden)."""
        return tuple(
            item for item in self.criteria if item.disposition != "satisfied"
        )


def validate_satisfaction_snapshot(value: object) -> SatisfactionSnapshot:
    """Validate one caller-supplied snapshot mapping; return the frozen copy.

    Key sets are exact (missing or extra keys are rejected), types are
    exact built-ins (a bool is not an index or an issue number; criteria
    and evidence must be exact lists), and the declared status must agree
    with the criteria under the same derivation the #3678 projector
    applies: ``complete`` iff at least one criterion exists and every
    criterion is satisfied; ``manual-review`` iff any criterion is
    manual-review (an empty criterion list only ever carries
    ``manual-review``); otherwise ``incomplete``. A status that disagrees —
    in particular a ``complete`` claim over unsatisfied, stale, missing,
    contradicted, or absent criteria — is forged or inconsistent and is
    rejected. An already-built ``SatisfactionSnapshot`` is returned
    unchanged: its own ``__post_init__`` enforces exactly these rules at
    construction, so no instance can be inconsistent. Any other object —
    including a look-alike type carrying the same fields — is rejected.
    """
    if type(value) is SatisfactionSnapshot:
        return value
    if type(value) is not dict:
        raise TypeError("satisfaction must be an exact dict snapshot")
    if set(value) != SATISFACTION_KEYS:
        raise ValueError(
            "satisfaction snapshot keys must be exactly repository, "
            "issue_number, issue_body_digest, status, criteria"
        )
    repository = value["repository"]
    if type(repository) is not str or not repository:
        raise TypeError("satisfaction repository must be a non-empty string")
    issue_number = value["issue_number"]
    if type(issue_number) is not int or issue_number < 1:
        raise TypeError(
            "satisfaction issue_number must be a positive built-in integer"
        )
    digest = value["issue_body_digest"]
    if (
        type(digest) is not str
        or len(digest) != 64
        or any(ch not in _HEX_DIGITS for ch in digest)
    ):
        raise ValueError(
            "satisfaction issue_body_digest must be a 64-char lowercase hex digest"
        )
    status = value["status"]
    if type(status) is not str or status not in SATISFACTION_STATUSES:
        raise ValueError("satisfaction status is unsupported")
    raw_criteria = value["criteria"]
    if type(raw_criteria) is not list:
        raise TypeError("satisfaction criteria must be an exact list")
    criteria: list[SatisfactionCriterionSnapshot] = []
    for position, raw in enumerate(raw_criteria, start=1):
        if type(raw) is not dict:
            raise TypeError("satisfaction criterion must be an exact dict")
        if set(raw) != SATISFACTION_CRITERION_KEYS:
            raise ValueError(
                "satisfaction criterion keys must be exactly index, "
                "identity, disposition, reason_code, evidence"
            )
        index = raw["index"]
        if type(index) is not int:
            raise TypeError("satisfaction criterion index must be a built-in int")
        if index != position:
            raise ValueError(
                "satisfaction criterion indexes must be 1..N contiguous, "
                "unique, and in order"
            )
        identity = raw["identity"]
        if type(identity) is not str or not identity:
            raise TypeError(
                "satisfaction criterion identity must be a non-empty string"
            )
        disposition = raw["disposition"]
        if type(disposition) is not str or disposition not in SATISFACTION_DISPOSITIONS:
            raise ValueError("satisfaction criterion disposition is unsupported")
        reason_code = raw["reason_code"]
        if type(reason_code) is not str or not reason_code:
            raise TypeError(
                "satisfaction criterion reason_code must be a non-empty string"
            )
        evidence = raw["evidence"]
        if (
            type(evidence) is not list
            or not evidence
            or any(type(pointer) is not str or not pointer for pointer in evidence)
        ):
            raise TypeError(
                "satisfaction criterion evidence must be a non-empty list "
                "of non-empty string pointers"
            )
        criteria.append(
            SatisfactionCriterionSnapshot(
                index, identity, disposition, reason_code, tuple(evidence)
            )
        )
    frozen_criteria = tuple(criteria)
    if status != derived_satisfaction_status(frozen_criteria):
        raise ValueError("satisfaction status disagrees with its criteria")
    return SatisfactionSnapshot(
        repository, issue_number, digest, status, frozen_criteria
    )
