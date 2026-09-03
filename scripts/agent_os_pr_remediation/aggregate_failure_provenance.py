"""Pure-local provenance projection for failed aggregate validation evidence.

This module refines existing validation evidence; it does not execute validation,
select tests, mutate CI, or grant readiness/merge/closure authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import EvidenceValidationError


class AggregateFailureProvenance(str, Enum):
    PR_ATTRIBUTABLE = "pr-attributable"
    SHARED_BASELINE = "shared-baseline"
    ENVIRONMENT = "environment-infrastructure"
    MERGE_CONTEXT = "merge-context"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class AggregateFailureEvidence:
    provenance: AggregateFailureProvenance
    tested_sha: str
    current_head_sha: str
    main_sha: str | None
    failure_fingerprint: str | None
    blocking_pr_failure: bool
    requires_manual_review: bool
    reason_codes: tuple[str, ...]
    execution_authorized: bool = False
    merge_authorized: bool = False
    closure_authorized: bool = False
    production_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False


def _sha(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise EvidenceValidationError(f"{field} must be a SHA")
    text = value.lower()
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise EvidenceValidationError(f"{field} must be a 40-character hexadecimal SHA")
    return text


def _fingerprint(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or len(value) > 256:
        raise EvidenceValidationError("failure_fingerprint must be a bounded non-empty string")
    return value


def classify_aggregate_failure(
    *,
    tested_sha: str,
    current_head_sha: str,
    main_sha: str | None,
    failure_fingerprint: str | None,
    same_failure_on_current_main: bool,
    environment_or_bootstrap_failure: bool,
    required_repository_invariant: bool,
    changed_contract_reaches_failure: bool,
    synthetic_merge_only_failure: bool,
) -> AggregateFailureEvidence:
    """Classify one already-observed aggregate failure using bounded evidence.

    Path distance is deliberately absent: downstream failures can remain attributable
    when a changed shared contract reaches them. Shared-baseline classification requires
    an identical current-main failure and is invalidated as soon as main no longer has it.
    Conflicting or insufficient evidence fails closed as ambiguous/manual review.
    """

    head = _sha(current_head_sha, "current_head_sha") or ""
    tested = _sha(tested_sha, "tested_sha") or ""
    main = _sha(main_sha, "main_sha", optional=True)
    fingerprint = _fingerprint(failure_fingerprint)
    flags = (
        same_failure_on_current_main,
        environment_or_bootstrap_failure,
        required_repository_invariant,
        changed_contract_reaches_failure,
        synthetic_merge_only_failure,
    )
    if any(type(value) is not bool for value in flags):
        raise EvidenceValidationError("aggregate provenance flags must be booleans")

    reasons: set[str] = set()
    if tested != head and not synthetic_merge_only_failure:
        reasons.add("aggregate-tested-sha-not-current-head")
        return AggregateFailureEvidence(
            AggregateFailureProvenance.AMBIGUOUS, tested, head, main, fingerprint,
            False, True, tuple(sorted(reasons)),
        )

    if required_repository_invariant:
        reasons.add("required-repository-invariant-failed")
        return AggregateFailureEvidence(
            AggregateFailureProvenance.PR_ATTRIBUTABLE, tested, head, main, fingerprint,
            True, False, tuple(sorted(reasons)),
        )

    if changed_contract_reaches_failure:
        reasons.add("changed-contract-reaches-failure")
        return AggregateFailureEvidence(
            AggregateFailureProvenance.PR_ATTRIBUTABLE, tested, head, main, fingerprint,
            True, False, tuple(sorted(reasons)),
        )

    if synthetic_merge_only_failure:
        reasons.add("synthetic-merge-context-failure")
        return AggregateFailureEvidence(
            AggregateFailureProvenance.MERGE_CONTEXT, tested, head, main, fingerprint,
            True, False, tuple(sorted(reasons)),
        )

    if environment_or_bootstrap_failure:
        if same_failure_on_current_main:
            reasons.update(("environment-or-bootstrap-failure", "same-failure-on-current-main"))
            return AggregateFailureEvidence(
                AggregateFailureProvenance.ENVIRONMENT, tested, head, main, fingerprint,
                False, False, tuple(sorted(reasons)),
            )
        reasons.add("environment-or-bootstrap-failure")
        return AggregateFailureEvidence(
            AggregateFailureProvenance.ENVIRONMENT, tested, head, main, fingerprint,
            False, True, tuple(sorted(reasons)),
        )

    if same_failure_on_current_main:
        if main is None or fingerprint is None:
            reasons.add("shared-baseline-proof-incomplete")
            return AggregateFailureEvidence(
                AggregateFailureProvenance.AMBIGUOUS, tested, head, main, fingerprint,
                False, True, tuple(sorted(reasons)),
            )
        reasons.add("same-failure-on-current-main")
        return AggregateFailureEvidence(
            AggregateFailureProvenance.SHARED_BASELINE, tested, head, main, fingerprint,
            False, False, tuple(sorted(reasons)),
        )

    reasons.add("aggregate-failure-attribution-unproven")
    return AggregateFailureEvidence(
        AggregateFailureProvenance.AMBIGUOUS, tested, head, main, fingerprint,
        False, True, tuple(sorted(reasons)),
    )
