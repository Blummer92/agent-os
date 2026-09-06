"""Canonical typed-subject successor for approval records and projections.

This module is an additive #398/#407 extension.  It deliberately delegates all
approval lifecycle state, revision transitions, expiry, invalidation,
supersession, and current repository/proposal applicability to the existing
approval_records implementation.  The only new approval-semantic input is one
verified, finite instructional live-operation subject reference.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from instructional_workflow_contracts.common import ValidationStatus
from instructional_workflow_contracts.live_operation_subject import (
    CONTRACT_ID as INSTRUCTIONAL_LIVE_SUBJECT_SCHEMA_VERSION,
    validate_live_operation_subject,
)

from .approval_records import (
    ApprovalApplicabilityResult,
    ApprovalKind,
    ApprovalRecord,
    ApprovalState,
    build_approval_candidate,
    evaluate_approval_applicability,
    reconstruct_approval_record,
    record_approval_decision,
    serialize_approval_record,
)
from .approved_execution_projection import (
    APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
    ApprovedExecutionProjection,
    ApprovedExecutionProjectionResult,
    build_approved_execution_projection,
    serialize_approved_execution_projection,
)
from .issueplan_current_state import IssuePlanCurrentStateEvidence
from .planning_binding import PlanningBindingEvidence
from scripts.agent_os_execution_capabilities import RepositoryStateEvidence

TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION = "1.2"
TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION = "1.1"
INSTRUCTIONAL_LIVE_SUBJECT_KIND = "instructional-materials-live-operation"

_APPROVAL_PREFIX = "approval:"
_REVISION_PREFIX = "approval-revision:"
_PROJECTION_PREFIX = "approved-execution-projection:"


@dataclass(frozen=True, slots=True)
class TypedSubjectReference:
    subject_kind: str
    subject_schema_version: str
    subject_id: str

    def __post_init__(self) -> None:
        if self.subject_kind != INSTRUCTIONAL_LIVE_SUBJECT_KIND:
            raise ValueError("unsupported typed approval subject kind")
        if self.subject_schema_version != INSTRUCTIONAL_LIVE_SUBJECT_SCHEMA_VERSION:
            raise ValueError("unsupported typed approval subject schema version")
        if not isinstance(self.subject_id, str) or not self.subject_id.startswith(
            "instructional-live-operation-subject:"
        ):
            raise ValueError("typed approval subject_id is malformed")
        digest = self.subject_id.removeprefix(
            "instructional-live-operation-subject:"
        )
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("typed approval subject_id is malformed")


@dataclass(frozen=True, slots=True)
class TypedSubjectApprovalRecord:
    schema_version: str
    approval_id: str
    approval_revision: str
    lifecycle_record: ApprovalRecord
    subject: TypedSubjectReference
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION:
            raise ValueError("unsupported typed approval schema version")
        verified = reconstruct_approval_record(serialize_approval_record(self.lifecycle_record))
        object.__setattr__(self, "lifecycle_record", verified)
        if not isinstance(self.subject, TypedSubjectReference):
            raise TypeError("subject must be TypedSubjectReference")
        expected_id = _typed_approval_id(verified, self.subject)
        if self.approval_id and self.approval_id != expected_id:
            raise ValueError("approval_id does not match typed approval content")
        object.__setattr__(self, "approval_id", expected_id)
        expected_revision = _typed_approval_revision(verified, self.subject, expected_id)
        if self.approval_revision and self.approval_revision != expected_revision:
            raise ValueError("approval_revision does not match typed approval content")
        object.__setattr__(self, "approval_revision", expected_revision)

    @property
    def state(self) -> ApprovalState:
        return self.lifecycle_record.state

    @property
    def revision_number(self) -> int:
        return self.lifecycle_record.revision_number

    @property
    def approval_kind(self) -> ApprovalKind:
        return self.lifecycle_record.approval_kind


@dataclass(frozen=True, slots=True)
class TypedSubjectApprovalApplicabilityResult:
    status: str
    approval_id: str
    approval_revision: str
    subject: TypedSubjectReference
    canonical_result: ApprovalApplicabilityResult
    reason_codes: tuple[str, ...]
    details: tuple[str, ...]
    approval_applicable: bool
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.status not in {"applicable", "stale", "blocked", "invalid", "needs-decision"}:
            raise ValueError("unsupported typed approval applicability status")
        if self.approval_applicable != (self.status == "applicable"):
            raise ValueError("approval_applicable must match status")
        if not isinstance(self.canonical_result, ApprovalApplicabilityResult):
            raise TypeError("canonical_result must be ApprovalApplicabilityResult")


@dataclass(frozen=True, slots=True)
class TypedSubjectApprovedExecutionProjection:
    schema_version: str
    projection_id: str
    approval_id: str
    approval_revision: str
    approval_revision_number: int
    subject: TypedSubjectReference
    base_projection: ApprovedExecutionProjection
    projected_at: str
    complete: Literal[True] = field(default=True, init=False)
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION:
            raise ValueError("unsupported typed projection schema version")
        if not isinstance(self.base_projection, ApprovedExecutionProjection):
            raise TypeError("base_projection must be ApprovedExecutionProjection")
        if not isinstance(self.subject, TypedSubjectReference):
            raise TypeError("subject must be TypedSubjectReference")
        expected = _typed_projection_id(self)
        if self.projection_id and self.projection_id != expected:
            raise ValueError("projection_id does not match typed projection content")
        object.__setattr__(self, "projection_id", expected)


@dataclass(frozen=True, slots=True)
class TypedSubjectProjectionResult:
    status: str
    projection: TypedSubjectApprovedExecutionProjection | None
    reason_codes: tuple[str, ...]
    details: tuple[str, ...] = ()
    complete: bool = field(init=False)
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.status not in {"complete", "stale", "blocked", "invalid", "needs-decision"}:
            raise ValueError("unsupported typed projection result status")
        object.__setattr__(self, "complete", self.status == "complete")
        if self.complete != isinstance(self.projection, TypedSubjectApprovedExecutionProjection):
            raise ValueError("projection presence must match complete status")


def validate_typed_subject_reference(subject: object) -> TypedSubjectReference:
    """Validate the exact #1975 subject object and return only its finite reference."""
    if not isinstance(subject, Mapping):
        raise TypeError("typed approval subject must be the complete subject object")
    result = validate_live_operation_subject(dict(subject))
    if result.status is not ValidationStatus.VALID or result.record is None:
        detail = ",".join((*result.reason_codes, *result.details))
        raise ValueError(f"typed approval subject is invalid: {detail}")
    return TypedSubjectReference(
        subject_kind=INSTRUCTIONAL_LIVE_SUBJECT_KIND,
        subject_schema_version=result.record.contract_version,
        subject_id=result.record.record_id,
    )


