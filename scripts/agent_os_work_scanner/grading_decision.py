from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Literal


GRADING_DECISION_SCHEMA_VERSION = "1.0"


class IdentityResolution(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not-found"


class EvidenceFreshness(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


class TeacherApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    resolution: IdentityResolution
    resolved_id: str | None
    evidence_refs: tuple[str, ...]
    confidence: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.resolution, IdentityResolution):
            raise TypeError("resolution must use IdentityResolution")
        refs = _strings(self.evidence_refs, "evidence_refs", allow_empty=False)
        confidence = _decimal(self.confidence, "confidence", minimum=Decimal("0"), maximum=Decimal("1"))
        if self.resolution == IdentityResolution.RESOLVED:
            resolved_id = _text(self.resolved_id, "resolved_id")
        elif self.resolved_id is not None:
            raise ValueError("unresolved identity evidence cannot carry resolved_id")
        else:
            resolved_id = None
        object.__setattr__(self, "resolved_id", resolved_id)
        object.__setattr__(self, "evidence_refs", refs)
        object.__setattr__(self, "confidence", confidence)


@dataclass(frozen=True, slots=True)
class RubricCriterionEvidence:
    criterion_id: str
    description: str
    possible_points: Decimal
    awarded_points: Decimal
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        criterion_id = _text(self.criterion_id, "criterion_id")
        description = _text(self.description, "description")
        possible = _decimal(self.possible_points, "possible_points", minimum=Decimal("0"))
        awarded = _decimal(self.awarded_points, "awarded_points", minimum=Decimal("0"))
        if awarded > possible:
            raise ValueError("awarded_points cannot exceed possible_points")
        object.__setattr__(self, "criterion_id", criterion_id)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "possible_points", possible)
        object.__setattr__(self, "awarded_points", awarded)
        object.__setattr__(
            self,
            "evidence_refs",
            _strings(self.evidence_refs, "evidence_refs", allow_empty=False),
        )


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    source_type: str
    source_id: str
    content_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", _text(self.source_type, "source_type"))
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        digest = _text(self.content_digest, "content_digest").lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("content_digest must be a lowercase SHA-256 hex digest")
        object.__setattr__(self, "content_digest", digest)


