"""Deterministic failure-to-lesson qualification and publication proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any

from .coding_knowledge_selection import CodingKnowledgeCandidate, KnowledgeCurrentness

MAX_EXISTING_LESSONS = 8
MAX_ITEMS = 20
MAX_TEXT_CHARS = 512
MAX_DETAIL_CHARS = 1024
MAX_RECURRENCE_COUNT = 1_000_000
IDENTITY_VERSION = "ckr5-lesson-v1"


class FailureKind(str, Enum):
    CODE_DEFECT = "code-defect"
    TEST_FAILURE = "test-failure"
    REVIEW_FINDING = "review-finding"
    ROUTING_FAILURE = "routing-failure"
    VALIDATION_FAILURE = "validation-failure"
    HUMAN_CORRECTION = "human-correction"
    ONE_OFF = "one-off"
    TRIVIAL = "trivial"
    TRANSIENT_ENVIRONMENT = "transient-environment"
    FLAKY_INFRASTRUCTURE = "flaky-infrastructure"
    ALREADY_CANONICAL = "already-canonical"


class LessonDisposition(str, Enum):
    REUSABLE_NEW = "reusable-new"
    REUSABLE_RECURRENCE = "reusable-recurrence"
    NON_REUSABLE = "non-reusable"
    MANUAL_REVIEW = "manual-review"
    INSUFFICIENT_EVIDENCE = "insufficient-evidence"


_NON_REUSABLE = frozenset(
    {
        FailureKind.ONE_OFF,
        FailureKind.TRIVIAL,
        FailureKind.TRANSIENT_ENVIRONMENT,
        FailureKind.FLAKY_INFRASTRUCTURE,
        FailureKind.ALREADY_CANONICAL,
    }
)


@dataclass(frozen=True, slots=True)
class FailureObservation:
    source_reference: str
    failure_kind: FailureKind
    failure_signature: str
    ecosystem: str
    capability_kind: str
    library_name: str | None
    lesson_summary: str
    what_happened: str
    what_to_do_next_time: str | None
    guardrail: str | None
    learning_type: str
    severity: str
    owner_agent: str
    canonical_github_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    future_use_hints: tuple[str, ...] = ()
    currentness: KnowledgeCurrentness = KnowledgeCurrentness.CURRENT
    reusable_rule: bool = True
    authority_conflict: bool = False

    def __post_init__(self) -> None:
        for name in (
            "source_reference", "failure_signature", "ecosystem", "capability_kind",
            "lesson_summary", "learning_type", "severity", "owner_agent",
        ):
            _text(getattr(self, name), name)
        _text(self.what_happened, "what_happened", MAX_DETAIL_CHARS)
        for name in ("library_name", "what_to_do_next_time", "guardrail"):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        for name in ("canonical_github_refs", "evidence_refs", "future_use_hints"):
            _items(getattr(self, name), name)
        if type(self.failure_kind) is not FailureKind:
            raise TypeError("failure_kind must be a FailureKind value")
        if type(self.currentness) is not KnowledgeCurrentness:
            raise TypeError("currentness must be a KnowledgeCurrentness value")
        if type(self.reusable_rule) is not bool or type(self.authority_conflict) is not bool:
            raise TypeError("reusable_rule and authority_conflict must be bool")


@dataclass(frozen=True, slots=True)
class ExistingLesson:
    knowledge_id: str
    failure_kind: FailureKind
    failure_signature: str
    ecosystem: str
    capability_kind: str
    library_name: str | None
    lesson_summary: str
    what_to_do_next_time: str
    guardrail: str
    recurrence_count: int
    currentness: KnowledgeCurrentness
    canonical_github_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    authority_conflict: bool = False

    def __post_init__(self) -> None:
        for name in (
            "knowledge_id", "failure_signature", "ecosystem", "capability_kind",
            "lesson_summary", "what_to_do_next_time", "guardrail",
        ):
            _text(getattr(self, name), name)
        if self.library_name is not None:
            _text(self.library_name, "library_name")
        _items(self.canonical_github_refs, "canonical_github_refs")
        _items(self.evidence_refs, "evidence_refs")
        if type(self.failure_kind) is not FailureKind:
            raise TypeError("failure_kind must be a FailureKind value")
        if type(self.currentness) is not KnowledgeCurrentness:
            raise TypeError("currentness must be a KnowledgeCurrentness value")
        if type(self.recurrence_count) is not int or isinstance(self.recurrence_count, bool):
            raise TypeError("recurrence_count must be an integer")
        if not 1 <= self.recurrence_count <= MAX_RECURRENCE_COUNT:
            raise ValueError("recurrence_count is out of bounds")
        if type(self.authority_conflict) is not bool:
            raise TypeError("authority_conflict must be a bool")

    def computed_core_identity(self) -> str:
        return _core_identity(self)

    def computed_knowledge_id(self) -> str:
        return _lesson_identity(
            self.computed_core_identity(), self.what_to_do_next_time, self.guardrail
        )


@dataclass(frozen=True, slots=True)
class LessonPublicationProposal:
    operation: str
    lesson_identity: str
    core_identity: str
    lesson_summary: str
    what_happened: str
    what_to_do_next_time: str
    learning_type: str
    severity: str
    guardrail: str
    owner_agent: str
    source_reference: str
    evidence_refs: tuple[str, ...]
    recurrence_evidence: tuple[str, ...]
    proposed_recurrence_count: int
    surface_before_work: bool
    currentness: KnowledgeCurrentness
    canonical_github_refs: tuple[str, ...]
    authority_created: bool = field(default=False, init=False)
    side_effects_performed: bool = field(default=False, init=False)
    notion_write_performed: bool = field(default=False, init=False)
    github_write_performed: bool = field(default=False, init=False)
    publication_authorized: bool = field(default=False, init=False)

    def to_dict(self) -> dict[str, Any]:
        data = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }
        data["currentness"] = self.currentness.value
        for name in ("evidence_refs", "recurrence_evidence", "canonical_github_refs"):
            data[name] = list(data[name])
        return data


@dataclass(frozen=True, slots=True)
class LessonLearningResult:
    disposition: LessonDisposition
    reason_codes: tuple[str, ...]
    lesson_identity: str | None = None
    core_identity: str | None = None
    proposal: LessonPublicationProposal | None = None
    ecosystem: str | None = None
    library_name: str | None = None
    capability_kind: str | None = None
    future_use_hints: tuple[str, ...] = ()
    authority_created: bool = field(default=False, init=False)
    side_effects_performed: bool = field(default=False, init=False)
    notion_write_performed: bool = field(default=False, init=False)
    github_write_performed: bool = field(default=False, init=False)
    publication_authorized: bool = field(default=False, init=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "reason_codes": list(self.reason_codes),
            "lesson_identity": self.lesson_identity,
            "core_identity": self.core_identity,
            "proposal": self.proposal.to_dict() if self.proposal else None,
            "ecosystem": self.ecosystem,
            "library_name": self.library_name,
            "capability_kind": self.capability_kind,
            "future_use_hints": list(self.future_use_hints),
            "authority_created": self.authority_created,
            "side_effects_performed": self.side_effects_performed,
            "notion_write_performed": self.notion_write_performed,
            "github_write_performed": self.github_write_performed,
            "publication_authorized": self.publication_authorized,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def to_coding_knowledge_candidate(self) -> CodingKnowledgeCandidate | None:
        proposal = self.proposal
        if (
            proposal is None
            or not proposal.surface_before_work
            or proposal.currentness is not KnowledgeCurrentness.CURRENT
            or self.disposition not in {
                LessonDisposition.REUSABLE_NEW,
                LessonDisposition.REUSABLE_RECURRENCE,
            }
        ):
            return None
        return CodingKnowledgeCandidate(
            knowledge_id=proposal.lesson_identity,
            source_system="lesson-publication-proposal",
            source_revision=proposal.source_reference,
            currentness=proposal.currentness,
            name=proposal.lesson_summary,
            ecosystem=self.ecosystem or "unknown",
            library_name=self.library_name,
            capability_kind=self.capability_kind or "unknown",
            keywords=self.future_use_hints,
            use_when=(proposal.what_to_do_next_time, proposal.guardrail),
            avoid_when=(),
            canonical_github_refs=proposal.canonical_github_refs,
            evidence_refs=proposal.evidence_refs,
            authority_conflict=False,
        )


def evaluate_coding_failure(
    observation: FailureObservation,
    existing_lessons: tuple[ExistingLesson, ...] = (),
) -> LessonLearningResult:
    """Return a bounded, authority-false lesson decision from supplied evidence."""
    if type(observation) is not FailureObservation:
        raise TypeError("observation must be a FailureObservation")
    if type(existing_lessons) is not tuple or any(
        type(item) is not ExistingLesson for item in existing_lessons
    ):
        raise TypeError("existing_lessons must be a tuple of ExistingLesson values")
    if len(existing_lessons) > MAX_EXISTING_LESSONS:
        return _result(LessonDisposition.MANUAL_REVIEW, "existing-lesson-budget-exceeded")

    if observation.authority_conflict:
        return _result(LessonDisposition.MANUAL_REVIEW, "canonical-authority-conflict")
    if observation.currentness is not KnowledgeCurrentness.CURRENT:
        return _result(
            LessonDisposition.MANUAL_REVIEW,
            f"{observation.currentness.value}-source-evidence",
        )
    if observation.failure_kind in _NON_REUSABLE:
        return _result(
            LessonDisposition.NON_REUSABLE,
            f"non-reusable-kind:{observation.failure_kind.value}",
        )
    if not observation.reusable_rule:
        return _result(LessonDisposition.NON_REUSABLE, "no-reusable-rule")
    if observation.what_to_do_next_time is None or observation.guardrail is None:
        return _result(LessonDisposition.INSUFFICIENT_EVIDENCE, "missing-reusable-guidance")
    if not observation.canonical_github_refs:
        return _result(LessonDisposition.INSUFFICIENT_EVIDENCE, "canonical-reference-missing")
    if not observation.evidence_refs:
        return _result(LessonDisposition.INSUFFICIENT_EVIDENCE, "evidence-reference-missing")

    core_id = _core_identity(observation)
    lesson_id = _lesson_identity(
        core_id, observation.what_to_do_next_time, observation.guardrail
    )
    if any(item.knowledge_id != item.computed_knowledge_id() for item in existing_lessons):
        return _result(LessonDisposition.MANUAL_REVIEW, "existing-identity-conflict", lesson_id, core_id)

    exact = tuple(item for item in existing_lessons if item.knowledge_id == lesson_id)
    if len(exact) > 1:
        return _result(LessonDisposition.MANUAL_REVIEW, "duplicate-existing-identity", lesson_id, core_id)
    if exact:
        item = exact[0]
        if item.authority_conflict:
            return _result(LessonDisposition.MANUAL_REVIEW, "canonical-authority-conflict", lesson_id, core_id)
        if item.currentness is not KnowledgeCurrentness.CURRENT:
            return _result(LessonDisposition.MANUAL_REVIEW, "existing-lesson-not-current", lesson_id, core_id)
        if item.recurrence_count >= MAX_RECURRENCE_COUNT:
            return _result(LessonDisposition.MANUAL_REVIEW, "recurrence-count-exhausted", lesson_id, core_id)
        evidence = _union(item.evidence_refs, observation.evidence_refs)
        canonical = _union(item.canonical_github_refs, observation.canonical_github_refs)
        if evidence is None or canonical is None:
            return _result(LessonDisposition.MANUAL_REVIEW, "proposal-reference-budget-exceeded", lesson_id, core_id)
        proposal = _proposal(
            observation, lesson_id, core_id, "increment-recurrence",
            item.recurrence_count + 1, evidence, canonical,
        )
        return _result(
            LessonDisposition.REUSABLE_RECURRENCE,
            "existing-lesson-recurrence",
            lesson_id, core_id, proposal, observation,
        )

    related = tuple(
        item for item in existing_lessons if item.computed_core_identity() == core_id
    )
    if len(related) > 1:
        return _result(LessonDisposition.MANUAL_REVIEW, "ambiguous-related-lessons", lesson_id, core_id)
    reason = "new-materially-distinct-lesson" if related else "new-reusable-lesson"
    proposal = _proposal(
        observation, lesson_id, core_id, "create", 1,
        observation.evidence_refs, observation.canonical_github_refs,
    )
    return _result(
        LessonDisposition.REUSABLE_NEW, reason, lesson_id, core_id, proposal, observation
    )


def _proposal(
    observation: FailureObservation,
    lesson_id: str,
    core_id: str,
    operation: str,
    recurrence_count: int,
    recurrence_evidence: tuple[str, ...],
    canonical_refs: tuple[str, ...],
) -> LessonPublicationProposal:
    return LessonPublicationProposal(
        operation=operation,
        lesson_identity=lesson_id,
        core_identity=core_id,
        lesson_summary=observation.lesson_summary,
        what_happened=observation.what_happened,
        what_to_do_next_time=observation.what_to_do_next_time or "",
        learning_type=observation.learning_type,
        severity=observation.severity,
        guardrail=observation.guardrail or "",
        owner_agent=observation.owner_agent,
        source_reference=observation.source_reference,
        evidence_refs=tuple(sorted(set(observation.evidence_refs))),
        recurrence_evidence=tuple(sorted(set(recurrence_evidence))),
        proposed_recurrence_count=recurrence_count,
        surface_before_work=bool(observation.future_use_hints),
        currentness=observation.currentness,
        canonical_github_refs=tuple(sorted(set(canonical_refs))),
    )


def _result(
    disposition: LessonDisposition,
    reason: str,
    lesson_id: str | None = None,
    core_id: str | None = None,
    proposal: LessonPublicationProposal | None = None,
    observation: FailureObservation | None = None,
) -> LessonLearningResult:
    return LessonLearningResult(
        disposition=disposition,
        reason_codes=(reason,),
        lesson_identity=lesson_id,
        core_identity=core_id,
        proposal=proposal,
        ecosystem=observation.ecosystem if observation else None,
        library_name=observation.library_name if observation else None,
        capability_kind=observation.capability_kind if observation else None,
        future_use_hints=tuple(sorted(set(observation.future_use_hints))) if observation else (),
    )


def _core_identity(value: FailureObservation | ExistingLesson) -> str:
    return "lesson-core:sha256:" + _digest(
        {
            "version": IDENTITY_VERSION,
            "failure_kind": value.failure_kind.value,
            "failure_signature": _norm(value.failure_signature),
            "ecosystem": _norm(value.ecosystem),
            "capability_kind": _norm(value.capability_kind),
            "library_name": _norm(value.library_name) if value.library_name else None,
        }
    )


def _lesson_identity(core_id: str, next_time: str, guardrail: str) -> str:
    return "lesson:sha256:" + _digest(
        {
            "version": IDENTITY_VERSION,
            "core_identity": core_id,
            "what_to_do_next_time": _norm(next_time),
            "guardrail": _norm(guardrail),
        }
    )


def _digest(value: dict[str, Any]) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _union(first: tuple[str, ...], second: tuple[str, ...]) -> tuple[str, ...] | None:
    result = tuple(sorted(set(first + second)))
    return result if len(result) <= MAX_ITEMS else None


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def _text(value: object, name: str, maximum: int = MAX_TEXT_CHARS) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must be non-empty")
    if len(value) > maximum:
        raise ValueError(f"{name} is oversized")
    if any(ord(char) < 32 and char != "\t" for char in value):
        raise ValueError(f"{name} contains control characters")


def _items(value: object, name: str) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be a tuple")
    if len(value) > MAX_ITEMS:
        raise ValueError(f"{name} is oversized")
    for item in value:
        _text(item, name)
