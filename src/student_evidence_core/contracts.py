"""Pure-local Student Evidence Core contracts.

These contracts intentionally perform no I/O. Provider-native artifacts remain authoritative;
this module records bounded identities, provenance, proposals, decisions, and projections only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
from typing import Any

MAX_TEXT = 512
MAX_ITEMS = 64


class ContractError(ValueError):
    """Raised when Student Evidence Core input fails closed."""


class EvidenceTrust(str, Enum):
    UNVERIFIED = "unverified"
    PROVIDER_VERIFIED = "provider-verified"
    HUMAN_VERIFIED = "human-verified"
    CONTRADICTORY = "contradictory"


class ReviewState(str, Enum):
    NOT_REVIEWED = "not-reviewed"
    NEEDS_REVIEW = "needs-review"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class ProposalState(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


def _text(value: str, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise ContractError(f"{field}:expected-str")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise ContractError(f"{field}:required")
    if len(normalized.encode("utf-8")) > MAX_TEXT:
        raise ContractError(f"{field}:too-long")
    return normalized


def _optional_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _tuple_text(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) > MAX_ITEMS:
        raise ContractError(f"{field}:invalid-collection")
    normalized = tuple(_text(item, field) for item in values)
    if len(set(normalized)) != len(normalized):
        raise ContractError(f"{field}:duplicate")
    return normalized


def canonical_payload(value: Any) -> str:
    """Return deterministic JSON for supported immutable contract values."""
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_payload(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StudentIdentity:
    provider: str
    native_student_id: str
    display_label: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _text(self.provider, "provider"))
        object.__setattr__(self, "native_student_id", _text(self.native_student_id, "native_student_id"))
        object.__setattr__(self, "display_label", _optional_text(self.display_label, "display_label"))


@dataclass(frozen=True)
class EvidenceLocator:
    provider: str
    native_artifact_id: str
    native_revision: str
    stable_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _text(self.provider, "provider"))
        object.__setattr__(self, "native_artifact_id", _text(self.native_artifact_id, "native_artifact_id"))
        object.__setattr__(self, "native_revision", _text(self.native_revision, "native_revision"))
        object.__setattr__(self, "stable_reference", _text(self.stable_reference, "stable_reference"))


@dataclass(frozen=True)
class EvidenceProvenance:
    locator: EvidenceLocator
    extraction_recipe: str
    extraction_version: str
    confidence: float | None
    trust: EvidenceTrust
    review_state: ReviewState

    def __post_init__(self) -> None:
        if not isinstance(self.locator, EvidenceLocator):
            raise ContractError("locator:invalid")
        object.__setattr__(self, "extraction_recipe", _text(self.extraction_recipe, "extraction_recipe"))
        object.__setattr__(self, "extraction_version", _text(self.extraction_version, "extraction_version"))
        if self.confidence is not None:
            if type(self.confidence) not in (int, float) or isinstance(self.confidence, bool):
                raise ContractError("confidence:invalid-type")
            confidence = float(self.confidence)
            if confidence < 0.0 or confidence > 1.0:
                raise ContractError("confidence:out-of-range")
            object.__setattr__(self, "confidence", confidence)
        if not isinstance(self.trust, EvidenceTrust):
            raise ContractError("trust:invalid")
        if not isinstance(self.review_state, ReviewState):
            raise ContractError("review_state:invalid")


@dataclass(frozen=True)
class EvidenceAsset:
    student: StudentIdentity
    locator: EvidenceLocator
    provenance: EvidenceProvenance
    media_type: str
    content_fingerprint: str
    metadata_fingerprint: str
    derived_text: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.student, StudentIdentity):
            raise ContractError("student:invalid")
        if not isinstance(self.locator, EvidenceLocator) or self.provenance.locator != self.locator:
            raise ContractError("locator:provenance-mismatch")
        object.__setattr__(self, "media_type", _text(self.media_type, "media_type"))
        object.__setattr__(self, "content_fingerprint", _text(self.content_fingerprint, "content_fingerprint"))
        object.__setattr__(self, "metadata_fingerprint", _text(self.metadata_fingerprint, "metadata_fingerprint"))
        object.__setattr__(self, "derived_text", _optional_text(self.derived_text, "derived_text"))


@dataclass(frozen=True)
class SubmissionRecord:
    submission_id: str
    student: StudentIdentity
    evidence: tuple[EvidenceAsset, ...]
    submitted_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "submission_id", _text(self.submission_id, "submission_id"))
        if not isinstance(self.student, StudentIdentity):
            raise ContractError("student:invalid")
        if type(self.evidence) is not tuple or not self.evidence or len(self.evidence) > MAX_ITEMS:
            raise ContractError("evidence:invalid-collection")
        if any(not isinstance(item, EvidenceAsset) or item.student != self.student for item in self.evidence):
            raise ContractError("evidence:student-mismatch")
        object.__setattr__(self, "submitted_at", _text(self.submitted_at, "submitted_at"))


@dataclass(frozen=True)
class ResponseRecord:
    response_id: str
    submission_id: str
    source_revision: str
    response_text: str
    provenance: EvidenceProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "response_id", _text(self.response_id, "response_id"))
        object.__setattr__(self, "submission_id", _text(self.submission_id, "submission_id"))
        object.__setattr__(self, "source_revision", _text(self.source_revision, "source_revision"))
        object.__setattr__(self, "response_text", _text(self.response_text, "response_text"))
        if not isinstance(self.provenance, EvidenceProvenance):
            raise ContractError("provenance:invalid")


@dataclass(frozen=True)
class OrganizationProposal:
    proposal_id: str
    evidence_ids: tuple[str, ...]
    suggested_destination: str
    state: ProposalState = ProposalState.PROPOSED
    teacher_correction: str | None = None
    execution_result: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_id", _text(self.proposal_id, "proposal_id"))
        object.__setattr__(self, "evidence_ids", _tuple_text(self.evidence_ids, "evidence_ids"))
        if not self.evidence_ids:
            raise ContractError("evidence_ids:required")
        object.__setattr__(self, "suggested_destination", _text(self.suggested_destination, "suggested_destination"))
        if not isinstance(self.state, ProposalState):
            raise ContractError("state:invalid")
        object.__setattr__(self, "teacher_correction", _optional_text(self.teacher_correction, "teacher_correction"))
        object.__setattr__(self, "execution_result", _optional_text(self.execution_result, "execution_result"))
        if self.state is ProposalState.CORRECTED and self.teacher_correction is None:
            raise ContractError("teacher_correction:required")
        if self.state in (ProposalState.EXECUTED, ProposalState.FAILED) and self.execution_result is None:
            raise ContractError("execution_result:required")


@dataclass(frozen=True)
class TeacherDecision:
    proposal_id: str
    decision: ProposalState
    decided_by: str
    decision_revision: str
    note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_id", _text(self.proposal_id, "proposal_id"))
        if self.decision not in (ProposalState.ACCEPTED, ProposalState.CORRECTED, ProposalState.REJECTED):
            raise ContractError("decision:invalid")
        object.__setattr__(self, "decided_by", _text(self.decided_by, "decided_by"))
        object.__setattr__(self, "decision_revision", _text(self.decision_revision, "decision_revision"))
        object.__setattr__(self, "note", _optional_text(self.note, "note"))


@dataclass(frozen=True)
class ProjectionRecord:
    projection_id: str
    source_ids: tuple[str, ...]
    payload_fingerprint: str
    review_state: ReviewState
    grading_authority: bool = False
    curriculum_authority: bool = False
    movement_authority: bool = False
    publication_authority: bool = False
    external_write_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "projection_id", _text(self.projection_id, "projection_id"))
        object.__setattr__(self, "source_ids", _tuple_text(self.source_ids, "source_ids"))
        object.__setattr__(self, "payload_fingerprint", _text(self.payload_fingerprint, "payload_fingerprint"))
        if not isinstance(self.review_state, ReviewState):
            raise ContractError("review_state:invalid")
        authority = (
            self.grading_authority,
            self.curriculum_authority,
            self.movement_authority,
            self.publication_authority,
            self.external_write_authority,
        )
        if any(type(value) is not bool for value in authority) or any(authority):
            raise ContractError("authority:must-be-false")