@dataclass(frozen=True, slots=True)
class GradingDecision:
    student: IdentityEvidence
    assignment: IdentityEvidence
    rubric: tuple[RubricCriterionEvidence, ...]
    proposed_score: Decimal
    max_score: Decimal
    feedback: str
    confidence: Decimal
    uncertainty_reasons: tuple[str, ...]
    approval_state: TeacherApprovalState
    freshness: EvidenceFreshness
    provenance: tuple[SourceProvenance, ...]
    target_platforms: tuple[str, ...]
    schema_version: str = GRADING_DECISION_SCHEMA_VERSION
    write_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != GRADING_DECISION_SCHEMA_VERSION:
            raise ValueError("unsupported grading decision schema version")
        if not isinstance(self.student, IdentityEvidence):
            raise TypeError("student must be IdentityEvidence")
        if not isinstance(self.assignment, IdentityEvidence):
            raise TypeError("assignment must be IdentityEvidence")
        if not isinstance(self.approval_state, TeacherApprovalState):
            raise TypeError("approval_state must use TeacherApprovalState")
        if not isinstance(self.freshness, EvidenceFreshness):
            raise TypeError("freshness must use EvidenceFreshness")

        rubric = tuple(self.rubric)
        if not rubric or any(not isinstance(item, RubricCriterionEvidence) for item in rubric):
            raise ValueError("rubric must contain RubricCriterionEvidence entries")
        ids = [item.criterion_id for item in rubric]
        if len(set(ids)) != len(ids):
            raise ValueError("rubric criterion_id values must be unique")
        rubric = tuple(sorted(rubric, key=lambda item: item.criterion_id))

        proposed = _decimal(self.proposed_score, "proposed_score", minimum=Decimal("0"))
        maximum = _decimal(self.max_score, "max_score", minimum=Decimal("0.000000001"))
        if proposed > maximum:
            raise ValueError("proposed_score cannot exceed max_score")
        rubric_possible = sum((item.possible_points for item in rubric), Decimal("0"))
        rubric_awarded = sum((item.awarded_points for item in rubric), Decimal("0"))
        if rubric_possible != maximum:
            raise ValueError("max_score must equal total rubric possible_points")
        if rubric_awarded != proposed:
            raise ValueError("proposed_score must equal total rubric awarded_points")

        feedback = self.feedback.strip() if isinstance(self.feedback, str) else None
        if not feedback:
            raise ValueError("feedback must be non-empty text")
        confidence = _decimal(self.confidence, "confidence", minimum=Decimal("0"), maximum=Decimal("1"))
        reasons = _strings(self.uncertainty_reasons, "uncertainty_reasons", allow_empty=True)
        provenance = tuple(self.provenance)
        if not provenance or any(not isinstance(item, SourceProvenance) for item in provenance):
            raise ValueError("provenance must contain SourceProvenance entries")
        provenance = tuple(sorted(provenance, key=lambda item: (item.source_type, item.source_id, item.content_digest)))
        targets = _strings(self.target_platforms, "target_platforms", allow_empty=False)

        object.__setattr__(self, "rubric", rubric)
        object.__setattr__(self, "proposed_score", proposed)
        object.__setattr__(self, "max_score", maximum)
        object.__setattr__(self, "feedback", feedback)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "uncertainty_reasons", reasons)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "target_platforms", targets)

    @property
    def blocking_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.student.resolution != IdentityResolution.RESOLVED:
            reasons.append(f"student.{self.student.resolution.value}")
        if self.assignment.resolution != IdentityResolution.RESOLVED:
            reasons.append(f"assignment.{self.assignment.resolution.value}")
        if self.freshness != EvidenceFreshness.CURRENT:
            reasons.append(f"evidence.{self.freshness.value}")
        if self.approval_state != TeacherApprovalState.APPROVED:
            reasons.append(f"approval.{self.approval_state.value}")
        if self.uncertainty_reasons:
            reasons.append("decision.uncertain")
        return tuple(reasons)

    @property
    def eligible_for_authorization_review(self) -> bool:
        """True only when downstream authorization may evaluate this decision.

        This is not write authority. A later authorization contract must still grant
        permission for the exact target mutation.
        """

        return not self.blocking_reasons

    @property
    def decision_id(self) -> str:
        return f"grading-decision:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self._payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def to_record(self) -> dict[str, Any]:
        return {**self._payload(), "decision_id": self.decision_id, "write_authorized": False}

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "student": _identity_payload(self.student),
            "assignment": _identity_payload(self.assignment),
            "rubric": [_criterion_payload(item) for item in self.rubric],
            "proposed_score": _decimal_text(self.proposed_score),
            "max_score": _decimal_text(self.max_score),
            "feedback": self.feedback,
            "confidence": _decimal_text(self.confidence),
            "uncertainty_reasons": list(self.uncertainty_reasons),
            "approval_state": self.approval_state.value,
            "freshness": self.freshness.value,
            "provenance": [
                {
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "content_digest": item.content_digest,
                }
                for item in self.provenance
            ],
            "target_platforms": list(self.target_platforms),
        }


def _identity_payload(value: IdentityEvidence) -> dict[str, Any]:
    return {
        "resolution": value.resolution.value,
        "resolved_id": value.resolved_id,
        "evidence_refs": list(value.evidence_refs),
        "confidence": _decimal_text(value.confidence),
    }


def _criterion_payload(value: RubricCriterionEvidence) -> dict[str, Any]:
    return {
        "criterion_id": value.criterion_id,
        "description": value.description,
        "possible_points": _decimal_text(value.possible_points),
        "awarded_points": _decimal_text(value.awarded_points),
        "evidence_refs": list(value.evidence_refs),
    }


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()


def _strings(values: tuple[str, ...], name: str, *, allow_empty: bool) -> tuple[str, ...]:
    normalized = tuple(sorted({_text(value, name) for value in values}))
    if not normalized and not allow_empty:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _decimal(
    value: object,
    name: str,
    *,
    minimum: Decimal,
    maximum: Decimal | None = None,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be numeric") from None
    if not decimal_value.is_finite():
        raise ValueError(f"{name} must be finite")
    if decimal_value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and decimal_value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return decimal_value.normalize()


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return "0" if text == "-0" else text
