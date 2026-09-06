from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from instructional_workflow_contracts.live_operation_subject import (
    CONTRACT_ID as LIVE_OPERATION_SUBJECT_SCHEMA_VERSION,
    validate_live_operation_subject,
)
from scripts.agent_os_execution_capabilities import RepositoryStateEvidence

from .approval_records import (
    ApprovalApplicabilityResult,
    ApprovalKind,
    ApprovalRecord,
    ApprovalState,
    build_approval_candidate,
    evaluate_approval_applicability,
    record_approval_decision,
)
from .approved_execution_projection import (
    ApprovedExecutionProjection,
    ApprovedExecutionProjectionResult,
    build_approved_execution_projection,
    serialize_approved_execution_projection,
)
from .issueplan_current_state import IssuePlanCurrentStateEvidence
from .planning_binding import PlanningBindingEvidence

TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION = "1.2"
TYPED_SUBJECT_REFERENCE_SCHEMA_VERSION = "1.0"
TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION = "1.1"
INSTRUCTIONAL_MATERIALS_LIVE_OPERATION_SUBJECT_KIND = (
    "instructional-materials-live-operation"
)

_APPROVAL_ID_RE = re.compile(r"^approval:[0-9a-f]{64}$")
_REVISION_ID_RE = re.compile(r"^approval-revision:[0-9a-f]{64}$")
_PROJECTION_ID_RE = re.compile(r"^approved-execution-projection:[0-9a-f]{64}$")
_SUBJECT_ID_RE = re.compile(r"^instructional-live-operation-subject:[0-9a-f]{64}$")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(prefix: str, value: object) -> str:
    return prefix + hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class TypedSubjectReference:
    schema_version: str
    subject_kind: str
    subject_schema_version: str
    subject_id: str

    def __post_init__(self) -> None:
        if self.schema_version != TYPED_SUBJECT_REFERENCE_SCHEMA_VERSION:
            raise ValueError("unsupported typed-subject reference schema version")
        if self.subject_kind != INSTRUCTIONAL_MATERIALS_LIVE_OPERATION_SUBJECT_KIND:
            raise ValueError("unsupported typed-subject kind")
        if self.subject_schema_version != LIVE_OPERATION_SUBJECT_SCHEMA_VERSION:
            raise ValueError("unsupported typed-subject schema version")
        if not _SUBJECT_ID_RE.fullmatch(self.subject_id):
            raise ValueError("typed subject_id is malformed")

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "subject_kind": self.subject_kind,
            "subject_schema_version": self.subject_schema_version,
            "subject_id": self.subject_id,
        }


def verified_typed_subject_reference(subject: object) -> TypedSubjectReference:
    result = validate_live_operation_subject(subject)
    if result.record is None or result.status.value != "valid":
        reasons = ",".join(result.reason_codes) or "invalid"
        raise ValueError(f"typed subject must be an exact validated subject: {reasons}")
    return TypedSubjectReference(
        schema_version=TYPED_SUBJECT_REFERENCE_SCHEMA_VERSION,
        subject_kind=INSTRUCTIONAL_MATERIALS_LIVE_OPERATION_SUBJECT_KIND,
        subject_schema_version=result.record.contract_version,
        subject_id=result.record.record_id,
    )


@dataclass(frozen=True, slots=True)
class TypedSubjectApprovalRecord:
    """Additive 1.2 envelope over the canonical #398 lifecycle record.

    Lifecycle state, authorizer, decision, expiry, supersession and repository
    applicability remain owned by ApprovalRecord. This envelope adds only the
    verified typed-subject binding and derives its public identities from the
    canonical lifecycle identity plus that binding.
    """

    schema_version: str
    approval_id: str
    approval_revision: str
    lifecycle_record: ApprovalRecord
    subject: TypedSubjectReference
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION:
            raise ValueError("unsupported typed-subject approval schema version")
        if not isinstance(self.lifecycle_record, ApprovalRecord):
            raise TypeError("lifecycle_record must be ApprovalRecord")
        if not isinstance(self.subject, TypedSubjectReference):
            raise TypeError("subject must be TypedSubjectReference")
        expected_id = _digest(
            "approval:",
            {
                "schema_version": self.schema_version,
                "lifecycle_approval_id": self.lifecycle_record.approval_id,
                "subject": self.subject.to_dict(),
            },
        )
        if self.approval_id and self.approval_id != expected_id:
            raise ValueError("approval_id does not match typed approval content")
        object.__setattr__(self, "approval_id", expected_id)
        expected_revision = _digest(
            "approval-revision:",
            {
                "schema_version": self.schema_version,
                "approval_id": expected_id,
                "lifecycle_revision": self.lifecycle_record.approval_revision,
                "subject": self.subject.to_dict(),
            },
        )
        if self.approval_revision and self.approval_revision != expected_revision:
            raise ValueError("approval_revision does not match typed approval content")
        object.__setattr__(self, "approval_revision", expected_revision)

    @property
    def state(self) -> ApprovalState:
        return self.lifecycle_record.state

    @property
    def approval_kind(self) -> ApprovalKind:
        return self.lifecycle_record.approval_kind


