"""Normalize high-value structured CI/review outcomes for existing CKR5.

This module is a narrow producer seam. It does not ingest raw logs, classify
Lessons Learned, publish to Notion, execute validation, or create authority.
CKR5 remains the reusable-learning, identity, and recurrence owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .coding_failure_learning import FailureKind, FailureObservation
from .coding_knowledge_selection import KnowledgeCurrentness

MAX_OUTCOME_TEXT_CHARS = 512
MAX_OUTCOME_DETAIL_CHARS = 1024
MAX_OUTCOME_REFS = 20


class LearningSignal(str, Enum):
    ESCAPED_REGRESSION = "escaped-regression"
    SUBSTANTIVE_REVIEW_FINDING = "substantive-review-finding"
    PROPERTY_COUNTEREXAMPLE = "property-counterexample"
    REPEATED_REPAIR = "repeated-repair"
    FLAKY_DIAGNOSIS = "flaky-diagnosis"
    OBSOLETE_VALIDATION = "obsolete-validation"
    EXPECTED_TEST_FAILURE = "expected-test-failure"
    TRANSIENT_ENVIRONMENT = "transient-environment"
    SURVIVING_MUTATION = "surviving-mutation"
    ORDINARY_PASS = "ordinary-pass"


class ProducerDisposition(str, Enum):
    CKR5_CANDIDATE = "ckr5-candidate"
    NOT_REUSABLE = "not-reusable"
    MANUAL_REVIEW = "manual-review"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, slots=True)
class StructuredLearningOutcome:
    source_reference: str
    signal: LearningSignal
    failure_signature: str
    ecosystem: str
    capability_kind: str
    lesson_summary: str
    what_happened: str
    severity: str
    owner_agent: str
    canonical_github_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    affected_paths: tuple[str, ...] = ()
    future_use_hints: tuple[str, ...] = ()
    library_name: str | None = None
    what_to_do_next_time: str | None = None
    guardrail: str | None = None
    currentness: KnowledgeCurrentness = KnowledgeCurrentness.CURRENT
    reusable_rule_proven: bool = False
    permanent_regression_ref: str | None = None
    authority_conflict: bool = False

    def __post_init__(self) -> None:
        for name in (
            "source_reference", "failure_signature", "ecosystem", "capability_kind",
            "lesson_summary", "severity", "owner_agent",
        ):
            _bounded_text(getattr(self, name), name)
        _bounded_text(self.what_happened, "what_happened", MAX_OUTCOME_DETAIL_CHARS)
        for name in ("library_name", "what_to_do_next_time", "guardrail", "permanent_regression_ref"):
            value = getattr(self, name)
            if value is not None:
                _bounded_text(value, name)
        for name in ("canonical_github_refs", "evidence_refs", "affected_paths", "future_use_hints"):
            _bounded_items(getattr(self, name), name)
        if type(self.signal) is not LearningSignal:
            raise TypeError("signal must be a LearningSignal value")
        if type(self.currentness) is not KnowledgeCurrentness:
            raise TypeError("currentness must be a KnowledgeCurrentness value")
        if type(self.reusable_rule_proven) is not bool or type(self.authority_conflict) is not bool:
            raise TypeError("reusable_rule_proven and authority_conflict must be bool")


@dataclass(frozen=True, slots=True)
class LearningProducerResult:
    disposition: ProducerDisposition
    reason_codes: tuple[str, ...]
    observation: FailureObservation | None = None
    authority_created: bool = field(default=False, init=False)
    side_effects_performed: bool = field(default=False, init=False)
    notion_write_performed: bool = field(default=False, init=False)
    github_write_performed: bool = field(default=False, init=False)
    validation_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    closure_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)
    external_write_authorized: bool = field(default=False, init=False)


_NOISE = frozenset({
    LearningSignal.EXPECTED_TEST_FAILURE,
    LearningSignal.TRANSIENT_ENVIRONMENT,
    LearningSignal.ORDINARY_PASS,
})


def normalize_learning_outcome(outcome: StructuredLearningOutcome) -> LearningProducerResult:
    """Return a CKR5-compatible observation only for bounded reusable evidence."""
    if type(outcome) is not StructuredLearningOutcome:
        raise TypeError("outcome must be a StructuredLearningOutcome")
    if outcome.authority_conflict or outcome.currentness is not KnowledgeCurrentness.CURRENT:
        return _result(ProducerDisposition.MANUAL_REVIEW, "stale-or-conflicting-evidence")
    if outcome.signal in _NOISE:
        return _result(ProducerDisposition.NOT_REUSABLE, f"noise:{outcome.signal.value}")
    if outcome.signal is LearningSignal.SURVIVING_MUTATION and not outcome.reusable_rule_proven:
        return _result(ProducerDisposition.NOT_REUSABLE, "mutation-quality-evidence-only")
    if outcome.signal is LearningSignal.PROPERTY_COUNTEREXAMPLE and not outcome.permanent_regression_ref:
        return _result(ProducerDisposition.INSUFFICIENT, "property-regression-evidence-missing")
    if not outcome.reusable_rule_proven:
        return _result(ProducerDisposition.NOT_REUSABLE, "reusable-rule-not-proven")
    if not outcome.what_to_do_next_time or not outcome.guardrail:
        return _result(ProducerDisposition.INSUFFICIENT, "reusable-guidance-missing")
    if not outcome.canonical_github_refs or not outcome.evidence_refs:
        return _result(ProducerDisposition.INSUFFICIENT, "bounded-references-missing")

    regression_refs = (outcome.permanent_regression_ref,) if outcome.permanent_regression_ref else ()
    canonical_refs = _bounded_union(outcome.canonical_github_refs, regression_refs)
    future_hints = _bounded_union(outcome.future_use_hints, outcome.affected_paths)
    if canonical_refs is None or future_hints is None:
        return _result(ProducerDisposition.MANUAL_REVIEW, "ckr5-reference-budget-exceeded")

    observation = FailureObservation(
        source_reference=outcome.source_reference,
        failure_kind=_failure_kind(outcome.signal),
        failure_signature=outcome.failure_signature,
        ecosystem=outcome.ecosystem,
        capability_kind=outcome.capability_kind,
        library_name=outcome.library_name,
        lesson_summary=outcome.lesson_summary,
        what_happened=outcome.what_happened,
        what_to_do_next_time=outcome.what_to_do_next_time,
        guardrail=outcome.guardrail,
        learning_type="ci-review-feedback",
        severity=outcome.severity,
        owner_agent=outcome.owner_agent,
        canonical_github_refs=canonical_refs,
        evidence_refs=tuple(sorted(set(outcome.evidence_refs))),
        future_use_hints=future_hints,
        currentness=outcome.currentness,
        reusable_rule=True,
        authority_conflict=False,
    )
    return LearningProducerResult(
        disposition=ProducerDisposition.CKR5_CANDIDATE,
        reason_codes=(f"admitted:{outcome.signal.value}",),
        observation=observation,
    )


def _failure_kind(signal: LearningSignal) -> FailureKind:
    if signal is LearningSignal.SUBSTANTIVE_REVIEW_FINDING:
        return FailureKind.REVIEW_FINDING
    if signal in {LearningSignal.OBSOLETE_VALIDATION, LearningSignal.FLAKY_DIAGNOSIS}:
        return FailureKind.VALIDATION_FAILURE
    if signal is LearningSignal.TRANSIENT_ENVIRONMENT:
        return FailureKind.TRANSIENT_ENVIRONMENT
    return FailureKind.CODE_DEFECT


def _result(disposition: ProducerDisposition, reason: str) -> LearningProducerResult:
    return LearningProducerResult(disposition=disposition, reason_codes=(reason,))


def _bounded_union(*groups: tuple[str, ...]) -> tuple[str, ...] | None:
    values = tuple(sorted(set(item for group in groups for item in group)))
    return values if len(values) <= MAX_OUTCOME_REFS else None


def _bounded_text(value: str, name: str, limit: int = MAX_OUTCOME_TEXT_CHARS) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    if len(value) > limit:
        raise ValueError(f"{name} exceeds bounded structured-evidence size")


def _bounded_items(values: tuple[str, ...], name: str) -> None:
    if type(values) is not tuple or len(values) > MAX_OUTCOME_REFS:
        raise ValueError(f"{name} must be a bounded tuple")
    for value in values:
        _bounded_text(value, name)