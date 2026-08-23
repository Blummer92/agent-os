"""Pure projection of CKR5 lesson proposals into non-authoritative Notion records."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .coding_failure_learning import LessonDisposition, LessonLearningResult

MAX_BACKFILL_BATCH_SIZE = 50
MAX_BACKFILL_RESULTS = MAX_BACKFILL_BATCH_SIZE  # compatibility alias; not a global cap
MAX_DIAGNOSIS_CHARS = 1024


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
    root_cause_or_diagnosis: str | None
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


@dataclass(frozen=True, slots=True)
class HistoricalBackfillPlan:
    results: tuple[NotionLearningProjectionResult, ...]
    offset: int
    batch_size: int
    total_results: int
    next_offset: int | None
    complete: bool
    authority_created: bool = field(default=False, init=False)
    side_effects_performed: bool = field(default=False, init=False)
    notion_write_performed: bool = field(default=False, init=False)
    publication_authorized: bool = field(default=False, init=False)


def project_lesson_to_notion(
    result: LessonLearningResult,
    *,
    root_cause_or_diagnosis: str | None = None,
) -> NotionLearningProjectionResult:
    """Return a write-free Notion record proposal from an already-qualified CKR5 result."""
    if type(result) is not LessonLearningResult:
        raise TypeError("result must be a LessonLearningResult")
    diagnosis = _optional_diagnosis(root_cause_or_diagnosis)
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
    reason_codes = result.reason_codes
    if diagnosis is None:
        reason_codes = reason_codes + ("root-cause-or-diagnosis-not-supplied",)
    record = NotionLearningRecordProposal(
        operation=proposal.operation,
        lesson_identity=proposal.lesson_identity,
        title=proposal.lesson_summary,
        component=result.capability_kind or "unknown",
        symptom=proposal.what_happened,
        root_cause_or_diagnosis=diagnosis,
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
    return NotionLearningProjectionResult(disposition, reason_codes, record)


def plan_historical_backfill(
    results: tuple[LessonLearningResult, ...],
    *,
    offset: int = 0,
    root_causes_or_diagnoses: tuple[str | None, ...] = (),
) -> HistoricalBackfillPlan:
    """Project one bounded page from an arbitrarily large supplied historical set."""
    if type(results) is not tuple or any(type(item) is not LessonLearningResult for item in results):
        raise TypeError("results must be a tuple of LessonLearningResult values")
    if type(offset) is not int or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if root_causes_or_diagnoses and len(root_causes_or_diagnoses) != len(results):
        raise ValueError("root_causes_or_diagnoses must be empty or align one-to-one with results")

    total = len(results)
    start = min(offset, total)
    end = min(start + MAX_BACKFILL_BATCH_SIZE, total)
    page = results[start:end]
    page_diagnoses = (
        root_causes_or_diagnoses[start:end]
        if root_causes_or_diagnoses
        else tuple(None for _ in page)
    )

    all_identities = [
        item.proposal.lesson_identity
        for item in results
        if item.proposal is not None
    ]
    if len(all_identities) != len(set(all_identities)):
        projected = (
            NotionLearningProjectionResult(
                ProjectionDisposition.MANUAL_REVIEW,
                ("duplicate-lesson-identity-in-backfill-set",),
            ),
        )
    else:
        projected = tuple(
            project_lesson_to_notion(item, root_cause_or_diagnosis=diagnosis)
            for item, diagnosis in zip(page, page_diagnoses)
        )

    next_offset = end if end < total else None
    return HistoricalBackfillPlan(
        results=projected,
        offset=start,
        batch_size=len(page),
        total_results=total,
        next_offset=next_offset,
        complete=next_offset is None,
    )


def _optional_diagnosis(value: str | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError("root_cause_or_diagnosis must be a string or None")
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) > MAX_DIAGNOSIS_CHARS:
        raise ValueError("root_cause_or_diagnosis exceeds the bounded length")
    return normalized