def build_typed_subject_approval_candidate(
    proposal: object,
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence,
    repository_state_evidence: RepositoryStateEvidence | Mapping[str, Any],
    *,
    subject: object,
    approval_kind: ApprovalKind | str,
    authorizer_id: str,
    decision_id: str,
    decision_at: str,
    expires_at: str | None = None,
    supersedes: TypedSubjectApprovalRecord | None = None,
    planning_binding: PlanningBindingEvidence | None = None,
) -> TypedSubjectApprovalRecord:
    subject_ref = validate_typed_subject_reference(subject)
    lifecycle_supersedes = None if supersedes is None else supersedes.lifecycle_record
    lifecycle = build_approval_candidate(
        proposal,
        issueplan_current_state_evidence,
        repository_state_evidence,
        approval_kind=approval_kind,
        authorizer_id=authorizer_id,
        decision_id=decision_id,
        decision_at=decision_at,
        expires_at=expires_at,
        supersedes=lifecycle_supersedes,
        planning_binding=planning_binding,
    )
    return TypedSubjectApprovalRecord(
        schema_version=TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION,
        approval_id="",
        approval_revision="",
        lifecycle_record=lifecycle,
        subject=subject_ref,
    )


def record_typed_subject_approval_decision(
    current: TypedSubjectApprovalRecord,
    *,
    state: ApprovalState | str,
    decision_id: str,
    authorizer_id: str,
    decision_at: str,
    reason_codes: Iterable[str] = (),
    details: Iterable[str] = (),
) -> TypedSubjectApprovalRecord:
    if not isinstance(current, TypedSubjectApprovalRecord):
        raise TypeError("current must be TypedSubjectApprovalRecord")
    lifecycle = record_approval_decision(
        current.lifecycle_record,
        state=state,
        decision_id=decision_id,
        authorizer_id=authorizer_id,
        decision_at=decision_at,
        reason_codes=reason_codes,
        details=details,
    )
    return TypedSubjectApprovalRecord(
        schema_version=TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION,
        approval_id=current.approval_id,
        approval_revision="",
        lifecycle_record=lifecycle,
        subject=current.subject,
    )


