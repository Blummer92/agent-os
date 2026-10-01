from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .gradebook_reader import (
    Editability,
    EvidenceProvenance,
    GradebookReaderResult,
    ReaderFreshness,
    ReaderStatus,
)
from .grading_decision import IdentityEvidence, IdentityResolution


class PowerSchoolPageState(str, Enum):
    READY = "ready"
    AUTHENTICATION_REQUIRED = "authentication-required"
    UNSUPPORTED_PAGE = "unsupported-page"
    READER_ERROR = "reader-error"


@dataclass(frozen=True, slots=True)
class PowerSchoolIdentityCandidate:
    identity_id: str
    evidence_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "identity_id", _text(self.identity_id, "identity_id"))
        object.__setattr__(self, "evidence_ref", _text(self.evidence_ref, "evidence_ref"))


@dataclass(frozen=True, slots=True)
class PowerSchoolGradebookSnapshot:
    course_id: str
    student_candidates: tuple[PowerSchoolIdentityCandidate, ...]
    assignment_candidates: tuple[PowerSchoolIdentityCandidate, ...]
    visible_score: str | None
    visible_feedback: str | None
    editable: bool
    freshness: ReaderFreshness
    evidence_refs: tuple[str, ...]
    selector_refs: tuple[str, ...] = ()
    selector_drift: bool = False
    page_state: PowerSchoolPageState = PowerSchoolPageState.READY

    def __post_init__(self) -> None:
        object.__setattr__(self, "course_id", _text(self.course_id, "course_id"))
        if not isinstance(self.freshness, ReaderFreshness):
            raise TypeError("freshness must use ReaderFreshness")
        if not isinstance(self.page_state, PowerSchoolPageState):
            raise TypeError("page_state must use PowerSchoolPageState")
        if not isinstance(self.editable, bool):
            raise TypeError("editable must be bool")
        if not isinstance(self.selector_drift, bool):
            raise TypeError("selector_drift must be bool")
        object.__setattr__(self, "evidence_refs", _strings(self.evidence_refs, "evidence_refs", allow_empty=False))
        object.__setattr__(self, "selector_refs", _strings(self.selector_refs, "selector_refs", allow_empty=True))
        object.__setattr__(self, "visible_score", _optional_text(self.visible_score, "visible_score"))
        object.__setattr__(self, "visible_feedback", _optional_text(self.visible_feedback, "visible_feedback"))


def normalize_powerschool_snapshot(snapshot: PowerSchoolGradebookSnapshot) -> GradebookReaderResult:
    if not isinstance(snapshot, PowerSchoolGradebookSnapshot):
        raise TypeError("snapshot must be PowerSchoolGradebookSnapshot")

    student = _identity(snapshot.student_candidates, "student")
    assignment = _identity(snapshot.assignment_candidates, "assignment")
    status = _status(snapshot, student, assignment)

    return GradebookReaderResult(
        platform="powerschool",
        course_id=snapshot.course_id,
        student=student,
        assignment=assignment,
        visible_score=snapshot.visible_score,
        visible_feedback=snapshot.visible_feedback,
        editability=Editability.EDITABLE if snapshot.editable else Editability.READ_ONLY,
        freshness=snapshot.freshness,
        provenance=EvidenceProvenance(snapshot.evidence_refs, snapshot.selector_refs),
        status=status,
        confidence=min(student.confidence, assignment.confidence),
    )


def _status(
    snapshot: PowerSchoolGradebookSnapshot,
    student: IdentityEvidence,
    assignment: IdentityEvidence,
) -> ReaderStatus:
    if snapshot.page_state == PowerSchoolPageState.AUTHENTICATION_REQUIRED:
        return ReaderStatus.AUTHENTICATION_REQUIRED
    if snapshot.page_state == PowerSchoolPageState.UNSUPPORTED_PAGE:
        return ReaderStatus.UNSUPPORTED_PAGE
    if snapshot.page_state == PowerSchoolPageState.READER_ERROR:
        return ReaderStatus.READER_ERROR
    if snapshot.selector_drift:
        return ReaderStatus.SELECTOR_DRIFT
    if student.resolution == IdentityResolution.AMBIGUOUS:
        return ReaderStatus.AMBIGUOUS_STUDENT
    if assignment.resolution == IdentityResolution.AMBIGUOUS:
        return ReaderStatus.AMBIGUOUS_ASSIGNMENT
    if student.resolution == IdentityResolution.NOT_FOUND or assignment.resolution == IdentityResolution.NOT_FOUND:
        return ReaderStatus.NOT_FOUND
    if snapshot.freshness == ReaderFreshness.STALE:
        return ReaderStatus.STALE_STATE
    if not snapshot.editable:
        return ReaderStatus.READ_ONLY
    if snapshot.freshness != ReaderFreshness.CURRENT:
        return ReaderStatus.READER_ERROR
    return ReaderStatus.READ_SUCCESS


def _identity(candidates: tuple[PowerSchoolIdentityCandidate, ...], kind: str) -> IdentityEvidence:
    if not candidates:
        return IdentityEvidence(
            IdentityResolution.NOT_FOUND,
            None,
            (f"powerschool:{kind}:not-found",),
            Decimal("0"),
        )
    if len(candidates) > 1:
        refs = tuple(sorted(candidate.evidence_ref for candidate in candidates))
        return IdentityEvidence(IdentityResolution.AMBIGUOUS, None, refs, Decimal("0.5"))
    candidate = candidates[0]
    return IdentityEvidence(
        IdentityResolution.RESOLVED,
        candidate.identity_id,
        (candidate.evidence_ref,),
        Decimal("1"),
    )


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text or null")
    return value.strip()


def _strings(values: tuple[str, ...], name: str, *, allow_empty: bool) -> tuple[str, ...]:
    normalized = tuple(sorted({_text(value, name) for value in values}))
    if not normalized and not allow_empty:
        raise ValueError(f"{name} cannot be empty")
    return normalized
