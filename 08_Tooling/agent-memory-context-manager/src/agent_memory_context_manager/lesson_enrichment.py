"""Deterministic, side-effect-free maintenance proposals for Lessons Learned."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .coding_knowledge_selection import KnowledgeCurrentness
from .lesson_preflight import LessonRecordEvidence

MAX_RELATED_EVIDENCE = 8
MAX_CONSOLIDATION_LESSONS = 5
MAX_REFS = 20
MAX_TEXT = 1024


class LessonEnrichmentDisposition(str, Enum):
    UNCHANGED = "unchanged"
    ENRICH_EXISTING = "enrich-existing"
    CONSOLIDATE_COMPATIBLE = "consolidate-compatible"
    SUPERSEDE_EXISTING = "supersede-existing"
    DISTINCT_LESSON = "distinct-lesson"
    MANUAL_REVIEW = "manual-review"
    INSUFFICIENT_EVIDENCE = "insufficient-evidence"


class EvidenceEffect(str, Enum):
    CONFIRMS = "confirms"
    IMPROVES_ROOT_CAUSE = "improves-root-cause"
    ADDS_GUARDRAIL = "adds-guardrail"
    SUPERSEDES = "supersedes"
    DISTINCT_CAUSE = "distinct-cause"
    CONTRADICTS = "contradicts"
    INCIDENTAL = "incidental"


@dataclass(frozen=True, slots=True)
class CurrentLessonEvidence:
    lesson_id: str
    source_revision: str
    title: str
    ecosystem: str
    capability_kind: str
    what_happened: str
    what_to_do_next_time: str
    guardrail: str
    canonical_github_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    origin_refs: tuple[str, ...]
    keywords: tuple[str, ...] = ()
    library_name: str | None = None
    currentness: KnowledgeCurrentness = KnowledgeCurrentness.CURRENT
    surface_before_work: bool = True
    authority_conflict: bool = False

    def __post_init__(self) -> None:
        for name in (
            "lesson_id", "source_revision", "title", "ecosystem", "capability_kind",
            "what_happened", "what_to_do_next_time", "guardrail",
        ):
            _text(getattr(self, name), name)
        if self.library_name is not None:
            _text(self.library_name, "library_name")
        for name in ("canonical_github_refs", "evidence_refs", "origin_refs", "keywords"):
            _refs(getattr(self, name), name)
        if type(self.currentness) is not KnowledgeCurrentness:
            raise TypeError("currentness must be KnowledgeCurrentness")
        if type(self.surface_before_work) is not bool or type(self.authority_conflict) is not bool:
            raise TypeError("boolean lesson fields must be bool")


@dataclass(frozen=True, slots=True)
class RelatedGitHubEvidence:
    reference: str
    effect: EvidenceEffect
    canonical_github_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    revised_title: str | None = None
    revised_what_happened: str | None = None
    revised_next_time: str | None = None
    revised_guardrail: str | None = None
    authority_conflict: bool = False

    def __post_init__(self) -> None:
        _text(self.reference, "reference")
        if type(self.effect) is not EvidenceEffect:
            raise TypeError("effect must be EvidenceEffect")
        for name in ("canonical_github_refs", "evidence_refs"):
            _refs(getattr(self, name), name)
        for name in ("revised_title", "revised_what_happened", "revised_next_time", "revised_guardrail"):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        if type(self.authority_conflict) is not bool:
            raise TypeError("authority_conflict must be bool")


@dataclass(frozen=True, slots=True)
class LessonRevisionProposal:
    disposition: LessonEnrichmentDisposition
    lesson_id: str
    source_revision: str
    title: str
    ecosystem: str
    capability_kind: str
    what_happened: str
    what_to_do_next_time: str
    guardrail: str
    currentness: KnowledgeCurrentness
    surface_before_work: bool
    canonical_github_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    origin_refs: tuple[str, ...]
    new_supporting_refs: tuple[str, ...]
    consolidated_from: tuple[str, ...]
    supersedes: tuple[str, ...]
    revision_reason_codes: tuple[str, ...]
    keywords: tuple[str, ...] = ()
    library_name: str | None = None
    authority_created: bool = field(default=False, init=False)
    side_effects_performed: bool = field(default=False, init=False)
    notion_write_performed: bool = field(default=False, init=False)
    github_external_mutation_performed: bool = field(default=False, init=False)
    publication_or_revision_authorized: bool = field(default=False, init=False)

    def to_lesson_record_evidence(self) -> LessonRecordEvidence | None:
        if self.disposition in {
            LessonEnrichmentDisposition.MANUAL_REVIEW,
            LessonEnrichmentDisposition.INSUFFICIENT_EVIDENCE,
            LessonEnrichmentDisposition.DISTINCT_LESSON,
        }:
            return None
        return LessonRecordEvidence(
            lesson_id=self.lesson_id,
            source_revision=self.source_revision,
            title=self.title,
            ecosystem=self.ecosystem,
            capability_kind=self.capability_kind,
            status="Applied",
            surface_before_work=self.surface_before_work,
            currentness=self.currentness,
            what_to_do_next_time=self.what_to_do_next_time,
            guardrail=self.guardrail,
            canonical_github_refs=self.canonical_github_refs,
            evidence_refs=self.evidence_refs,
            keywords=self.keywords,
            library_name=self.library_name,
            archived=False,
            authority_conflict=False,
        )

    def to_dict(self) -> dict[str, Any]:
        data = {name: getattr(self, name) for name in self.__dataclass_fields__}
        data["disposition"] = self.disposition.value
        data["currentness"] = self.currentness.value
        for name in (
            "canonical_github_refs", "evidence_refs", "origin_refs", "new_supporting_refs",
            "consolidated_from", "supersedes", "revision_reason_codes", "keywords",
        ):
            data[name] = list(data[name])
        return data


@dataclass(frozen=True, slots=True)
class LessonEnrichmentResult:
    disposition: LessonEnrichmentDisposition
    reason_codes: tuple[str, ...]
    proposal: LessonRevisionProposal | None
    candidate_lessons_considered: int
    lessons_consolidated: int
    canonical_refs_preserved: int
    estimated_retrieval_records_before: int
    after_current_synthesis_count: int
    manual_review_count: int
    authority_created: bool = field(default=False, init=False)
    side_effects_performed: bool = field(default=False, init=False)
    notion_write_performed: bool = field(default=False, init=False)
    github_external_mutation_performed: bool = field(default=False, init=False)
    publication_or_revision_authorized: bool = field(default=False, init=False)


def evaluate_lesson_enrichment(
    lesson: CurrentLessonEvidence,
    related_evidence: tuple[RelatedGitHubEvidence, ...],
    compatible_lessons: tuple[CurrentLessonEvidence, ...] = (),
) -> LessonEnrichmentResult:
    """Propose a bounded lesson revision from explicit GitHub relationship evidence."""
    if type(lesson) is not CurrentLessonEvidence:
        raise TypeError("lesson must be CurrentLessonEvidence")
    if type(related_evidence) is not tuple or any(type(x) is not RelatedGitHubEvidence for x in related_evidence):
        raise TypeError("related_evidence must be a tuple of RelatedGitHubEvidence")
    if type(compatible_lessons) is not tuple or any(type(x) is not CurrentLessonEvidence for x in compatible_lessons):
        raise TypeError("compatible_lessons must be a tuple of CurrentLessonEvidence")
    if len(related_evidence) > MAX_RELATED_EVIDENCE or len(compatible_lessons) > MAX_CONSOLIDATION_LESSONS:
        return _result(LessonEnrichmentDisposition.MANUAL_REVIEW, ("evidence-budget-exceeded",), lesson, None)
    if lesson.authority_conflict or any(x.authority_conflict for x in related_evidence + compatible_lessons):
        return _result(LessonEnrichmentDisposition.MANUAL_REVIEW, ("canonical-authority-conflict",), lesson, None)
    if lesson.currentness is not KnowledgeCurrentness.CURRENT:
        return _result(LessonEnrichmentDisposition.MANUAL_REVIEW, ("base-lesson-not-current",), lesson, None)
    if any(x.currentness is not KnowledgeCurrentness.CURRENT for x in compatible_lessons):
        return _result(LessonEnrichmentDisposition.MANUAL_REVIEW, ("consolidation-candidate-not-current",), lesson, None)

    material = tuple(x for x in related_evidence if x.effect is not EvidenceEffect.INCIDENTAL)
    if not material and not compatible_lessons:
        disposition = LessonEnrichmentDisposition.INSUFFICIENT_EVIDENCE if related_evidence else LessonEnrichmentDisposition.UNCHANGED
        reason = "only-incidental-related-evidence" if related_evidence else "no-new-evidence"
        return _result(disposition, (reason,), lesson, None)
    if any(x.effect is EvidenceEffect.CONTRADICTS for x in material):
        return _result(LessonEnrichmentDisposition.MANUAL_REVIEW, ("contradictory-related-evidence",), lesson, None)
    if any(x.effect is EvidenceEffect.DISTINCT_CAUSE for x in material):
        return _result(LessonEnrichmentDisposition.DISTINCT_LESSON, ("materially-distinct-cause",), lesson, None)

    effects = {x.effect for x in material}
    if EvidenceEffect.SUPERSEDES in effects and len(effects - {EvidenceEffect.CONFIRMS, EvidenceEffect.SUPERSEDES}) > 0:
        return _result(LessonEnrichmentDisposition.MANUAL_REVIEW, ("mixed-supersession-evidence",), lesson, None)

    if compatible_lessons:
        if material and effects - {EvidenceEffect.CONFIRMS}:
            return _result(LessonEnrichmentDisposition.MANUAL_REVIEW, ("consolidation-with-material-rewrite",), lesson, None)
        if any(not _compatible(lesson, item) for item in compatible_lessons):
            return _result(LessonEnrichmentDisposition.DISTINCT_LESSON, ("consolidation-guidance-differs",), lesson, None)
        disposition = LessonEnrichmentDisposition.CONSOLIDATE_COMPATIBLE
        reasons = ("compatible-lessons-consolidated",)
    elif EvidenceEffect.SUPERSEDES in effects:
        disposition = LessonEnrichmentDisposition.SUPERSEDE_EXISTING
        reasons = ("current-github-evidence-supersedes-guidance",)
    elif effects & {EvidenceEffect.IMPROVES_ROOT_CAUSE, EvidenceEffect.ADDS_GUARDRAIL}:
        disposition = LessonEnrichmentDisposition.ENRICH_EXISTING
        reasons = tuple(sorted("effect:" + effect.value for effect in effects if effect is not EvidenceEffect.CONFIRMS))
    else:
        disposition = LessonEnrichmentDisposition.UNCHANGED
        reasons = ("confirming-evidence-added",)

    proposal = _proposal(lesson, material, compatible_lessons, disposition, reasons)
    if proposal is None:
        return _result(LessonEnrichmentDisposition.MANUAL_REVIEW, ("reference-budget-exceeded",), lesson, None)
    return _result(disposition, reasons, lesson, proposal, compatible_lessons)


def _proposal(lesson, evidence, compatible, disposition, reasons):
    canonical = _union(lesson.canonical_github_refs, *(x.canonical_github_refs for x in evidence), *(x.canonical_github_refs for x in compatible))
    evidence_refs = _union(lesson.evidence_refs, *(x.evidence_refs for x in evidence), *(x.evidence_refs for x in compatible))
    origins = _union(lesson.origin_refs, *(x.origin_refs for x in compatible))
    supporting = _union(*( (x.reference,) for x in evidence)) if evidence else ()
    if canonical is None or evidence_refs is None or origins is None or supporting is None:
        return None
    title, happened, next_time, guardrail = lesson.title, lesson.what_happened, lesson.what_to_do_next_time, lesson.guardrail
    for item in evidence:
        title = item.revised_title or title
        happened = item.revised_what_happened or happened
        next_time = item.revised_next_time or next_time
        guardrail = item.revised_guardrail or guardrail
    if disposition is LessonEnrichmentDisposition.SUPERSEDE_EXISTING:
        currentness = KnowledgeCurrentness.STALE
        surface = False
        supersedes = (lesson.lesson_id,)
    else:
        currentness = KnowledgeCurrentness.CURRENT
        surface = lesson.surface_before_work
        supersedes = ()
    consolidated = tuple(sorted(x.lesson_id for x in compatible))
    source_revision = supporting[-1] if supporting else lesson.source_revision
    return LessonRevisionProposal(
        disposition=disposition, lesson_id=lesson.lesson_id, source_revision=source_revision,
        title=title, ecosystem=lesson.ecosystem, capability_kind=lesson.capability_kind,
        what_happened=happened, what_to_do_next_time=next_time, guardrail=guardrail,
        currentness=currentness, surface_before_work=surface,
        canonical_github_refs=canonical, evidence_refs=evidence_refs, origin_refs=origins,
        new_supporting_refs=supporting, consolidated_from=consolidated, supersedes=supersedes,
        revision_reason_codes=reasons, keywords=lesson.keywords, library_name=lesson.library_name,
    )


def _result(disposition, reasons, lesson, proposal, compatible=()):
    before = 1 + len(compatible)
    return LessonEnrichmentResult(
        disposition=disposition, reason_codes=reasons, proposal=proposal,
        candidate_lessons_considered=before,
        lessons_consolidated=len(compatible) if disposition is LessonEnrichmentDisposition.CONSOLIDATE_COMPATIBLE else 0,
        canonical_refs_preserved=len(proposal.canonical_github_refs) if proposal else len(lesson.canonical_github_refs),
        estimated_retrieval_records_before=before,
        after_current_synthesis_count=1 if proposal and disposition is not LessonEnrichmentDisposition.SUPERSEDE_EXISTING else before,
        manual_review_count=1 if disposition is LessonEnrichmentDisposition.MANUAL_REVIEW else 0,
    )


def _compatible(left: CurrentLessonEvidence, right: CurrentLessonEvidence) -> bool:
    return (
        left.ecosystem.casefold() == right.ecosystem.casefold()
        and left.capability_kind.casefold() == right.capability_kind.casefold()
        and (left.library_name or "").casefold() == (right.library_name or "").casefold()
        and left.what_to_do_next_time.strip().casefold() == right.what_to_do_next_time.strip().casefold()
        and left.guardrail.strip().casefold() == right.guardrail.strip().casefold()
    )


def _union(*groups: tuple[str, ...]) -> tuple[str, ...] | None:
    values = tuple(sorted({item for group in groups for item in group}))
    return values if len(values) <= MAX_REFS else None


def _text(value: object, name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must be non-empty")
    if len(value) > MAX_TEXT:
        raise ValueError(f"{name} is oversized")


def _refs(value: object, name: str) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be a tuple")
    if len(value) > MAX_REFS:
        raise ValueError(f"{name} is oversized")
    for item in value:
        _text(item, name)