def evaluate_typed_subject_approval_applicability(
    approval_record: TypedSubjectApprovalRecord,
    current_proposal: object,
    current_issueplan_evidence: IssuePlanCurrentStateEvidence,
    current_repository_state_evidence: RepositoryStateEvidence | Mapping[str, Any],
    *,
    current_subject: object,
    evaluated_at: str,
    invalidation_events: Iterable[str] = (),
    planning_binding: PlanningBindingEvidence | None = None,
) -> TypedSubjectApprovalApplicabilityResult:
    if not isinstance(approval_record, TypedSubjectApprovalRecord):
        raise TypeError("approval_record must be TypedSubjectApprovalRecord")
    canonical = evaluate_approval_applicability(
        approval_record.lifecycle_record,
        current_proposal,
        current_issueplan_evidence,
        current_repository_state_evidence,
        evaluated_at=evaluated_at,
        invalidation_events=invalidation_events,
        planning_binding=planning_binding,
    )
    if canonical.status != "applicable":
        return _typed_result(approval_record, canonical.status, canonical, canonical.reason_codes, canonical.details)
    try:
        current_ref = validate_typed_subject_reference(current_subject)
    except (TypeError, ValueError) as exc:
        return _typed_result(
            approval_record,
            "invalid",
            canonical,
            ("projection.incomplete",),
            (f"typed-subject:{exc}",),
        )
    if current_ref != approval_record.subject:
        return _typed_result(
            approval_record,
            "stale",
            canonical,
            ("candidate.changed",),
            ("typed-subject:reference-mismatch",),
        )
    return _typed_result(approval_record, "applicable", canonical, (), ())


def build_typed_subject_approved_execution_projection(
    proposal: object,
    approval_record: TypedSubjectApprovalRecord,
    applicability: TypedSubjectApprovalApplicabilityResult,
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence,
    repository_state_evidence: RepositoryStateEvidence,
    *,
    projected_at: str,
    planning_binding: PlanningBindingEvidence | None = None,
) -> TypedSubjectProjectionResult:
    if not isinstance(approval_record, TypedSubjectApprovalRecord):
        raise TypeError("approval_record must be TypedSubjectApprovalRecord")
    if not isinstance(applicability, TypedSubjectApprovalApplicabilityResult):
        raise TypeError("applicability must be TypedSubjectApprovalApplicabilityResult")
    if applicability.approval_id != approval_record.approval_id or applicability.approval_revision != approval_record.approval_revision:
        return TypedSubjectProjectionResult("invalid", None, ("projection.incomplete",), ("typed-applicability:identity-mismatch",))
    if applicability.status != "applicable":
        reasons = applicability.reason_codes or ("projection.incomplete",)
        return TypedSubjectProjectionResult(applicability.status, None, reasons, applicability.details)
    base_result: ApprovedExecutionProjectionResult = build_approved_execution_projection(
        proposal,
        approval_record.lifecycle_record,
        applicability.canonical_result,
        issueplan_current_state_evidence,
        repository_state_evidence,
        projected_at=projected_at,
        planning_binding=planning_binding,
        schema_version=APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
    )
    if not base_result.complete or base_result.projection is None:
        return TypedSubjectProjectionResult(base_result.status, None, base_result.reason_codes, base_result.details)
    projection = TypedSubjectApprovedExecutionProjection(
        schema_version=TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION,
        projection_id="",
        approval_id=approval_record.approval_id,
        approval_revision=approval_record.approval_revision,
        approval_revision_number=approval_record.revision_number,
        subject=approval_record.subject,
        base_projection=base_result.projection,
        projected_at=projected_at,
    )
    return TypedSubjectProjectionResult("complete", projection, (), ())


