"""Bounded advisory Lessons Learned consumption for coding preflight.

This module consumes already-read normalized lesson evidence. It performs no
Notion reads or writes and delegates relevance/sufficiency to CKR2's canonical
``select_coding_knowledge`` contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .coding_knowledge_selection import (
    CodingKnowledgeCandidate,
    CodingKnowledgeRequest,
    CodingKnowledgeSelectionResult,
    KnowledgeCurrentness,
    RetrievalEscalation,
    SufficiencyStatus,
    select_coding_knowledge,
)

MAX_LESSON_RECORDS = 5
_ALLOWED_STATUSES = frozenset({"New", "Applied", "Needs follow-up"})


class LessonRetrievalStatus(str, Enum):
    NOT_NEEDED = "not-needed"
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    MANUAL_REVIEW = "manual-review"
    UNAVAILABLE_SAFE_FALLBACK = "unavailable-safe-fallback"


@dataclass(frozen=True, slots=True)
class LessonRecordEvidence:
    """Provider-neutral bounded evidence for one Lessons Learned row."""

    lesson_id: str
    source_revision: str
    title: str
    ecosystem: str
    capability_kind: str
    status: str
    surface_before_work: bool
    currentness: KnowledgeCurrentness
    what_to_do_next_time: str
    guardrail: str
    canonical_github_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    keywords: tuple[str, ...] = ()
    library_name: str | None = None
    archived: bool = False
    authority_conflict: bool = False

    def __post_init__(self) -> None:
        for name in (
            "lesson_id", "source_revision", "title", "ecosystem", "capability_kind",
            "status", "what_to_do_next_time", "guardrail",
        ):
            _text(getattr(self, name), name)
        if self.library_name is not None:
            _text(self.library_name, "library_name")
        for name in ("canonical_github_refs", "evidence_refs", "keywords"):
            _items(getattr(self, name), name)
        if type(self.surface_before_work) is not bool:
            raise TypeError("surface_before_work must be bool")
        if type(self.archived) is not bool or type(self.authority_conflict) is not bool:
            raise TypeError("archived and authority_conflict must be bool")
        if type(self.currentness) is not KnowledgeCurrentness:
            raise TypeError("currentness must be a KnowledgeCurrentness value")


@dataclass(frozen=True, slots=True)
class LessonPreflightPlan:
    retrieval_required: bool
    reason_codes: tuple[str, ...]
    recommended_escalation: RetrievalEscalation
    notion_read_performed: bool = field(default=False, init=False)
    authority_created: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class LessonPreflightResult:
    lesson_retrieval_status: LessonRetrievalStatus
    candidate_count: int
    selected_count: int
    selected_lesson_ids: tuple[str, ...]
    selection_reason_codes: tuple[str, ...]
    canonical_github_refs: tuple[str, ...]
    knowledge_refs: tuple[str, ...]
    stale_or_conflicting_count: int
    retrieval_escalation: RetrievalEscalation
    source_authority: str
    handoff_projection: dict[str, list[str]]
    selection: CodingKnowledgeSelectionResult | None = None
    notion_write_performed: bool = field(default=False, init=False)
    github_write_performed: bool = field(default=False, init=False)
    authority_created: bool = field(default=False, init=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lesson_retrieval_status": self.lesson_retrieval_status.value,
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "selected_lesson_ids": list(self.selected_lesson_ids),
            "selection_reason_codes": list(self.selection_reason_codes),
            "canonical_github_refs": list(self.canonical_github_refs),
            "knowledge_refs": list(self.knowledge_refs),
            "stale_or_conflicting_count": self.stale_or_conflicting_count,
            "retrieval_escalation": self.retrieval_escalation.value,
            "source_authority": self.source_authority,
            "handoff_projection": self.handoff_projection,
            "notion_write_performed": self.notion_write_performed,
            "github_write_performed": self.github_write_performed,
            "authority_created": self.authority_created,
        }


def plan_lesson_preflight(request: CodingKnowledgeRequest) -> LessonPreflightPlan:
    """Use CKR2 to decide whether a caller should retrieve lesson evidence."""
    selection = select_coding_knowledge(request, ())
    if selection.sufficiency_status is SufficiencyStatus.NOT_NEEDED:
        return LessonPreflightPlan(False, selection.reason_codes, RetrievalEscalation.NONE)
    return LessonPreflightPlan(
        True,
        ("lesson-retrieval-required",),
        RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,
    )


def consume_lesson_preflight(
    request: CodingKnowledgeRequest,
    lessons: tuple[LessonRecordEvidence, ...] = (),
    *,
    retrieval_available: bool = True,
) -> LessonPreflightResult:
    """Normalize eligible lesson evidence and delegate selection to CKR2."""
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")
    if type(lessons) is not tuple or any(type(item) is not LessonRecordEvidence for item in lessons):
        raise TypeError("lessons must be a tuple of LessonRecordEvidence values")
    if type(retrieval_available) is not bool:
        raise TypeError("retrieval_available must be bool")

    plan = plan_lesson_preflight(request)
    if not plan.retrieval_required:
        selection = select_coding_knowledge(request, ())
        return _from_selection(selection, (), 0)

    if not retrieval_available:
        if request.specialized_knowledge_required is True:
            return _fallback(
                LessonRetrievalStatus.INSUFFICIENT,
                "lesson-retrieval-unavailable-specialized-knowledge-required",
                RetrievalEscalation.MANUAL_REVIEW,
            )
        return _fallback(
            LessonRetrievalStatus.UNAVAILABLE_SAFE_FALLBACK,
            "lesson-retrieval-unavailable-github-only-fallback",
            RetrievalEscalation.NONE,
        )

    if len(lessons) > MAX_LESSON_RECORDS:
        return _fallback(
            LessonRetrievalStatus.MANUAL_REVIEW,
            "lesson-candidate-budget-exceeded",
            RetrievalEscalation.MANUAL_REVIEW,
            candidate_count=len(lessons),
        )

    eligible: list[LessonRecordEvidence] = []
    stale_or_conflicting = 0
    for lesson in lessons:
        if lesson.archived or lesson.status not in _ALLOWED_STATUSES or not lesson.surface_before_work:
            continue
        if lesson.currentness is not KnowledgeCurrentness.CURRENT or lesson.authority_conflict:
            stale_or_conflicting += 1
        eligible.append(lesson)

    candidates = tuple(_candidate(item) for item in eligible)
    selection = select_coding_knowledge(request, candidates)
    return _from_selection(selection, tuple(eligible), stale_or_conflicting)


def _candidate(lesson: LessonRecordEvidence) -> CodingKnowledgeCandidate:
    return CodingKnowledgeCandidate(
        knowledge_id=lesson.lesson_id,
        source_system="notion-lessons-learned",
        source_revision=lesson.source_revision,
        currentness=lesson.currentness,
        name=lesson.title,
        ecosystem=lesson.ecosystem,
        library_name=lesson.library_name,
        capability_kind=lesson.capability_kind,
        keywords=lesson.keywords,
        use_when=(lesson.what_to_do_next_time, lesson.guardrail),
        avoid_when=(),
        canonical_github_refs=lesson.canonical_github_refs,
        evidence_refs=lesson.evidence_refs,
        authority_conflict=lesson.authority_conflict,
    )


def _from_selection(
    selection: CodingKnowledgeSelectionResult,
    eligible: tuple[LessonRecordEvidence, ...],
    stale_or_conflicting_count: int,
) -> LessonPreflightResult:
    status = {
        SufficiencyStatus.NOT_NEEDED: LessonRetrievalStatus.NOT_NEEDED,
        SufficiencyStatus.SUFFICIENT: LessonRetrievalStatus.SUFFICIENT,
        SufficiencyStatus.INSUFFICIENT: LessonRetrievalStatus.INSUFFICIENT,
        SufficiencyStatus.MANUAL_REVIEW: LessonRetrievalStatus.MANUAL_REVIEW,
    }[selection.sufficiency_status]
    selected_ids = tuple(item.candidate.knowledge_id for item in selection.selected)
    return LessonPreflightResult(
        lesson_retrieval_status=status,
        candidate_count=selection.candidate_count,
        selected_count=selection.selected_count,
        selected_lesson_ids=selected_ids,
        selection_reason_codes=selection.reason_codes,
        canonical_github_refs=selection.canonical_github_refs,
        knowledge_refs=selection.knowledge_refs,
        stale_or_conflicting_count=stale_or_conflicting_count,
        retrieval_escalation=selection.recommended_escalation,
        source_authority="advisory-only",
        handoff_projection=selection.to_handoff_projection(),
        selection=selection,
    )


def _fallback(
    status: LessonRetrievalStatus,
    reason: str,
    escalation: RetrievalEscalation,
    *,
    candidate_count: int = 0,
) -> LessonPreflightResult:
    stop_conditions = []
    if status in {LessonRetrievalStatus.INSUFFICIENT, LessonRetrievalStatus.MANUAL_REVIEW}:
        stop_conditions = [f"coding-knowledge:{reason}"]
    return LessonPreflightResult(
        lesson_retrieval_status=status,
        candidate_count=candidate_count,
        selected_count=0,
        selected_lesson_ids=(),
        selection_reason_codes=(reason,),
        canonical_github_refs=(),
        knowledge_refs=(),
        stale_or_conflicting_count=0,
        retrieval_escalation=escalation,
        source_authority="advisory-only",
        handoff_projection={
            "known_facts": [f"coding-knowledge-sufficiency:{status.value}"],
            "prior_decisions": [],
            "allowed_inspect_first": [],
            "stop_conditions": stop_conditions,
        },
    )


def _text(value: object, name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must be non-empty")
    if len(value) > 512:
        raise ValueError(f"{name} is oversized")


def _items(value: object, name: str) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be a tuple")
    if len(value) > 20:
        raise ValueError(f"{name} is oversized")
    for item in value:
        _text(item, name)
