"""Pure-local, content-bound merge authorization evidence.

This module extends the canonical approval and projection contracts with one
exact-pull-request merge authorization layer.  It performs no retrieval,
publication, merge, issue mutation, settings change, scheduling, or external I/O.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from .approved_execution_projection import ApprovedExecutionProjection
from .approval_records import (
    ApprovalApplicabilityResult,
    ApprovalRecord,
    ApprovalState,
)

MERGE_AUTHORIZATION_SCHEMA_VERSION = "1.0"
MERGE_EXECUTION_OBSERVATION_SCHEMA_VERSION = "1.0"

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_AUTHORIZATION_ID_RE = re.compile(r"^merge-authorization:[0-9a-f]{64}$")
_REVISION_ID_RE = re.compile(r"^merge-authorization-revision:[0-9a-f]{64}$")
_CHECK_ID_RE = re.compile(r"^merge-check:[0-9a-f]{64}$")
_PR_EVIDENCE_ID_RE = re.compile(
    r"^pull-request-merge-evidence:[0-9a-f]{64}$"
)
_APPLICABILITY_ID_RE = re.compile(r"^approval-applicability:[0-9a-f]{64}$")
_PROJECTION_ID_RE = re.compile(r"^approved-execution-projection:[0-9a-f]{64}$")
_OBSERVATION_ID_RE = re.compile(r"^merge-execution-observation:[0-9a-f]{64}$")
_MAX_TEXT_BYTES = 4096
_MAX_ITEMS = 256

_CHECK_STATES = frozenset(
    {
        "success",
        "failure",
        "pending",
        "cancelled",
        "skipped",
        "not-triggered",
        "unknown",
    }
)
_MERGE_METHODS = frozenset({"merge", "squash", "rebase"})
_APPLICABILITY_STATUSES = frozenset(
    {"applicable", "stale", "blocked", "invalid", "needs-decision", "consumed"}
)

MERGE_AUTHORIZATION_REASON_CODES = frozenset(
    {
        "approval.absent",
        "approval.changed",
        "approval.expired",
        "approval.invalidated",
        "approval.needs-decision",
        "approval.not-applicable",
        "approval.not-approved",
        "approval.superseded",
        "authorization.consumed",
        "authorization.expired",
        "authorization.invalidated",
        "authorization.pending",
        "authorization.rejected",
        "authorization.revoked",
        "authorization.superseded",
        "checks.cancelled",
        "checks.changed",
        "checks.failed",
        "checks.missing",
        "checks.not-triggered",
        "checks.pending",
        "checks.skipped",
        "checks.unknown",
        "contract.allowlist-changed",
        "contract.forbidden-paths-changed",
        "contract.required-tests-changed",
        "contract.scope-changed",
        "emergency-override.changed",
        "evidence.malformed",
        "merge.method-changed",
        "observation.mismatch",
        "projection.changed",
        "projection.incomplete",
        "pull-request.base-changed",
        "pull-request.draft",
        "pull-request.head-changed",
        "pull-request.identity-changed",
        "pull-request.not-ready",
        "pull-request.ready-state-changed",
        "review.blocked",
        "review.changed",
        "review.head-stale",
        "review.unresolved",
        "version.unsupported",
    }
)

_NEEDS_DECISION = frozenset(
    {
        "approval.needs-decision",
        "checks.missing",
        "checks.not-triggered",
        "checks.pending",
        "checks.unknown",
    }
)
_BLOCKED = frozenset(
    {
        "approval.absent",
        "approval.not-applicable",
        "approval.not-approved",
        "authorization.pending",
        "authorization.rejected",
        "checks.cancelled",
        "checks.failed",
        "checks.skipped",
        "pull-request.draft",
        "pull-request.not-ready",
        "review.blocked",
        "review.head-stale",
        "review.unresolved",
    }
)
_INVALID = frozenset({"evidence.malformed", "version.unsupported"})
_LIFECYCLE_REASON = {
    "expired": "authorization.expired",
    "invalidated": "authorization.invalidated",
    "consumed": "authorization.consumed",
    "superseded": "authorization.superseded",
}


class MergeAuthorizationState(str, Enum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    CONSUMED = "consumed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class MergeCheckEvidence:
    context: str
    app_identity: str
    tested_sha: str
    evidence_id: str
    state: str

    def __post_init__(self) -> None:
        _text(self.context, "context")
        _text(self.app_identity, "app_identity")
        _sha40(self.tested_sha, "tested_sha")
        if self.state not in _CHECK_STATES:
            raise ValueError("unsupported merge-check state")
        expected = _identity("merge-check", _check_payload(self))
        if self.evidence_id and self.evidence_id != expected:
            raise ValueError("evidence_id does not match merge-check content")
        object.__setattr__(self, "evidence_id", expected)


@dataclass(frozen=True, slots=True)
class MergeReviewEvidence:
    blocking_review_present: bool
    unresolved_conversation_count: int
    exact_head_reviewed: bool

    def __post_init__(self) -> None:
        for name in ("blocking_review_present", "exact_head_reviewed"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be bool")
        if (
            not isinstance(self.unresolved_conversation_count, int)
            or isinstance(self.unresolved_conversation_count, bool)
            or self.unresolved_conversation_count < 0
            or self.unresolved_conversation_count > _MAX_ITEMS
        ):
            raise ValueError("unresolved_conversation_count is out of bounds")


@dataclass(frozen=True, slots=True)
class PullRequestMergeEvidence:
    repository: str
    pull_request_number: int
    head_sha: str
    base_branch: str
    base_sha_or_evidence_id: str
    draft: bool
    ready_for_review: bool
    proposed_merge_method: str
    changed_scope_fingerprint: str
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_tests: tuple[str, ...]
    required_checks: tuple[MergeCheckEvidence, ...]
    review_evidence: MergeReviewEvidence
    evidence_id: str

    def __post_init__(self) -> None:
        _repository(self.repository)
        _positive_int(self.pull_request_number, "pull_request_number")
        _sha40(self.head_sha, "head_sha")
        _text(self.base_branch, "base_branch")
        _text(self.base_sha_or_evidence_id, "base_sha_or_evidence_id")
        if not isinstance(self.draft, bool) or not isinstance(
            self.ready_for_review, bool
        ):
            raise TypeError("draft and ready_for_review must be bool")
        if self.draft == self.ready_for_review:
            raise ValueError("exactly one Draft/Ready state must be true")
        if self.proposed_merge_method not in _MERGE_METHODS:
            raise ValueError("unsupported proposed_merge_method")
        _sha256(self.changed_scope_fingerprint, "changed_scope_fingerprint")
        object.__setattr__(
            self, "allowed_files", _strings(self.allowed_files, "allowed_files")
        )
        object.__setattr__(
            self,
            "forbidden_paths",
            _strings(self.forbidden_paths, "forbidden_paths"),
        )
        object.__setattr__(
            self, "required_tests", _strings(self.required_tests, "required_tests")
        )
        checks = _checks(self.required_checks)
        object.__setattr__(self, "required_checks", checks)
        if not isinstance(self.review_evidence, MergeReviewEvidence):
            raise TypeError("review_evidence must be MergeReviewEvidence")
        expected = _identity("pull-request-merge-evidence", _pr_payload(self))
        if self.evidence_id and self.evidence_id != expected:
            raise ValueError("evidence_id does not match pull-request content")
        object.__setattr__(self, "evidence_id", expected)


@dataclass(frozen=True, slots=True)
class MergeAuthorizationBinding:
    repository: str
    pull_request_number: int
    exact_head_sha: str
    target_base_branch: str
    base_sha_or_evidence_id: str
    permitted_merge_method: str
    approval_id: str
    approval_revision: str
    approval_applicability_identity: str
    approved_execution_projection_id: str
    changed_scope_fingerprint: str
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_tests: tuple[str, ...]
    required_check_evidence: tuple[MergeCheckEvidence, ...]
    review_evidence: MergeReviewEvidence
    draft_ready_state: Literal["draft", "ready"]

    def __post_init__(self) -> None:
        _repository(self.repository)
        _positive_int(self.pull_request_number, "pull_request_number")
        _sha40(self.exact_head_sha, "exact_head_sha")
        _text(self.target_base_branch, "target_base_branch")
        _text(self.base_sha_or_evidence_id, "base_sha_or_evidence_id")
        if self.permitted_merge_method not in _MERGE_METHODS:
            raise ValueError("unsupported permitted_merge_method")
        _matches(self.approval_id, re.compile(r"^approval:[0-9a-f]{64}$"), "approval_id")
        _matches(
            self.approval_revision,
            re.compile(r"^approval-revision:[0-9a-f]{64}$"),
            "approval_revision",
        )
        _matches(
            self.approval_applicability_identity,
            _APPLICABILITY_ID_RE,
            "approval_applicability_identity",
        )
        _matches(
            self.approved_execution_projection_id,
            _PROJECTION_ID_RE,
            "approved_execution_projection_id",
        )
        _sha256(self.changed_scope_fingerprint, "changed_scope_fingerprint")
        object.__setattr__(
            self, "allowed_files", _strings(self.allowed_files, "allowed_files")
        )
        object.__setattr__(
            self,
            "forbidden_paths",
            _strings(self.forbidden_paths, "forbidden_paths"),
        )
        object.__setattr__(
            self, "required_tests", _strings(self.required_tests, "required_tests")
        )
        object.__setattr__(
            self,
            "required_check_evidence",
            _checks(self.required_check_evidence),
        )
        if not isinstance(self.review_evidence, MergeReviewEvidence):
            raise TypeError("review_evidence must be MergeReviewEvidence")
        if self.draft_ready_state not in {"draft", "ready"}:
            raise ValueError("draft_ready_state is unsupported")


@dataclass(frozen=True, slots=True)
class MergeAuthorizationRecord:
    schema_version: str
    authorization_id: str
    authorization_revision: str
    revision_number: int
    previous_revision: str | None
    state: MergeAuthorizationState
    binding: MergeAuthorizationBinding
    authorizer_id: str
    decision_id: str
    decision_at: str
    expires_at: str | None
    supersedes_authorization_id: str | None
    revoked_authorization_id: str | None
    emergency_override_reason: str | None
    emergency_override_audit_location: str | None
    reason_codes: tuple[str, ...]
    details: tuple[str, ...] = ()
    merge_authorized: bool = field(init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != MERGE_AUTHORIZATION_SCHEMA_VERSION:
            raise ValueError("unsupported merge-authorization schema version")
        if not isinstance(self.state, MergeAuthorizationState):
            raise TypeError("state must use MergeAuthorizationState")
        if not isinstance(self.binding, MergeAuthorizationBinding):
            raise TypeError("binding must be MergeAuthorizationBinding")
        _positive_int(self.revision_number, "revision_number")
        _text(self.authorizer_id, "authorizer_id")
        _text(self.decision_id, "decision_id")
        decision_time = _timestamp(self.decision_at, "decision_at")
        expiry_time = _optional_timestamp(self.expires_at, "expires_at")
        if self.revision_number == 1:
            if (
                self.previous_revision is not None
                or self.state is not MergeAuthorizationState.PENDING
            ):
                raise ValueError("first revision must be pending with no predecessor")
        else:
            _matches(self.previous_revision, _REVISION_ID_RE, "previous_revision")
            if self.state is MergeAuthorizationState.PENDING:
                raise ValueError("later revisions cannot return to pending")
        if self.supersedes_authorization_id is not None:
            _matches(
                self.supersedes_authorization_id,
                _AUTHORIZATION_ID_RE,
                "supersedes_authorization_id",
            )
        if self.revoked_authorization_id is not None:
            _matches(
                self.revoked_authorization_id,
                _AUTHORIZATION_ID_RE,
                "revoked_authorization_id",
            )
        _override_pair(
            self.emergency_override_reason,
            self.emergency_override_audit_location,
            expiry_time,
        )
        if expiry_time is not None:
            if self.state is MergeAuthorizationState.EXPIRED:
                if decision_time < expiry_time:
                    raise ValueError("expired revision requires decision_at >= expires_at")
            elif decision_time >= expiry_time:
                raise ValueError("non-expiry decision must occur before expires_at")
        elif self.state is MergeAuthorizationState.EXPIRED:
            raise ValueError("expired revision requires expires_at")
        reasons = _reason_codes(self.reason_codes)
        required = _LIFECYCLE_REASON.get(self.state.value)
        lifecycle = set(reasons) & set(_LIFECYCLE_REASON.values())
        if required is None and lifecycle:
            raise ValueError("lifecycle reason does not match authorization state")
        if required is not None and lifecycle != {required}:
            raise ValueError(f"{self.state.value} requires only {required}")
        if self.state is MergeAuthorizationState.PENDING and reasons:
            raise ValueError("pending candidate cannot carry reason codes")
        if self.state is MergeAuthorizationState.INVALIDATED:
            if self.revoked_authorization_id != self.authorization_id:
                raise ValueError("invalidated revision must revoke its authorization")
        elif self.revoked_authorization_id is not None:
            raise ValueError("revoked_authorization_id requires invalidated state")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "details", tuple(str(item) for item in self.details))
        expected_id = _authorization_id(self)
        if self.authorization_id and self.authorization_id != expected_id:
            raise ValueError("authorization_id does not match candidate content")
        object.__setattr__(self, "authorization_id", expected_id)
        expected_revision = _authorization_revision(self)
        if self.authorization_revision and self.authorization_revision != expected_revision:
            raise ValueError("authorization_revision does not match record content")
        object.__setattr__(self, "authorization_revision", expected_revision)
        object.__setattr__(
            self,
            "merge_authorized",
            self.state is MergeAuthorizationState.AUTHORIZED,
        )


@dataclass(frozen=True, slots=True)
class MergeAuthorizationApplicabilityResult:
    status: str
    authorization_id: str | None
    authorization_revision: str | None
    current_pull_request_evidence_id: str | None
    changed_bindings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    merge_authorized: bool
    details: tuple[str, ...] = ()
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.status not in _APPLICABILITY_STATUSES:
            raise ValueError("unsupported merge-authorization applicability status")
        if self.merge_authorized != (self.status == "applicable"):
            raise ValueError("merge_authorized must match applicable status")
        if self.authorization_id is not None:
            _matches(self.authorization_id, _AUTHORIZATION_ID_RE, "authorization_id")
        if self.authorization_revision is not None:
            _matches(
                self.authorization_revision,
                _REVISION_ID_RE,
                "authorization_revision",
            )
        if self.current_pull_request_evidence_id is not None:
            _matches(
                self.current_pull_request_evidence_id,
                _PR_EVIDENCE_ID_RE,
                "current_pull_request_evidence_id",
            )
        object.__setattr__(
            self,
            "changed_bindings",
            tuple(sorted(set(str(item) for item in self.changed_bindings))),
        )
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        object.__setattr__(self, "details", tuple(str(item) for item in self.details))


@dataclass(frozen=True, slots=True)
class MergeExecutionObservation:
    schema_version: str
    observation_id: str
    authorization_id: str
    authorization_revision: str
    repository: str
    pull_request_number: int
    observed_head_sha: str
    observed_base_identity: str
    observed_merge_method: str
    observed_merge_commit_sha: str
    observed_actor_id: str
    observed_at: str
    audit_location: str
    linked_issue_closure_observed: bool
    authorization_consumed: Literal[True] = field(default=True, init=False)
    side_effects_performed: Literal[True] = field(default=True, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != MERGE_EXECUTION_OBSERVATION_SCHEMA_VERSION:
            raise ValueError("unsupported merge-execution observation version")
        _matches(self.authorization_id, _AUTHORIZATION_ID_RE, "authorization_id")
        _matches(
            self.authorization_revision,
            _REVISION_ID_RE,
            "authorization_revision",
        )
        _repository(self.repository)
        _positive_int(self.pull_request_number, "pull_request_number")
        _sha40(self.observed_head_sha, "observed_head_sha")
        _text(self.observed_base_identity, "observed_base_identity")
        if self.observed_merge_method not in _MERGE_METHODS:
            raise ValueError("unsupported observed_merge_method")
        _sha40(self.observed_merge_commit_sha, "observed_merge_commit_sha")
        _text(self.observed_actor_id, "observed_actor_id")
        _timestamp(self.observed_at, "observed_at")
        _text(self.audit_location, "audit_location")
        if not isinstance(self.linked_issue_closure_observed, bool):
            raise TypeError("linked_issue_closure_observed must be bool")
        expected = _identity("merge-execution-observation", _observation_payload(self))
        if self.observation_id and self.observation_id != expected:
            raise ValueError("observation_id does not match observation content")
        object.__setattr__(self, "observation_id", expected)


def build_merge_authorization_candidate(
    approval_record: ApprovalRecord,
    approval_applicability: ApprovalApplicabilityResult,
    approved_execution_projection: ApprovedExecutionProjection,
    pull_request_evidence: PullRequestMergeEvidence,
    *,
    authorizer_id: str,
    decision_id: str,
    decision_at: str,
    expires_at: str | None = None,
    permitted_merge_method: str | None = None,
    supersedes: MergeAuthorizationRecord | None = None,
    emergency_override_reason: str | None = None,
    emergency_override_audit_location: str | None = None,
) -> MergeAuthorizationRecord:
    binding, reasons, details = _current_binding(
        approval_record,
        approval_applicability,
        approved_execution_projection,
        pull_request_evidence,
        permitted_merge_method=permitted_merge_method,
    )
    if reasons:
        raise ValueError(
            "merge authorization candidate requires current eligible evidence: "
            + ",".join((*reasons, *details))
        )
    prior_id = None
    if supersedes is not None:
        prior = _verified(supersedes, MergeAuthorizationRecord)
        if prior.state not in {
            MergeAuthorizationState.REJECTED,
            MergeAuthorizationState.EXPIRED,
            MergeAuthorizationState.INVALIDATED,
            MergeAuthorizationState.CONSUMED,
            MergeAuthorizationState.SUPERSEDED,
        }:
            raise ValueError("replacement candidate requires terminal prior authorization")
        if _timestamp(decision_at, "decision_at") < _timestamp(
            prior.decision_at, "prior decision_at"
        ):
            raise ValueError("replacement candidate cannot predate prior authorization")
        prior_id = prior.authorization_id
    return MergeAuthorizationRecord(
        schema_version=MERGE_AUTHORIZATION_SCHEMA_VERSION,
        authorization_id="",
        authorization_revision="",
        revision_number=1,
        previous_revision=None,
        state=MergeAuthorizationState.PENDING,
        binding=binding,
        authorizer_id=authorizer_id,
        decision_id=decision_id,
        decision_at=decision_at,
        expires_at=expires_at,
        supersedes_authorization_id=prior_id,
        revoked_authorization_id=None,
        emergency_override_reason=emergency_override_reason,
        emergency_override_audit_location=emergency_override_audit_location,
        reason_codes=(),
    )


def record_merge_authorization_decision(
    current: MergeAuthorizationRecord,
    *,
    state: MergeAuthorizationState | str,
    decision_id: str,
    authorizer_id: str,
    decision_at: str,
    reason_codes: Iterable[str] = (),
    details: Iterable[str] = (),
) -> MergeAuthorizationRecord:
    current = _verified(current, MergeAuthorizationRecord)
    target = MergeAuthorizationState(state)
    allowed = {
        MergeAuthorizationState.PENDING: {
            MergeAuthorizationState.AUTHORIZED,
            MergeAuthorizationState.REJECTED,
            MergeAuthorizationState.EXPIRED,
            MergeAuthorizationState.INVALIDATED,
            MergeAuthorizationState.SUPERSEDED,
        },
        MergeAuthorizationState.AUTHORIZED: {
            MergeAuthorizationState.EXPIRED,
            MergeAuthorizationState.INVALIDATED,
            MergeAuthorizationState.CONSUMED,
            MergeAuthorizationState.SUPERSEDED,
        },
    }
    if target not in allowed.get(current.state, set()):
        raise ValueError(
            f"invalid merge authorization transition: {current.state.value} -> {target.value}"
        )
    decision_time = _timestamp(decision_at, "decision_at")
    if decision_time < _timestamp(current.decision_at, "current decision_at"):
        raise ValueError("decision revisions cannot move backward in time")
    expiry_time = _optional_timestamp(current.expires_at, "expires_at")
    if target is MergeAuthorizationState.EXPIRED:
        if expiry_time is None or decision_time < expiry_time:
            raise ValueError("expired revision requires decision_at >= expires_at")
    elif expiry_time is not None and decision_time >= expiry_time:
        raise ValueError("non-expiry decision must occur before expires_at")
    reasons = set(_reason_codes(reason_codes))
    lifecycle = _LIFECYCLE_REASON.get(target.value)
    if lifecycle is not None:
        reasons.add(lifecycle)
    revoked = current.authorization_id if target is MergeAuthorizationState.INVALIDATED else None
    return MergeAuthorizationRecord(
        schema_version=current.schema_version,
        authorization_id=current.authorization_id,
        authorization_revision="",
        revision_number=current.revision_number + 1,
        previous_revision=current.authorization_revision,
        state=target,
        binding=current.binding,
        authorizer_id=authorizer_id,
        decision_id=decision_id,
        decision_at=decision_at,
        expires_at=current.expires_at,
        supersedes_authorization_id=current.supersedes_authorization_id,
        revoked_authorization_id=revoked,
        emergency_override_reason=current.emergency_override_reason,
        emergency_override_audit_location=current.emergency_override_audit_location,
        reason_codes=tuple(sorted(reasons)),
        details=tuple(str(item) for item in details),
    )


def evaluate_merge_authorization_applicability(
    authorization_record: MergeAuthorizationRecord | None,
    current_approval_record: ApprovalRecord,
    current_approval_applicability: ApprovalApplicabilityResult,
    current_approved_execution_projection: ApprovedExecutionProjection,
    current_pull_request_evidence: PullRequestMergeEvidence,
    *,
    evaluated_at: str,
    invalidation_events: Iterable[str] = (),
) -> MergeAuthorizationApplicabilityResult:
    evaluation_time = _timestamp(evaluated_at, "evaluated_at")
    try:
        current_pr = _verified(current_pull_request_evidence, PullRequestMergeEvidence)
    except (TypeError, ValueError) as exc:
        return _result(
            "invalid",
            getattr(authorization_record, "authorization_id", None),
            getattr(authorization_record, "authorization_revision", None),
            getattr(current_pull_request_evidence, "evidence_id", None),
            (),
            ("evidence.malformed",),
            (f"pull-request-evidence:{exc}",),
        )
    if authorization_record is None:
        return _result(
            "blocked",
            None,
            None,
            current_pr.evidence_id,
            (),
            ("authorization.pending",),
            ("merge-authorization-record:absent",),
        )
    try:
        authorization = _verified(authorization_record, MergeAuthorizationRecord)
    except (TypeError, ValueError) as exc:
        reason = (
            "version.unsupported"
            if getattr(authorization_record, "schema_version", None)
            != MERGE_AUTHORIZATION_SCHEMA_VERSION
            else "evidence.malformed"
        )
        return _result(
            "invalid",
            getattr(authorization_record, "authorization_id", None),
            getattr(authorization_record, "authorization_revision", None),
            current_pr.evidence_id,
            (),
            (reason,),
            (f"merge-authorization-record:{exc}",),
        )
    try:
        binding, current_reasons, current_details = _current_binding(
            current_approval_record,
            current_approval_applicability,
            current_approved_execution_projection,
            current_pr,
            permitted_merge_method=current_pr.proposed_merge_method,
        )
    except (TypeError, ValueError) as exc:
        return _result(
            "invalid",
            authorization.authorization_id,
            authorization.authorization_revision,
            current_pr.evidence_id,
            (),
            ("evidence.malformed",),
            (f"current-evidence:{exc}",),
        )
    changed = _changed_bindings(authorization.binding, binding)
    reasons = set(current_reasons)
    reasons.update(_reason_codes(invalidation_events))
    reasons.update(_binding_reasons(changed))
    if len(current_pr.required_checks) < len(authorization.binding.required_check_evidence):
        reasons.add("checks.missing")
    if authorization.state is MergeAuthorizationState.PENDING:
        reasons.add("authorization.pending")
    elif authorization.state is MergeAuthorizationState.REJECTED:
        reasons.add("authorization.rejected")
    elif authorization.state is MergeAuthorizationState.CONSUMED:
        reasons.add("authorization.consumed")
    else:
        lifecycle = _LIFECYCLE_REASON.get(authorization.state.value)
        if lifecycle is not None:
            reasons.add(lifecycle)
    if authorization.revoked_authorization_id is not None:
        reasons.add("authorization.revoked")
    expiry_time = _optional_timestamp(authorization.expires_at, "expires_at")
    if expiry_time is not None and evaluation_time >= expiry_time:
        reasons.add("authorization.expired")
    status = _status_for_reasons(reasons)
    if status == "applicable" and (
        changed or authorization.state is not MergeAuthorizationState.AUTHORIZED
    ):
        status = "stale" if changed else "blocked"
    return _result(
        status,
        authorization.authorization_id,
        authorization.authorization_revision,
        current_pr.evidence_id,
        changed,
        reasons,
        current_details,
    )


def record_merge_execution_observation(
    authorization_record: MergeAuthorizationRecord,
    applicability: MergeAuthorizationApplicabilityResult,
    pull_request_evidence: PullRequestMergeEvidence,
    *,
    observed_merge_commit_sha: str,
    observed_actor_id: str,
    observed_at: str,
    audit_location: str,
    observed_merge_method: str,
    linked_issue_closure_observed: bool = False,
) -> MergeExecutionObservation:
    authorization = _verified(authorization_record, MergeAuthorizationRecord)
    result = _verified(applicability, MergeAuthorizationApplicabilityResult)
    current_pr = _verified(pull_request_evidence, PullRequestMergeEvidence)
    if authorization.state is not MergeAuthorizationState.AUTHORIZED:
        raise ValueError("merge observation requires an authorized record")
    if (
        result.status != "applicable"
        or not result.merge_authorized
        or result.authorization_id != authorization.authorization_id
        or result.authorization_revision != authorization.authorization_revision
        or result.current_pull_request_evidence_id != current_pr.evidence_id
    ):
        raise ValueError("merge observation requires matching applicable authorization")
    changed = _changed_bindings(
        authorization.binding,
        _binding_from_pr_and_record(current_pr, authorization.binding),
    )
    if changed or observed_merge_method != authorization.binding.permitted_merge_method:
        raise ValueError("merge observation does not match authorization binding")
    observed_time = _timestamp(observed_at, "observed_at")
    if observed_time < _timestamp(authorization.decision_at, "decision_at"):
        raise ValueError("merge observation cannot predate authorization")
    expiry_time = _optional_timestamp(authorization.expires_at, "expires_at")
    if expiry_time is not None and observed_time >= expiry_time:
        raise ValueError("merge observation cannot consume expired authorization")
    return MergeExecutionObservation(
        schema_version=MERGE_EXECUTION_OBSERVATION_SCHEMA_VERSION,
        observation_id="",
        authorization_id=authorization.authorization_id,
        authorization_revision=authorization.authorization_revision,
        repository=current_pr.repository,
        pull_request_number=current_pr.pull_request_number,
        observed_head_sha=current_pr.head_sha,
        observed_base_identity=current_pr.base_sha_or_evidence_id,
        observed_merge_method=observed_merge_method,
        observed_merge_commit_sha=observed_merge_commit_sha,
        observed_actor_id=observed_actor_id,
        observed_at=observed_at,
        audit_location=audit_location,
        linked_issue_closure_observed=linked_issue_closure_observed,
    )


def approval_applicability_identity(
    result: ApprovalApplicabilityResult,
) -> str:
    verified = _verified(result, ApprovalApplicabilityResult)
    return _identity(
        "approval-applicability",
        {
            "status": verified.status,
            "approval_id": verified.approval_id,
            "approval_revision": verified.approval_revision,
            "current_proposal_id": verified.current_proposal_id,
            "reason_codes": verified.reason_codes,
            "changed_bindings": verified.changed_bindings,
            "approval_applicable": verified.approval_applicable,
        },
    )


def _current_binding(
    approval_record: ApprovalRecord,
    approval_applicability: ApprovalApplicabilityResult,
    projection: ApprovedExecutionProjection,
    pull_request: PullRequestMergeEvidence,
    *,
    permitted_merge_method: str | None,
) -> tuple[MergeAuthorizationBinding, tuple[str, ...], tuple[str, ...]]:
    reasons: set[str] = set()
    details: list[str] = []
    try:
        approval = _verified(approval_record, ApprovalRecord)
        applicability = _verified(approval_applicability, ApprovalApplicabilityResult)
        projected = _verified(projection, ApprovedExecutionProjection)
        pr = _verified(pull_request, PullRequestMergeEvidence)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"malformed merge-authorization input: {exc}") from exc
    method = permitted_merge_method or pr.proposed_merge_method
    if method not in _MERGE_METHODS:
        raise ValueError("unsupported permitted merge method")
    if approval.state is not ApprovalState.APPROVED:
        reasons.add("approval.not-approved")
    if applicability.status != "applicable" or not applicability.approval_applicable:
        reasons.add(
            "approval.needs-decision"
            if applicability.status == "needs-decision"
            else "approval.not-applicable"
        )
    if (
        applicability.approval_id != approval.approval_id
        or applicability.approval_revision != approval.approval_revision
        or applicability.current_proposal_id != projected.proposal_id
    ):
        reasons.add("approval.changed")
    if (
        projected.approval_id != approval.approval_id
        or projected.approval_revision != approval.approval_revision
    ):
        reasons.add("projection.changed")
    if projected.repository != pr.repository:
        reasons.add("pull-request.identity-changed")
    if projected.base_branch != pr.base_branch:
        reasons.add("pull-request.base-changed")
    if projected.tested_repository_sha != pr.head_sha:
        reasons.add("pull-request.head-changed")
    if projected.allowed_files != pr.allowed_files:
        reasons.add("contract.allowlist-changed")
    if projected.forbidden_paths != pr.forbidden_paths:
        reasons.add("contract.forbidden-paths-changed")
    if projected.required_tests != pr.required_tests:
        reasons.add("contract.required-tests-changed")
    reasons.update(_eligibility_reasons(pr))
    if method != pr.proposed_merge_method:
        reasons.add("merge.method-changed")
    binding = MergeAuthorizationBinding(
        repository=pr.repository,
        pull_request_number=pr.pull_request_number,
        exact_head_sha=pr.head_sha,
        target_base_branch=pr.base_branch,
        base_sha_or_evidence_id=pr.base_sha_or_evidence_id,
        permitted_merge_method=method,
        approval_id=approval.approval_id,
        approval_revision=approval.approval_revision,
        approval_applicability_identity=approval_applicability_identity(applicability),
        approved_execution_projection_id=projected.projection_id,
        changed_scope_fingerprint=pr.changed_scope_fingerprint,
        allowed_files=pr.allowed_files,
        forbidden_paths=pr.forbidden_paths,
        required_tests=pr.required_tests,
        required_check_evidence=pr.required_checks,
        review_evidence=pr.review_evidence,
        draft_ready_state="draft" if pr.draft else "ready",
    )
    return binding, tuple(sorted(reasons)), tuple(details)


def _eligibility_reasons(pr: PullRequestMergeEvidence) -> set[str]:
    reasons: set[str] = set()
    if pr.draft:
        reasons.add("pull-request.draft")
    if not pr.ready_for_review:
        reasons.add("pull-request.not-ready")
    if pr.review_evidence.blocking_review_present:
        reasons.add("review.blocked")
    if pr.review_evidence.unresolved_conversation_count:
        reasons.add("review.unresolved")
    if not pr.review_evidence.exact_head_reviewed:
        reasons.add("review.head-stale")
    for check in pr.required_checks:
        if check.tested_sha != pr.head_sha:
            reasons.add("checks.changed")
        if check.state != "success":
            reason = "checks.failed" if check.state == "failure" else f"checks.{check.state}"
            reasons.add(reason)
    return reasons


def _binding_from_pr_and_record(
    pr: PullRequestMergeEvidence,
    prior: MergeAuthorizationBinding,
) -> MergeAuthorizationBinding:
    return MergeAuthorizationBinding(
        repository=pr.repository,
        pull_request_number=pr.pull_request_number,
        exact_head_sha=pr.head_sha,
        target_base_branch=pr.base_branch,
        base_sha_or_evidence_id=pr.base_sha_or_evidence_id,
        permitted_merge_method=pr.proposed_merge_method,
        approval_id=prior.approval_id,
        approval_revision=prior.approval_revision,
        approval_applicability_identity=prior.approval_applicability_identity,
        approved_execution_projection_id=prior.approved_execution_projection_id,
        changed_scope_fingerprint=pr.changed_scope_fingerprint,
        allowed_files=pr.allowed_files,
        forbidden_paths=pr.forbidden_paths,
        required_tests=pr.required_tests,
        required_check_evidence=pr.required_checks,
        review_evidence=pr.review_evidence,
        draft_ready_state="draft" if pr.draft else "ready",
    )


def _changed_bindings(
    prior: MergeAuthorizationBinding,
    current: MergeAuthorizationBinding,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            item.name
            for item in fields(MergeAuthorizationBinding)
            if getattr(prior, item.name) != getattr(current, item.name)
        )
    )


def _binding_reasons(changed: Iterable[str]) -> set[str]:
    mapping = {
        "repository": "pull-request.identity-changed",
        "pull_request_number": "pull-request.identity-changed",
        "exact_head_sha": "pull-request.head-changed",
        "target_base_branch": "pull-request.base-changed",
        "base_sha_or_evidence_id": "pull-request.base-changed",
        "permitted_merge_method": "merge.method-changed",
        "approval_id": "approval.changed",
        "approval_revision": "approval.changed",
        "approval_applicability_identity": "approval.changed",
        "approved_execution_projection_id": "projection.changed",
        "changed_scope_fingerprint": "contract.scope-changed",
        "allowed_files": "contract.allowlist-changed",
        "forbidden_paths": "contract.forbidden-paths-changed",
        "required_tests": "contract.required-tests-changed",
        "required_check_evidence": "checks.changed",
        "review_evidence": "review.changed",
        "draft_ready_state": "pull-request.ready-state-changed",
    }
    return {mapping[item] for item in changed if item in mapping}


def _status_for_reasons(reasons: Iterable[str]) -> str:
    items = set(reasons)
    if not items:
        return "applicable"
    if "authorization.consumed" in items:
        return "consumed"
    if items & _INVALID:
        return "invalid"
    if items & _NEEDS_DECISION:
        return "needs-decision"
    if items & _BLOCKED:
        return "blocked"
    return "stale"


def _result(
    status: str,
    authorization_id: str | None,
    authorization_revision: str | None,
    current_pr_id: str | None,
    changed: Iterable[str],
    reasons: Iterable[str],
    details: Iterable[str],
) -> MergeAuthorizationApplicabilityResult:
    return MergeAuthorizationApplicabilityResult(
        status=status,
        authorization_id=authorization_id,
        authorization_revision=authorization_revision,
        current_pull_request_evidence_id=current_pr_id,
        changed_bindings=tuple(changed),
        reason_codes=tuple(reasons),
        merge_authorized=status == "applicable",
        details=tuple(details),
    )


def _verified(value: Any, expected_type: type[Any]) -> Any:
    if not isinstance(value, expected_type):
        raise TypeError(f"expected {expected_type.__name__}")
    kwargs = {item.name: getattr(value, item.name) for item in fields(expected_type) if item.init}
    return expected_type(**kwargs)


def _authorization_id(record: MergeAuthorizationRecord) -> str:
    return _identity(
        "merge-authorization",
        {
            "schema_version": record.schema_version,
            "binding": record.binding,
            "expires_at": record.expires_at,
            "supersedes_authorization_id": record.supersedes_authorization_id,
            "emergency_override_reason": record.emergency_override_reason,
            "emergency_override_audit_location": record.emergency_override_audit_location,
        },
    )


def _authorization_revision(record: MergeAuthorizationRecord) -> str:
    return _identity(
        "merge-authorization-revision",
        {
            "authorization_id": record.authorization_id,
            "revision_number": record.revision_number,
            "previous_revision": record.previous_revision,
            "state": record.state,
            "authorizer_id": record.authorizer_id,
            "decision_id": record.decision_id,
            "decision_at": record.decision_at,
            "revoked_authorization_id": record.revoked_authorization_id,
            "reason_codes": record.reason_codes,
            "details": record.details,
        },
    )


def _identity(prefix: str, payload: Any) -> str:
    digest = hashlib.sha256(
        f"agent-os-{prefix}:v1\0".encode("ascii") + _canonical_bytes(payload)
    ).hexdigest()
    return f"{prefix}:{digest}"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {
            item.name: _json_value(getattr(value, item.name))
            for item in fields(value)
            if item.init
        }
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _check_payload(check: MergeCheckEvidence) -> dict[str, Any]:
    return {
        "context": check.context,
        "app_identity": check.app_identity,
        "tested_sha": check.tested_sha,
        "state": check.state,
    }


def _pr_payload(pr: PullRequestMergeEvidence) -> dict[str, Any]:
    return {
        item.name: getattr(pr, item.name)
        for item in fields(PullRequestMergeEvidence)
        if item.init and item.name != "evidence_id"
    }


def _observation_payload(observation: MergeExecutionObservation) -> dict[str, Any]:
    return {
        item.name: getattr(observation, item.name)
        for item in fields(MergeExecutionObservation)
        if item.init and item.name != "observation_id"
    }


def _checks(value: Iterable[MergeCheckEvidence]) -> tuple[MergeCheckEvidence, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError("required checks must be an iterable of MergeCheckEvidence")
    items = tuple(_verified(item, MergeCheckEvidence) for item in value)
    if not items or len(items) > _MAX_ITEMS:
        raise ValueError("required checks must be non-empty and bounded")
    identities = tuple((item.context, item.app_identity) for item in items)
    if len(set(identities)) != len(identities):
        raise ValueError("required check identities must be unique")
    return tuple(
        sorted(
            items,
            key=lambda item: (
                item.context,
                item.app_identity,
                item.tested_sha,
                item.evidence_id,
                item.state,
            ),
        )
    )


def _strings(value: Iterable[str], name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of strings")
    items = tuple(value)
    if len(items) > _MAX_ITEMS:
        raise ValueError(f"{name} exceeds bounded item count")
    for item in items:
        _text(item, name)
    if len(set(items)) != len(items):
        raise ValueError(f"{name} contains duplicate values")
    return tuple(sorted(items))


def _reason_codes(value: Iterable[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError("reason_codes must be an iterable")
    reasons = tuple(sorted(set(value)))
    unknown = set(reasons) - MERGE_AUTHORIZATION_REASON_CODES
    if unknown:
        raise ValueError(f"unsupported merge-authorization reason codes: {sorted(unknown)}")
    return reasons


def _override_pair(
    reason: str | None,
    audit_location: str | None,
    expiry_time: datetime | None,
) -> None:
    if (reason is None) != (audit_location is None):
        raise ValueError("emergency override reason and audit location must be paired")
    if reason is not None:
        _text(reason, "emergency_override_reason")
        _text(audit_location, "emergency_override_audit_location")
        if expiry_time is None:
            raise ValueError("emergency override must be time-bounded")


def _repository(value: str) -> str:
    text = _text(value, "repository")
    if text.count("/") != 1 or any(part in {"", ".", ".."} for part in text.split("/")):
        raise ValueError("repository must use owner/name form")
    return text


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{name} must be non-empty NUL-free text")
    if len(value.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError(f"{name} exceeds bounded byte length")
    return value


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _sha40(value: Any, name: str) -> str:
    text = _text(value, name)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError(f"{name} must be a full lowercase SHA")
    return text


def _sha256(value: Any, name: str) -> str:
    text = _text(value, name)
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{name} must be lowercase SHA-256 text")
    return text


def _matches(value: Any, pattern: re.Pattern[str], name: str) -> str:
    text = _text(value, name)
    if not pattern.fullmatch(text):
        raise ValueError(f"{name} is malformed")
    return text


def _timestamp(value: Any, name: str) -> datetime:
    text = _text(value, name)
    if not _TIMESTAMP_RE.fullmatch(text):
        raise ValueError(f"{name} must use canonical UTC timestamp format")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{name} is not a valid timestamp") from exc


def _optional_timestamp(value: Any, name: str) -> datetime | None:
    return None if value is None else _timestamp(value, name)