def serialize_typed_subject_approval_record(record: TypedSubjectApprovalRecord) -> bytes:
    if not isinstance(record, TypedSubjectApprovalRecord):
        raise TypeError("record must be TypedSubjectApprovalRecord")
    payload = {
        "schema_version": record.schema_version,
        "approval_id": record.approval_id,
        "approval_revision": record.approval_revision,
        "lifecycle_record": json.loads(serialize_approval_record(record.lifecycle_record)),
        "subject": _subject_payload(record.subject),
        "execution_authorized": False,
        "side_effects_performed": False,
    }
    return _canonical_bytes(payload)


def serialize_typed_subject_projection(projection: TypedSubjectApprovedExecutionProjection) -> bytes:
    if not isinstance(projection, TypedSubjectApprovedExecutionProjection):
        raise TypeError("projection must be TypedSubjectApprovedExecutionProjection")
    payload = {
        "schema_version": projection.schema_version,
        "projection_id": projection.projection_id,
        "approval_id": projection.approval_id,
        "approval_revision": projection.approval_revision,
        "approval_revision_number": projection.approval_revision_number,
        "subject": _subject_payload(projection.subject),
        "base_projection": json.loads(serialize_approved_execution_projection(projection.base_projection)),
        "projected_at": projection.projected_at,
        "complete": True,
        "authoritative": False,
        "execution_authorized": False,
        "side_effects_performed": False,
    }
    return _canonical_bytes(payload) + b"\n"


def _typed_result(
    record: TypedSubjectApprovalRecord,
    status: str,
    canonical: ApprovalApplicabilityResult,
    reasons: Iterable[str],
    details: Iterable[str],
) -> TypedSubjectApprovalApplicabilityResult:
    return TypedSubjectApprovalApplicabilityResult(
        status=status,
        approval_id=record.approval_id,
        approval_revision=record.approval_revision,
        subject=record.subject,
        canonical_result=canonical,
        reason_codes=tuple(sorted(set(reasons))),
        details=tuple(str(item) for item in details),
        approval_applicable=status == "applicable",
    )


def _subject_payload(subject: TypedSubjectReference) -> dict[str, str]:
    return {
        "subject_kind": subject.subject_kind,
        "subject_schema_version": subject.subject_schema_version,
        "subject_id": subject.subject_id,
    }


def _typed_approval_id(lifecycle: ApprovalRecord, subject: TypedSubjectReference) -> str:
    return _APPROVAL_PREFIX + _digest({
        "schema_version": TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION,
        "lifecycle_approval_id": lifecycle.approval_id,
        "subject": _subject_payload(subject),
    })


def _typed_approval_revision(lifecycle: ApprovalRecord, subject: TypedSubjectReference, approval_id: str) -> str:
    return _REVISION_PREFIX + _digest({
        "schema_version": TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION,
        "approval_id": approval_id,
        "lifecycle_approval_revision": lifecycle.approval_revision,
        "revision_number": lifecycle.revision_number,
        "subject": _subject_payload(subject),
    })


def _typed_projection_id(projection: TypedSubjectApprovedExecutionProjection) -> str:
    return _PROJECTION_PREFIX + _digest({
        "schema_version": projection.schema_version,
        "approval_id": projection.approval_id,
        "approval_revision": projection.approval_revision,
        "approval_revision_number": projection.approval_revision_number,
        "subject": _subject_payload(projection.subject),
        "base_projection_id": projection.base_projection.projection_id,
        "projected_at": projection.projected_at,
    })


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


__all__ = [
    "TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION",
    "TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION",
    "INSTRUCTIONAL_LIVE_SUBJECT_KIND",
    "TypedSubjectReference",
    "TypedSubjectApprovalRecord",
    "TypedSubjectApprovalApplicabilityResult",
    "TypedSubjectApprovedExecutionProjection",
    "TypedSubjectProjectionResult",
    "validate_typed_subject_reference",
    "build_typed_subject_approval_candidate",
    "record_typed_subject_approval_decision",
    "evaluate_typed_subject_approval_applicability",
    "build_typed_subject_approved_execution_projection",
    "serialize_typed_subject_approval_record",
    "serialize_typed_subject_projection",
]
