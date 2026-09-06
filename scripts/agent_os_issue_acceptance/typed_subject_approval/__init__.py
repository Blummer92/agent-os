"""Additive #398/#407 typed-subject approval successor; pure and non-authorizing."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from instructional_workflow_contracts.common import ValidationStatus
from instructional_workflow_contracts.live_operation_subject import (
    CONTRACT_ID as INSTRUCTIONAL_LIVE_SUBJECT_SCHEMA_VERSION,
    validate_live_operation_subject,
)
from scripts.agent_os_execution_capabilities import RepositoryStateEvidence

from ..approval_records import (
    ApprovalApplicabilityResult, ApprovalKind, ApprovalRecord, ApprovalState,
    build_approval_candidate, evaluate_approval_applicability,
    reconstruct_approval_record, record_approval_decision, serialize_approval_record,
)
from ..approved_execution_projection import (
    APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION, ApprovedExecutionProjection,
    build_approved_execution_projection, serialize_approved_execution_projection,
)
from ..issueplan_current_state import IssuePlanCurrentStateEvidence
from ..planning_binding import PlanningBindingEvidence

TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION = "1.2"
TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION = "1.1"
INSTRUCTIONAL_LIVE_SUBJECT_KIND = "instructional-materials-live-operation"


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
        prefix = "instructional-live-operation-subject:"
        if not isinstance(self.subject_id, str) or not self.subject_id.startswith(prefix):
            raise ValueError("typed approval subject_id is malformed")
        digest = self.subject_id[len(prefix):]
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
        lifecycle = reconstruct_approval_record(serialize_approval_record(self.lifecycle_record))
        object.__setattr__(self, "lifecycle_record", lifecycle)
        if not isinstance(self.subject, TypedSubjectReference):
            raise TypeError("subject must be TypedSubjectReference")
        approval_id = "approval:" + _digest({"schema_version": self.schema_version, "lifecycle_approval_id": lifecycle.approval_id, "subject": _subject_payload(self.subject)})
        if self.approval_id and self.approval_id != approval_id:
            raise ValueError("approval_id does not match typed approval content")
        object.__setattr__(self, "approval_id", approval_id)
        revision = "approval-revision:" + _digest({"schema_version": self.schema_version, "approval_id": approval_id, "lifecycle_approval_revision": lifecycle.approval_revision, "revision_number": lifecycle.revision_number, "subject": _subject_payload(self.subject)})
        if self.approval_revision and self.approval_revision != revision:
            raise ValueError("approval_revision does not match typed approval content")
        object.__setattr__(self, "approval_revision", revision)

    @property
    def state(self) -> ApprovalState: return self.lifecycle_record.state
    @property
    def revision_number(self) -> int: return self.lifecycle_record.revision_number


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
        identity = "approved-execution-projection:" + _digest({"schema_version": self.schema_version, "approval_id": self.approval_id, "approval_revision": self.approval_revision, "approval_revision_number": self.approval_revision_number, "subject": _subject_payload(self.subject), "base_projection_id": self.base_projection.projection_id, "projected_at": self.projected_at})
        if self.projection_id and self.projection_id != identity:
            raise ValueError("projection_id does not match typed projection content")
        object.__setattr__(self, "projection_id", identity)


def validate_typed_subject_reference(subject: object) -> TypedSubjectReference:
    if not isinstance(subject, Mapping):
        raise TypeError("typed approval subject must be the complete subject object")
    result = validate_live_operation_subject(dict(subject))
    if result.status is not ValidationStatus.VALID or result.record is None:
        raise ValueError("typed approval subject is invalid: " + ",".join((*result.reason_codes, *result.details)))
    return TypedSubjectReference(INSTRUCTIONAL_LIVE_SUBJECT_KIND, result.record.contract_version, result.record.record_id)


def build_typed_subject_approval_candidate(proposal: object, issueplan_current_state_evidence: IssuePlanCurrentStateEvidence, repository_state_evidence: RepositoryStateEvidence | Mapping[str, Any], *, subject: object, approval_kind: ApprovalKind | str, authorizer_id: str, decision_id: str, decision_at: str, expires_at: str | None = None, supersedes: TypedSubjectApprovalRecord | None = None, planning_binding: PlanningBindingEvidence | None = None) -> TypedSubjectApprovalRecord:
    subject_ref = validate_typed_subject_reference(subject)
    lifecycle = build_approval_candidate(proposal, issueplan_current_state_evidence, repository_state_evidence, approval_kind=approval_kind, authorizer_id=authorizer_id, decision_id=decision_id, decision_at=decision_at, expires_at=expires_at, supersedes=None if supersedes is None else supersedes.lifecycle_record, planning_binding=planning_binding)
    return TypedSubjectApprovalRecord(TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION, "", "", lifecycle, subject_ref)


def record_typed_subject_approval_decision(current: TypedSubjectApprovalRecord, *, state: ApprovalState | str, decision_id: str, authorizer_id: str, decision_at: str, reason_codes: Iterable[str] = (), details: Iterable[str] = ()) -> TypedSubjectApprovalRecord:
    lifecycle = record_approval_decision(current.lifecycle_record, state=state, decision_id=decision_id, authorizer_id=authorizer_id, decision_at=decision_at, reason_codes=reason_codes, details=details)
    return TypedSubjectApprovalRecord(TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION, current.approval_id, "", lifecycle, current.subject)


def evaluate_typed_subject_approval_applicability(approval_record: TypedSubjectApprovalRecord, current_proposal: object, current_issueplan_evidence: IssuePlanCurrentStateEvidence, current_repository_state_evidence: RepositoryStateEvidence | Mapping[str, Any], *, current_subject: object, evaluated_at: str, invalidation_events: Iterable[str] = (), planning_binding: PlanningBindingEvidence | None = None) -> TypedSubjectApprovalApplicabilityResult:
    canonical = evaluate_approval_applicability(approval_record.lifecycle_record, current_proposal, current_issueplan_evidence, current_repository_state_evidence, evaluated_at=evaluated_at, invalidation_events=invalidation_events, planning_binding=planning_binding)
    if canonical.status != "applicable": return _result(approval_record, canonical.status, canonical, canonical.reason_codes, canonical.details)
    try: current_ref = validate_typed_subject_reference(current_subject)
    except (TypeError, ValueError) as exc: return _result(approval_record, "invalid", canonical, ("projection.incomplete",), (f"typed-subject:{exc}",))
    if current_ref != approval_record.subject: return _result(approval_record, "stale", canonical, ("candidate.changed",), ("typed-subject:reference-mismatch",))
    return _result(approval_record, "applicable", canonical, (), ())


def build_typed_subject_approved_execution_projection(proposal: object, approval_record: TypedSubjectApprovalRecord, applicability: TypedSubjectApprovalApplicabilityResult, issueplan_current_state_evidence: IssuePlanCurrentStateEvidence, repository_state_evidence: RepositoryStateEvidence, *, projected_at: str, planning_binding: PlanningBindingEvidence | None = None):
    if applicability.approval_id != approval_record.approval_id or applicability.approval_revision != approval_record.approval_revision or applicability.status != "applicable":
        return None
    base = build_approved_execution_projection(proposal, approval_record.lifecycle_record, applicability.canonical_result, issueplan_current_state_evidence, repository_state_evidence, projected_at=projected_at, planning_binding=planning_binding, schema_version=APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION)
    if not base.complete or base.projection is None: return None
    return TypedSubjectApprovedExecutionProjection(TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION, "", approval_record.approval_id, approval_record.approval_revision, approval_record.revision_number, approval_record.subject, base.projection, projected_at)


def serialize_typed_subject_approval_record(record: TypedSubjectApprovalRecord) -> bytes:
    return _canonical_bytes({"schema_version": record.schema_version, "approval_id": record.approval_id, "approval_revision": record.approval_revision, "lifecycle_record": json.loads(serialize_approval_record(record.lifecycle_record)), "subject": _subject_payload(record.subject), "execution_authorized": False, "side_effects_performed": False})


def serialize_typed_subject_projection(projection: TypedSubjectApprovedExecutionProjection) -> bytes:
    return _canonical_bytes({"schema_version": projection.schema_version, "projection_id": projection.projection_id, "approval_id": projection.approval_id, "approval_revision": projection.approval_revision, "approval_revision_number": projection.approval_revision_number, "subject": _subject_payload(projection.subject), "base_projection": json.loads(serialize_approved_execution_projection(projection.base_projection)), "projected_at": projection.projected_at, "complete": True, "authoritative": False, "execution_authorized": False, "side_effects_performed": False}) + b"\n"


def _result(record, status, canonical, reasons, details):
    return TypedSubjectApprovalApplicabilityResult(status, record.approval_id, record.approval_revision, record.subject, canonical, tuple(sorted(set(reasons))), tuple(str(x) for x in details), status == "applicable")

def _subject_payload(subject): return {"subject_kind": subject.subject_kind, "subject_schema_version": subject.subject_schema_version, "subject_id": subject.subject_id}
def _canonical_bytes(value): return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
def _digest(value): return hashlib.sha256(_canonical_bytes(value)).hexdigest()
