"""Pure projection of CKR5 lesson proposals into non-authoritative Notion records."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .coding_failure_learning import LessonDisposition, LessonLearningResult

MAX_BACKFILL_RESULTS = 50


class ProjectionDisposition(str, Enum):
    ELIGIBLE = "eligible"
    RECURRENCE = "recurrence"
    SKIP = "skip"
    MANUAL_REVIEW = "manual-review"


@dataclass(frozen=True, slots=True)
class NotionLearningRecordProposal:
    operation: str
    lesson_identity: str
    title: str
    component: str
    symptom: str
    root_cause_or_diagnosis: str
    resolution_or_next_time: str
    prevention_guardrail: str
    learning_type: str
    severity: str
    owner_agent: str
    source_reference: str
    canonical_github_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    proposed_recurrence_count: int
    surface_before_work: bool
    source_of_truth: str = field(default="GitHub", init=False)
    notion_role: str = field(default="non-authoritative-working-knowledge", init=False)
    authority_created: bool = field(default=False, init=False)
    side_effects_performed: bool = field(default=False, init=False)
    notion_write_performed: bool = field(default=False, init=False)
    publication_authorized: bool = field(default=False, init=False)

    def to_dict(self) -> dict[str, Any]:
        data = {name: getattr(self, name) for name in self.__dataclass_fields__}
        for name in ("canonical_github_refs", "evidence_refs"):
            data[name] = list(data[name])
        return data


@dataclass(frozen=True, slots=True)
class NotionLearningProjectionResult:
    disposition: ProjectionDisposition
    reason_codes: tuple[str, ...]
    record: NotionLearningRecordProposal | None = None
    authority_created: bool = field(default=False, init=False)
    side_effects_performed: bool = field(default=False, init=False)
    notion_write_performed: bool = field(default=False, init=False)
    publication_authorized: bool = field(default=False, init=False)


def project_lesson_to_notion(result: LessonLearningResult) -> NotionLearningProjectionResult:
    """Return a write-free Notion record proposal from an already-qualified CKR5 result."""
    if type(result) is not LessonLearningResult:
        raise TypeError("result must be a LessonLearningResult")
    if result.disposition in {LessonDisposition.NON_REUSABLE, LessonDisposition.INSUFFICIENT_EVIDENCE}:
        return NotionLearningProjectionResult(ProjectionDisposition.SKIP, (result.disposition.value,))
    if result.disposition is LessonDisposition.MANUAL_REVIEW:
        return NotionLearningProjectionResult(ProjectionDisposition.MANUAL_REVIEW, result.reason_codes)
    proposal = result.proposal
    if proposal is None:
        return NotionLearningProjectionResult(ProjectionDisposition.MANUAL_REVIEW, ("qualified-result-missing-proposal",))
    if not proposal.canonical_github_refs or not proposal.evidence_refs:
        return NotionLearningProjectionResult(ProjectionDisposition.MANUAL_REVIEW, ("canonical-evidence-missing",))

    disposition = (
        ProjectionDisposition.RECURRENCE
        if result.disposition is LessonDisposition.REUSABLE_RECURRENCE
        else ProjectionDisposition.ELIGIBLE
    )
    record = NotionLearningRecordProposal(
        operation=proposal.operation,
        lesson_identity=proposal.lesson_identity,
        title=proposal.lesson_summary,
        component=result.capability_kind or "unknown",
        symptom=proposal.what_happened,
        root_cause_or_diagnosis=proposal.what_happened,
        resolution_or_next_time=proposal.what_to_do_next_time,
        prevention_guardrail=proposal.guardrail,
        learning_type=proposal.learning_type,
        severity=proposal.severity,
        owner_agent=proposal.owner_agent,
        source_reference=proposal.source_reference,
        canonical_github_refs=proposal.canonical_github_refs,
        evidence_refs=proposal.evidence_refs,
        proposed_recurrence_count=proposal.proposed_recurrence_count,
        surface_before_work=proposal.surface_before_work,
    )
    return NotionLearningProjectionResult(disposition, result.reason_codes, record)


def plan_historical_backfill(
    results: tuple[LessonLearningResult, ...],
) -> tuple[NotionLearningProjectionResult, ...]:
    """Project a bounded historical batch without performing writes or dedup cleanup."""
    if type(results) is not tuple or any(type(item) is not LessonLearningResult for item in results):
        raise TypeError("results must be a tuple of LessonLearningResult values")
    if len(results) > MAX_BACKFILL_RESULTS:
        return (NotionLearningProjectionResult(ProjectionDisposition.MANUAL_REVIEW, ("backfill-budget-exceeded",)),)
    projected = tuple(project_lesson_to_notion(item) for item in results)
    identities = [item.record.lesson_identity for item in projected if item.record is not None]
    if len(identities) != len(set(identities)):
        return (NotionLearningProjectionResult(ProjectionDisposition.MANUAL_REVIEW, ("duplicate-lesson-identity-in-batch",)),)
    return projected