@dataclass(frozen=True, slots=True)
class TypedSubjectApprovalApplicabilityResult:
    status: str
    approval_id: str | None
    approval_revision: str | None
    subject: TypedSubjectReference | None
    base_applicability: ApprovalApplicabilityResult | None
    reason_codes: tuple[str, ...]
    changed_bindings: tuple[str, ...]
    approval_applicable: bool
    details: tuple[str, ...] = ()
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.status not in {"applicable", "stale", "blocked", "invalid", "needs-decision"}:
            raise ValueError("unsupported typed approval applicability status")
        if self.approval_applicable != (self.status == "applicable"):
            raise ValueError("approval_applicable must match applicable status")


def build_typed_subject_approval_candidate(
    proposal: object,
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence,
    repository_state_evidence: RepositoryStateEvidence | Mapping[str, Any],
    subject: object,
    *,
    approval_kind: ApprovalKind | str,
    authorizer_id: str,
    decision_id: str,
    decision_at: str,
    expires_at: str | None = None,
    supersedes: TypedSubjectApprovalRecord | None = None,
    planning_binding: PlanningBindingEvidence | None = None,
) -> TypedSubjectApprovalRecord:
    subject_ref = verified_typed_subject_reference(subject)
    base_supersedes = None if supersedes is None else supersedes.lifecycle_record
    base = build_approval_candidate(
        proposal,
        issueplan_current_state_evidence,
        repository_state_evidence,
        approval_kind=approval_kind,
        authorizer_id=authorizer_id,
        decision_id=decision_id,
        decision_at=decision_at,
        expires_at=expires_at,
        supersedes=base_supersedes,
        planning_binding=planning_binding,
    )
    return TypedSubjectApprovalRecord(
        schema_version=TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION,
        approval_id="",
        approval_revision="",
        lifecycle_record=base,
        subject=subject_ref,
    )


def record_typed_subject_approval_decision(
    current: TypedSubjectApprovalRecord,
    *,
    state: ApprovalState | str,
    decision_id: str,
    authorizer_id: str,
    decision_at: str,
    reason_codes: tuple[str, ...] = (),
    details: tuple[str, ...] = (),
) -> TypedSubjectApprovalRecord:
    if not isinstance(current, TypedSubjectApprovalRecord):
        raise TypeError("current must be TypedSubjectApprovalRecord")
    base = record_approval_decision(
        current.lifecycle_record,
        state=state,
        decision_id=decision_id,
        authorizer_id=authorizer_id,
        decision_at=decision_at,
        reason_codes=reason_codes,
        details=details,
    )
    return TypedSubjectApprovalRecord(
        schema_version=current.schema_version,
        approval_id="",
        approval_revision="",
        lifecycle_record=base,
        subject=current.subject,
    )


def evaluate_typed_subject_approval_applicability(
    approval_record: TypedSubjectApprovalRecord | None,
    current_subject: object,
    current_proposal: object,
    current_issueplan_evidence: IssuePlanCurrentStateEvidence,
    current_repository_state_evidence: RepositoryStateEvidence | Mapping[str, Any],
    *,
    evaluated_at: str,
    planning_binding: PlanningBindingEvidence | None = None,
) -> TypedSubjectApprovalApplicabilityResult:
    if approval_record is None:
        return TypedSubjectApprovalApplicabilityResult(
            "needs-decision", None, None, None, None,
            ("projection.lookup-failed",), (), False, ("approval-record:missing",)
        )
    if not isinstance(approval_record, TypedSubjectApprovalRecord):
        return TypedSubjectApprovalApplicabilityResult(
            "invalid", None, None, None, None,
            ("version.unsupported",), (), False, ("typed-approval:invalid-type",)
        )
    try:
        current_ref = verified_typed_subject_reference(current_subject)
    except (TypeError, ValueError) as exc:
        return TypedSubjectApprovalApplicabilityResult(
            "invalid", approval_record.approval_id, approval_record.approval_revision,
            None, None, ("version.unsupported",), ("typed-subject",), False, (str(exc),)
        )
    base = evaluate_approval_applicability(
        approval_record.lifecycle_record,
        current_proposal,
        current_issueplan_evidence,
        current_repository_state_evidence,
        evaluated_at=evaluated_at,
        planning_binding=planning_binding,
    )
    if base.status != "applicable":
        return TypedSubjectApprovalApplicabilityResult(
            base.status,
            approval_record.approval_id,
            approval_record.approval_revision,
            current_ref,
            base,
            base.reason_codes,
            base.changed_bindings,
            False,
            base.details,
        )
    if current_ref != approval_record.subject:
        return TypedSubjectApprovalApplicabilityResult(
            "stale",
            approval_record.approval_id,
            approval_record.approval_revision,
            current_ref,
            base,
            ("candidate.changed",),
            ("typed-subject",),
            False,
            ("typed subject reference changed",),
        )
    return TypedSubjectApprovalApplicabilityResult(
        "applicable",
        approval_record.approval_id,
        approval_record.approval_revision,
        current_ref,
        base,
        (),
        (),
        True,
        (),
    )


