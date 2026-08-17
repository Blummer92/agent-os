"""Deterministic continuation admission for already-authorized Agent OS work.

This module is the #1188 composition seam between the existing #895
``ResumePlan`` and the existing #758 Scheduler lease. It performs no discovery,
Git mutation, lease mutation, checkpoint persistence, retry, provider execution,
validation, or external I/O. All inputs are caller-supplied current evidence.

The lease remains the concurrency authority and the resume plan remains
continuation evidence. Neither creates implementation authorization.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from scripts.agent_os_execution_checkpoint.resume_planner import (
    ResumePlan,
    StageClassification,
)
from workflow_scheduler.execution.host_local_lease_adapter import (
    HostLocalLeaseObservation,
)
from workflow_scheduler.execution.single_issue_pilot import (
    PilotLeaseRequest,
    pilot_holder_identity,
    pilot_lease_identity,
)

CONTINUATION_SCHEMA_VERSION = "1.0"
_MAX_TEXT = 512
_MAX_REASON_CODES = 24
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)


class ContinuationDisposition(str, Enum):
    NO_EXISTING_WORK = "no-existing-work"
    RESUMABLE_EXISTING_WORK = "resumable-existing-work"
    ACTIVE_CONFLICT = "active-conflict"
    STALE_EXISTING_WORK = "stale-existing-work"
    HEAD_ADVANCED = "head-advanced"
    SCOPE_DRIFT = "scope-drift"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExistingExecutionIdentity:
    """Bounded identity for the discovered authorized execution/checkpoint lineage."""

    repository: str
    issue_number: int
    branch: str
    base_sha: str
    head_sha: str
    invocation_id: str
    execution_id: str
    candidate_identity: str
    checkpoint_lineage_identity: str
    authorization_identity: str
    executor_identity: str
    scope_identity: str

    def __post_init__(self) -> None:
        _bounded_text(self.repository, "repository")
        _bounded_text(self.branch, "branch")
        _sha40(self.base_sha, "base_sha")
        _sha40(self.head_sha, "head_sha")
        if type(self.issue_number) is not int or isinstance(self.issue_number, bool) or self.issue_number < 1:
            raise TypeError("issue_number must be a positive exact integer")
        for name in (
            "invocation_id",
            "execution_id",
            "candidate_identity",
            "checkpoint_lineage_identity",
            "authorization_identity",
            "executor_identity",
            "scope_identity",
        ):
            _bounded_text(getattr(self, name), name)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExistingWorkEvidence:
    """Caller-supplied live discovery facts for one Safe Implementation Lane issue."""

    repository: str
    issue_number: int
    branch: str
    current_base_sha: str
    current_head_sha: str
    primary_pr_count: int
    branch_present: bool
    draft_pr_present: bool
    checkpoint_lineage_present: bool
    authorization_applicable: bool
    authorization_current: bool
    source_of_truth_current: bool
    ownership_current: bool
    scope_current: bool
    excluded_surface_present: bool
    head_advance_in_scope: bool
    existing_execution: ExistingExecutionIdentity | None = None
    base_behind: bool = False
    branch_conflicted: bool = False

    def __post_init__(self) -> None:
        _bounded_text(self.repository, "repository")
        _bounded_text(self.branch, "branch")
        _sha40(self.current_base_sha, "current_base_sha")
        _sha40(self.current_head_sha, "current_head_sha")
        if type(self.issue_number) is not int or isinstance(self.issue_number, bool) or self.issue_number < 1:
            raise TypeError("issue_number must be a positive exact integer")
        if type(self.primary_pr_count) is not int or isinstance(self.primary_pr_count, bool):
            raise TypeError("primary_pr_count must be an exact integer")
        if self.primary_pr_count < 0 or self.primary_pr_count > 8:
            raise ValueError("primary_pr_count exceeds the bounded range")
        if self.existing_execution is not None and type(self.existing_execution) is not ExistingExecutionIdentity:
            raise TypeError("existing_execution must be exact ExistingExecutionIdentity or None")
        for name in (
            "branch_present",
            "draft_pr_present",
            "checkpoint_lineage_present",
            "authorization_applicable",
            "authorization_current",
            "source_of_truth_current",
            "ownership_current",
            "scope_current",
            "excluded_surface_present",
            "head_advance_in_scope",
            "base_behind",
            "branch_conflicted",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")

    @property
    def existing_work_present(self) -> bool:
        return self.branch_present or self.draft_pr_present or self.checkpoint_lineage_present


@dataclass(frozen=True, slots=True, kw_only=True)
class ContinuationDecision:
    schema_version: Literal["1.0"]
    disposition: ContinuationDisposition
    repository: str
    issue_number: int
    branch: str
    observed_base_sha: str
    observed_head_sha: str
    current_base_sha: str
    current_head_sha: str
    invocation_id: str | None
    execution_id: str | None
    candidate_identity: str | None
    checkpoint_lineage_identity: str | None
    authorization_identity: str | None
    executor_identity: str | None
    scope_identity: str | None
    resume_plan_id: str | None
    resume_point: str | None
    lease_identity: str | None
    lease_holder_identity: str | None
    lease_generation: int | None
    reason_codes: tuple[str, ...]
    recommended_action: str
    decision_id: str = field(init=False)
    continuation_authorized: Literal[False] = field(default=False, init=False)
    branch_refresh_authorized: Literal[False] = field(default=False, init=False)
    retry_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != CONTINUATION_SCHEMA_VERSION:
            raise ValueError("unsupported continuation schema version")
        if type(self.disposition) is not ContinuationDisposition:
            raise TypeError("disposition must be an exact ContinuationDisposition")
        _bounded_text(self.repository, "repository")
        _bounded_text(self.branch, "branch")
        for name in ("observed_base_sha", "observed_head_sha", "current_base_sha", "current_head_sha"):
            _sha40(getattr(self, name), name)
        if type(self.issue_number) is not int or isinstance(self.issue_number, bool) or self.issue_number < 1:
            raise TypeError("issue_number must be a positive exact integer")
        for name in (
            "invocation_id", "execution_id", "candidate_identity",
            "checkpoint_lineage_identity", "authorization_identity",
            "executor_identity", "scope_identity", "resume_plan_id",
            "resume_point", "lease_identity", "lease_holder_identity",
        ):
            value = getattr(self, name)
            if value is not None:
                _bounded_text(value, name)
        if self.lease_generation is not None and (
            type(self.lease_generation) is not int or self.lease_generation < 0
        ):
            raise TypeError("lease_generation must be a non-negative exact integer or None")
        if type(self.reason_codes) is not tuple:
            raise TypeError("reason_codes must be an exact tuple")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("reason_codes must be sorted and unique")
        if len(self.reason_codes) > _MAX_REASON_CODES:
            raise ValueError("reason_codes exceeds the bounded count")
        for reason in self.reason_codes:
            _bounded_text(reason, "reason_code")
        _bounded_text(self.recommended_action, "recommended_action")
        payload = {
            "schema_version": self.schema_version,
            "disposition": self.disposition.value,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "branch": self.branch,
            "observed_base_sha": self.observed_base_sha,
            "observed_head_sha": self.observed_head_sha,
            "current_base_sha": self.current_base_sha,
            "current_head_sha": self.current_head_sha,
            "invocation_id": self.invocation_id,
            "execution_id": self.execution_id,
            "candidate_identity": self.candidate_identity,
            "checkpoint_lineage_identity": self.checkpoint_lineage_identity,
            "authorization_identity": self.authorization_identity,
            "executor_identity": self.executor_identity,
            "scope_identity": self.scope_identity,
            "resume_plan_id": self.resume_plan_id,
            "resume_point": self.resume_point,
            "lease_identity": self.lease_identity,
            "lease_holder_identity": self.lease_holder_identity,
            "lease_generation": self.lease_generation,
            "reason_codes": list(self.reason_codes),
            "recommended_action": self.recommended_action,
            "continuation_authorized": False,
            "branch_refresh_authorized": False,
            "retry_authorized": False,
            "merge_authorized": False,
            "issue_closure_authorized": False,
            "external_writes_authorized": False,
        }
        object.__setattr__(
            self,
            "decision_id",
            "execution-continuation:" + hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        )


_ACTIONS = {
    ContinuationDisposition.NO_EXISTING_WORK: "continue the normal Safe Implementation Lane creation path",
    ContinuationDisposition.RESUMABLE_EXISTING_WORK: (
        "consume the canonical ResumePlan and continue from its earliest non-reusable stage after normal lease acquisition"
    ),
    ContinuationDisposition.ACTIVE_CONFLICT: (
        "do not create duplicate work or take over the lease; join or await the governed execution through existing Scheduler semantics"
    ),
    ContinuationDisposition.STALE_EXISTING_WORK: (
        "reacquire current evidence and replan; do not infer authority, retry, or take over a lease"
    ),
    ContinuationDisposition.HEAD_ADVANCED: (
        "rebind the current head, invalidate head-bound evidence, recompute the ResumePlan, then continue if authorization and scope remain valid"
    ),
    ContinuationDisposition.SCOPE_DRIFT: "stop fail-closed and obtain a new scope or authorization decision",
    ContinuationDisposition.NEEDS_DECISION: "preserve current state and route the unresolved evidence for manual review",
}


def plan_execution_continuation(
    evidence: ExistingWorkEvidence,
    *,
    resume_plan: ResumePlan | None,
    lease_request: PilotLeaseRequest | None,
    lease_observation: HostLocalLeaseObservation | None,
) -> ContinuationDecision:
    """Classify existing work without performing any mutation.

    For discovered work, ``lease_request`` is the canonical lease request bound
    to the discovered execution/candidate, not a newly invented resume request.
    """
    if type(evidence) is not ExistingWorkEvidence:
        raise TypeError("evidence must be exact ExistingWorkEvidence")
    if resume_plan is not None and type(resume_plan) is not ResumePlan:
        raise TypeError("resume_plan must be exact ResumePlan or None")
    if lease_request is not None and type(lease_request) is not PilotLeaseRequest:
        raise TypeError("lease_request must be exact PilotLeaseRequest or None")
    if lease_observation is not None and type(lease_observation) is not HostLocalLeaseObservation:
        raise TypeError("lease_observation must be exact HostLocalLeaseObservation or None")

    lease_fields = _lease_fields(lease_observation)
    if not evidence.existing_work_present:
        return _decision(evidence, ContinuationDisposition.NO_EXISTING_WORK, None, lease_fields, ("existing.none",))
    if evidence.primary_pr_count > 1:
        return _decision(evidence, ContinuationDisposition.NEEDS_DECISION, resume_plan, lease_fields, ("existing.multiple-primary-prs",))
    if evidence.existing_execution is None:
        return _decision(evidence, ContinuationDisposition.STALE_EXISTING_WORK, resume_plan, lease_fields, ("existing.execution-identity-unavailable",))

    identity_error = _identity_reason(evidence)
    if identity_error is not None:
        return _decision(evidence, ContinuationDisposition.NEEDS_DECISION, resume_plan, lease_fields, (identity_error,))
    if not evidence.authorization_applicable:
        return _decision(evidence, ContinuationDisposition.SCOPE_DRIFT, resume_plan, lease_fields, ("authorization.no-longer-applicable",))
    if not evidence.authorization_current:
        return _decision(evidence, ContinuationDisposition.STALE_EXISTING_WORK, resume_plan, lease_fields, ("authorization.stale",))
    if not evidence.source_of_truth_current:
        return _decision(evidence, ContinuationDisposition.SCOPE_DRIFT, resume_plan, lease_fields, ("source-of-truth.drift",))
    if not evidence.ownership_current:
        return _decision(evidence, ContinuationDisposition.SCOPE_DRIFT, resume_plan, lease_fields, ("ownership.drift",))
    if not evidence.scope_current or evidence.excluded_surface_present:
        reason = "scope.excluded-surface" if evidence.excluded_surface_present else "scope.drift"
        return _decision(evidence, ContinuationDisposition.SCOPE_DRIFT, resume_plan, lease_fields, (reason,))

    lease_decision = _classify_lease(evidence, resume_plan, lease_request, lease_observation)
    if lease_decision is not None:
        return lease_decision
    if evidence.branch_conflicted:
        return _decision(evidence, ContinuationDisposition.NEEDS_DECISION, resume_plan, lease_fields, ("branch.conflicted",))
    if evidence.base_behind:
        return _decision(
            evidence,
            ContinuationDisposition.STALE_EXISTING_WORK,
            resume_plan,
            lease_fields,
            ("branch.base-behind-route-gh-life3",),
            recommended_action="route to the separately governed #1187 branch-refresh path; do not treat base-behind as same-branch HEAD_ADVANCED",
        )

    existing = evidence.existing_execution
    if existing.head_sha != evidence.current_head_sha:
        if not evidence.head_advance_in_scope:
            return _decision(evidence, ContinuationDisposition.SCOPE_DRIFT, resume_plan, lease_fields, ("head.advanced-out-of-scope",))
        return _decision(
            evidence,
            ContinuationDisposition.HEAD_ADVANCED,
            resume_plan,
            lease_fields,
            ("head.advanced-in-scope", "resume-plan.rebind-required"),
            resume_point_override=None,
        )
    if resume_plan is None:
        return _decision(evidence, ContinuationDisposition.STALE_EXISTING_WORK, None, lease_fields, ("resume-plan.unavailable",))
    if (
        resume_plan.repository != existing.repository
        or resume_plan.issue_number != existing.issue_number
        or resume_plan.execution_id != existing.execution_id
    ):
        return _decision(evidence, ContinuationDisposition.NEEDS_DECISION, resume_plan, lease_fields, ("resume-plan.identity-mismatch",))

    classifications = {item.classification for item in resume_plan.stage_decisions}
    if StageClassification.QUARANTINED in classifications:
        return _decision(evidence, ContinuationDisposition.NEEDS_DECISION, resume_plan, lease_fields, ("resume-plan.quarantined",))
    if StageClassification.MANUAL_REVIEW in classifications:
        return _decision(evidence, ContinuationDisposition.NEEDS_DECISION, resume_plan, lease_fields, ("resume-plan.manual-review",))
    if StageClassification.BLOCKED in classifications:
        return _decision(evidence, ContinuationDisposition.NEEDS_DECISION, resume_plan, lease_fields, ("resume-plan.blocked",))
    return _decision(
        evidence,
        ContinuationDisposition.RESUMABLE_EXISTING_WORK,
        resume_plan,
        lease_fields,
        ("existing.resumable", "lease.no-active-conflict"),
    )


def _identity_reason(evidence: ExistingWorkEvidence) -> str | None:
    existing = evidence.existing_execution
    if existing is None:
        return "existing.execution-identity-unavailable"
    if existing.repository != evidence.repository or existing.issue_number != evidence.issue_number:
        return "existing.issue-identity-mismatch"
    if existing.branch != evidence.branch:
        return "existing.branch-identity-mismatch"
    return None


def _classify_lease(
    evidence: ExistingWorkEvidence,
    resume_plan: ResumePlan | None,
    lease_request: PilotLeaseRequest | None,
    lease_observation: HostLocalLeaseObservation | None,
) -> ContinuationDecision | None:
    lease_fields = _lease_fields(lease_observation)
    existing = evidence.existing_execution
    if existing is None:
        return _decision(evidence, ContinuationDisposition.STALE_EXISTING_WORK, resume_plan, lease_fields, ("existing.execution-identity-unavailable",))
    if lease_request is None or lease_observation is None:
        return _decision(evidence, ContinuationDisposition.STALE_EXISTING_WORK, resume_plan, lease_fields, ("lease.current-observation-required",))
    if (
        lease_request.repository != existing.repository
        or lease_request.issue_number != existing.issue_number
        or lease_request.branch != existing.branch
        or lease_request.invocation_id != existing.invocation_id
        or lease_request.source_head_sha != existing.head_sha
    ):
        return _decision(evidence, ContinuationDisposition.NEEDS_DECISION, resume_plan, lease_fields, ("lease.request-identity-mismatch",))

    expected_lease = pilot_lease_identity(lease_request)
    expected_holder = pilot_holder_identity(lease_request)
    if lease_observation.lease_identity != expected_lease:
        return _decision(evidence, ContinuationDisposition.NEEDS_DECISION, resume_plan, lease_fields, ("lease.identity-mismatch",))
    if lease_observation.ambiguous:
        return _decision(evidence, ContinuationDisposition.NEEDS_DECISION, resume_plan, lease_fields, ("lease.ambiguous",))
    if lease_observation.active:
        reason = "lease.active-canonical-holder" if lease_observation.holder_identity == expected_holder else "lease.active-holder-drift"
        return _decision(evidence, ContinuationDisposition.ACTIVE_CONFLICT, resume_plan, lease_fields, (reason,))
    if lease_observation.holder_identity is not None:
        return _decision(evidence, ContinuationDisposition.NEEDS_DECISION, resume_plan, lease_fields, ("lease.inactive-with-holder",))
    return None


def _lease_fields(observation: HostLocalLeaseObservation | None) -> tuple[str | None, str | None, int | None]:
    if observation is None:
        return None, None, None
    return observation.lease_identity, observation.holder_identity, observation.generation


def _decision(
    evidence: ExistingWorkEvidence,
    disposition: ContinuationDisposition,
    resume_plan: ResumePlan | None,
    lease_fields: tuple[str | None, str | None, int | None],
    reasons: tuple[str, ...],
    *,
    recommended_action: str | None = None,
    resume_point_override: str | None | object = ...,
) -> ContinuationDecision:
    existing = evidence.existing_execution
    observed_base = evidence.current_base_sha if existing is None else existing.base_sha
    observed_head = evidence.current_head_sha if existing is None else existing.head_sha
    if resume_point_override is ...:
        resume_point = None if resume_plan is None or resume_plan.resume_point is None else resume_plan.resume_point.value
    else:
        resume_point = resume_point_override
    return ContinuationDecision(
        schema_version=CONTINUATION_SCHEMA_VERSION,
        disposition=disposition,
        repository=evidence.repository,
        issue_number=evidence.issue_number,
        branch=evidence.branch,
        observed_base_sha=observed_base,
        observed_head_sha=observed_head,
        current_base_sha=evidence.current_base_sha,
        current_head_sha=evidence.current_head_sha,
        invocation_id=None if existing is None else existing.invocation_id,
        execution_id=None if existing is None else existing.execution_id,
        candidate_identity=None if existing is None else existing.candidate_identity,
        checkpoint_lineage_identity=None if existing is None else existing.checkpoint_lineage_identity,
        authorization_identity=None if existing is None else existing.authorization_identity,
        executor_identity=None if existing is None else existing.executor_identity,
        scope_identity=None if existing is None else existing.scope_identity,
        resume_plan_id=None if resume_plan is None else resume_plan.plan_id,
        resume_point=resume_point,
        lease_identity=lease_fields[0],
        lease_holder_identity=lease_fields[1],
        lease_generation=lease_fields[2],
        reason_codes=tuple(sorted(set(reasons))),
        recommended_action=recommended_action or _ACTIONS[disposition],
    )


def _bounded_text(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise TypeError(f"{name} must be a non-empty exact string")
    if len(value) > _MAX_TEXT:
        raise ValueError(f"{name} exceeds the bounded length")
    return value


def _sha40(value: object, name: str) -> str:
    if type(value) is not str or _SHA40_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase 40-character SHA")
    return value
