from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from .grading_decision import IdentityEvidence, IdentityResolution


GRADEBOOK_READER_SCHEMA_VERSION = "1.0"


class ReaderStatus(str, Enum):
    READ_SUCCESS = "read-success"
    AMBIGUOUS_STUDENT = "ambiguous-student"
    AMBIGUOUS_ASSIGNMENT = "ambiguous-assignment"
    NOT_FOUND = "not-found"
    READ_ONLY = "read-only"
    STALE_STATE = "stale-state"
    SELECTOR_DRIFT = "selector-drift"
    AUTHENTICATION_REQUIRED = "authentication-required"
    UNSUPPORTED_PAGE = "unsupported-page"
    READER_ERROR = "reader-error"


class ReaderFreshness(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


class Editability(str, Enum):
    EDITABLE = "editable"
    READ_ONLY = "read-only"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    evidence_refs: tuple[str, ...]
    selector_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _strings(self.evidence_refs, "evidence_refs", allow_empty=False))
        object.__setattr__(self, "selector_refs", _strings(self.selector_refs, "selector_refs", allow_empty=True))


@dataclass(frozen=True, slots=True)
class GradebookReaderResult:
    platform: str
    course_id: str
    student: IdentityEvidence
    assignment: IdentityEvidence
    visible_score: str | None
    visible_feedback: str | None
    editability: Editability
    freshness: ReaderFreshness
    provenance: EvidenceProvenance
    status: ReaderStatus
    confidence: Decimal
    schema_version: str = GRADEBOOK_READER_SCHEMA_VERSION
    write_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != GRADEBOOK_READER_SCHEMA_VERSION:
            raise ValueError("unsupported gradebook reader schema version")
        if not isinstance(self.student, IdentityEvidence):
            raise TypeError("student must be IdentityEvidence")
        if not isinstance(self.assignment, IdentityEvidence):
            raise TypeError("assignment must be IdentityEvidence")
        if not isinstance(self.editability, Editability):
            raise TypeError("editability must use Editability")
        if not isinstance(self.freshness, ReaderFreshness):
            raise TypeError("freshness must use ReaderFreshness")
        if not isinstance(self.provenance, EvidenceProvenance):
            raise TypeError("provenance must be EvidenceProvenance")
        if not isinstance(self.status, ReaderStatus):
            raise TypeError("status must use ReaderStatus")

        object.__setattr__(self, "platform", _text(self.platform, "platform"))
        object.__setattr__(self, "course_id", _text(self.course_id, "course_id"))
        object.__setattr__(self, "visible_score", _optional_text(self.visible_score, "visible_score"))
        object.__setattr__(self, "visible_feedback", _optional_text(self.visible_feedback, "visible_feedback"))
        confidence = Decimal(str(self.confidence))
        if not confidence.is_finite() or confidence < 0 or confidence > 1:
            raise ValueError("confidence must be finite and between 0 and 1")
        object.__setattr__(self, "confidence", confidence.normalize())
        self._validate_status_contract()

    def _validate_status_contract(self) -> None:
        if self.status == ReaderStatus.READ_SUCCESS:
            if self.student.resolution != IdentityResolution.RESOLVED:
                raise ValueError("read-success requires resolved student identity")
            if self.assignment.resolution != IdentityResolution.RESOLVED:
                raise ValueError("read-success requires resolved assignment identity")
            if self.freshness != ReaderFreshness.CURRENT:
                raise ValueError("read-success requires current evidence")
        elif self.status == ReaderStatus.AMBIGUOUS_STUDENT:
            if self.student.resolution != IdentityResolution.AMBIGUOUS:
                raise ValueError("ambiguous-student requires ambiguous student evidence")
        elif self.status == ReaderStatus.AMBIGUOUS_ASSIGNMENT:
            if self.assignment.resolution != IdentityResolution.AMBIGUOUS:
                raise ValueError("ambiguous-assignment requires ambiguous assignment evidence")
        elif self.status == ReaderStatus.STALE_STATE:
            if self.freshness != ReaderFreshness.STALE:
                raise ValueError("stale-state requires stale freshness")
        elif self.status == ReaderStatus.READ_ONLY:
            if self.editability != Editability.READ_ONLY:
                raise ValueError("read-only requires read-only editability")

    @property
    def reader_evidence_id(self) -> str:
        return f"gradebook-reader:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"

    def canonical_bytes(self) -> bytes:
        return json.dumps(self._payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def to_record(self) -> dict[str, Any]:
        return {**self._payload(), "reader_evidence_id": self.reader_evidence_id, "write_authorized": False}

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "platform": self.platform,
            "course_id": self.course_id,
            "student": _identity_payload(self.student),
            "assignment": _identity_payload(self.assignment),
            "visible_score": self.visible_score,
            "visible_feedback": self.visible_feedback,
            "editability": self.editability.value,
            "freshness": self.freshness.value,
            "provenance": {
                "evidence_refs": list(self.provenance.evidence_refs),
                "selector_refs": list(self.provenance.selector_refs),
            },
            "status": self.status.value,
            "confidence": _decimal_text(self.confidence),
        }


def normalize_reader_record(record: dict[str, Any]) -> GradebookReaderResult:
    if not isinstance(record, dict):
        raise TypeError("reader record must be a mapping")
    try:
        return GradebookReaderResult(
            platform=record["platform"],
            course_id=record["course_id"],
            student=_identity_from_record(record["student"]),
            assignment=_identity_from_record(record["assignment"]),
            visible_score=record.get("visible_score"),
            visible_feedback=record.get("visible_feedback"),
            editability=Editability(record["editability"]),
            freshness=ReaderFreshness(record["freshness"]),
            provenance=EvidenceProvenance(
                evidence_refs=tuple(record["provenance"]["evidence_refs"]),
                selector_refs=tuple(record["provenance"].get("selector_refs", ())),
            ),
            status=ReaderStatus(record["status"]),
            confidence=Decimal(str(record["confidence"])),
            schema_version=record.get("schema_version", GRADEBOOK_READER_SCHEMA_VERSION),
        )
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError("malformed gradebook reader record") from exc


def _identity_from_record(record: dict[str, Any]) -> IdentityEvidence:
    if not isinstance(record, dict):
        raise TypeError("identity evidence must be a mapping")
    return IdentityEvidence(
        resolution=IdentityResolution(record["resolution"]),
        resolved_id=record.get("resolved_id"),
        evidence_refs=tuple(record["evidence_refs"]),
        confidence=Decimal(str(record["confidence"])),
    )


def _identity_payload(value: IdentityEvidence) -> dict[str, Any]:
    return {
        "resolution": value.resolution.value,
        "resolved_id": value.resolved_id,
        "evidence_refs": list(value.evidence_refs),
        "confidence": _decimal_text(value.confidence),
    }


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


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text == "-0" else text