@dataclass(frozen=True, slots=True)
class TypedSubjectApprovedExecutionProjection:
    schema_version: str
    projection_id: str
    base_projection: ApprovedExecutionProjection
    approval_id: str
    approval_revision: str
    subject: TypedSubjectReference
    complete: Literal[True] = field(default=True, init=False)
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION:
            raise ValueError("unsupported typed-subject projection schema version")
        if not isinstance(self.base_projection, ApprovedExecutionProjection):
            raise TypeError("base_projection must be ApprovedExecutionProjection")
        if not _APPROVAL_ID_RE.fullmatch(self.approval_id):
            raise ValueError("approval_id is malformed")
        if not _REVISION_ID_RE.fullmatch(self.approval_revision):
            raise ValueError("approval_revision is malformed")
        expected = _digest(
            "approved-execution-projection:",
            {
                "schema_version": self.schema_version,
                "base_projection_id": self.base_projection.projection_id,
                "approval_id": self.approval_id,
                "approval_revision": self.approval_revision,
                "subject": self.subject.to_dict(),
            },
        )
        if self.projection_id and self.projection_id != expected:
            raise ValueError("projection_id does not match typed projection content")
        object.__setattr__(self, "projection_id", expected)


@dataclass(frozen=True, slots=True)
class TypedSubjectApprovedExecutionProjectionResult:
    status: str
    projection: TypedSubjectApprovedExecutionProjection | None
    reason_codes: tuple[str, ...]
    details: tuple[str, ...] = ()
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def build_typed_subject_approved_execution_projection(
    proposal: object,
    approval_record: TypedSubjectApprovalRecord | None,
    approval_applicability: TypedSubjectApprovalApplicabilityResult | None,
    current_subject: object,
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence | None,
    repository_state_evidence: RepositoryStateEvidence | None,
    *,
    projected_at: str,
    planning_binding: PlanningBindingEvidence | None = None,
) -> TypedSubjectApprovedExecutionProjectionResult:
    if not isinstance(approval_record, TypedSubjectApprovalRecord):
        return TypedSubjectApprovedExecutionProjectionResult(
            "needs-decision", None, ("projection.lookup-failed",), ("approval-record:missing-or-invalid",)
        )
    recomputed = evaluate_typed_subject_approval_applicability(
        approval_record,
        current_subject,
        proposal,
        issueplan_current_state_evidence,
        repository_state_evidence,
        evaluated_at=projected_at,
        planning_binding=planning_binding,
    )
    if approval_applicability != recomputed:
        return TypedSubjectApprovedExecutionProjectionResult(
            "invalid", None, ("projection.incomplete",), ("approval-applicability:mismatch",)
        )
    if recomputed.status != "applicable" or recomputed.base_applicability is None:
        return TypedSubjectApprovedExecutionProjectionResult(
            recomputed.status, None, recomputed.reason_codes or ("projection.incomplete",), recomputed.details
        )
    base_result: ApprovedExecutionProjectionResult = build_approved_execution_projection(
        proposal,
        approval_record.lifecycle_record,
        recomputed.base_applicability,
        issueplan_current_state_evidence,
        repository_state_evidence,
        projected_at=projected_at,
        planning_binding=planning_binding,
    )
    if base_result.status != "complete" or base_result.projection is None:
        return TypedSubjectApprovedExecutionProjectionResult(
            base_result.status, None, base_result.reason_codes, base_result.details
        )
    projection = TypedSubjectApprovedExecutionProjection(
        schema_version=TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION,
        projection_id="",
        base_projection=base_result.projection,
        approval_id=approval_record.approval_id,
        approval_revision=approval_record.approval_revision,
        subject=approval_record.subject,
    )
    return TypedSubjectApprovedExecutionProjectionResult("complete", projection, (), ())


def serialize_typed_subject_approved_execution_projection(
    projection: TypedSubjectApprovedExecutionProjection,
) -> bytes:
    if not isinstance(projection, TypedSubjectApprovedExecutionProjection):
        raise TypeError("projection must be TypedSubjectApprovedExecutionProjection")
    payload = {
        "schema_version": projection.schema_version,
        "projection_id": projection.projection_id,
        "base_projection": json.loads(
            serialize_approved_execution_projection(projection.base_projection)
        ),
        "approval_id": projection.approval_id,
        "approval_revision": projection.approval_revision,
        "subject": projection.subject.to_dict(),
        "complete": True,
        "authoritative": False,
        "execution_authorized": False,
        "side_effects_performed": False,
    }
    return _canonical_bytes(payload) + b"\n"
