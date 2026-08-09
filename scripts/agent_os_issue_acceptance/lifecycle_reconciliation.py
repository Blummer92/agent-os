"""Deterministic, pure-local lifecycle reconciliation planning for Agent OS."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .issue_operational_state import (
    AuthorizationState, ClaimState, DependencyState, FreshnessState,
    IssueOperationalState, IssueState, OperationalOutcome, PrimaryPrState,
    ReadinessState, TerminalDisposition,
)
from .lifecycle_mutation_guard import (
    AdmissionStatus, LifecycleMutationAdmissionResult, LifecycleStateSnapshot,
)

SCHEMA_NAME = "agent-os-lifecycle-reconciliation"
SCHEMA_VERSION = "1.0"
MAX_ITEMS = 64
MAX_BYTES = 64 * 1024


class ReconciliationOutcome(str, Enum):
    CONSISTENT = "consistent"
    REQUIRED = "reconciliation-required"
    NEEDS_DECISION = "needs-decision"


class ActionCategory(str, Enum):
    OBSERVATION = "observation"
    PROJECTION_REPAIR = "projection-repair"
    GOVERNED_MUTATION = "governed-lifecycle-mutation"
    MERGE = "merge"
    MANUAL_DECISION = "manual-decision"


class ProjectionSurface(str, Enum):
    ISSUE_BODY = "issue-body"
    ROADMAP = "roadmap"
    PR_DESCRIPTION = "pr-description"


class PullRequestState(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    MERGED = "merged"
    CLOSED_SUPERSEDED = "closed-superseded"


class DependencyDisposition(str, Enum):
    INCOMPLETE = "incomplete"
    COMPLETED = "completed"
    NOT_PLANNED = "not-planned"
    DUPLICATE = "duplicate"
    SUPERSEDED = "superseded"


REASON_CODES = frozenset({
    "source.identity-mismatch", "source.canonical-conflict",
    "source.lifecycle-snapshot-conflict", "source.conflicting-dependency-evidence",
    "source.conflicting-projection-evidence", "source.conflicting-admission-evidence",
    "claim.multiple-primary", "claim.closed-pr-projected-active",
    "projection.readiness-stale", "projection.completed-dependency-blocker",
    "projection.pr-description-head-stale", "projection.pr-state-stale",
    "validation.exact-head-stale", "lifecycle.status-label-stale",
    "lifecycle.merged-pr-open-issue", "lifecycle.closed-without-terminal-evidence",
    "authorization.lifecycle-admission-required", "authorization.closure-required",
})


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _id(prefix: str, value: object) -> str:
    data = prefix.encode() + b"\0" + _canonical(value).encode()
    return f"{prefix}:{hashlib.sha256(data).hexdigest()}"


def _tuple(value: object, name: str) -> tuple:
    if type(value) is not tuple or len(value) > MAX_ITEMS:
        raise TypeError(f"{name} must be a bounded exact tuple")
    return value


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise TypeError(f"{name} must be a positive built-in integer")
    return value


@dataclass(frozen=True, slots=True)
class DependencyEvidence:
    issue_number: int
    disposition: DependencyDisposition
    evidence_id: str

    def __post_init__(self) -> None:
        _positive(self.issue_number, "issue_number")
        if type(self.disposition) is not DependencyDisposition or type(self.evidence_id) is not str:
            raise TypeError("invalid dependency evidence")


@dataclass(frozen=True, slots=True)
class PullRequestEvidence:
    pull_request_number: int
    branch: str
    head_sha: str
    state: PullRequestState
    evidence_id: str

    def __post_init__(self) -> None:
        _positive(self.pull_request_number, "pull_request_number")
        if type(self.state) is not PullRequestState or any(type(v) is not str or not v for v in (self.branch, self.head_sha, self.evidence_id)):
            raise TypeError("invalid pull request evidence")
        if len(self.head_sha) != 40 or any(ch not in "0123456789abcdef" for ch in self.head_sha):
            raise ValueError("head_sha must be lowercase SHA-1")


@dataclass(frozen=True, slots=True)
class ProjectionEvidence:
    surface: ProjectionSurface
    evidence_id: str
    readiness: ReadinessState | None = None
    blocked_dependencies: tuple[int, ...] = ()
    pull_request_number: int | None = None
    pull_request_state: PullRequestState | None = None
    head_sha: str | None = None

    def __post_init__(self) -> None:
        if type(self.surface) is not ProjectionSurface or type(self.evidence_id) is not str:
            raise TypeError("invalid projection evidence")
        deps = _tuple(self.blocked_dependencies, "blocked_dependencies")
        if any(type(v) is not int or v < 1 for v in deps) or tuple(sorted(set(deps))) != deps:
            raise ValueError("blocked_dependencies must be sorted unique positive integers")


@dataclass(frozen=True, slots=True)
class ExactHeadEvidence:
    evidence_id: str
    tested_head_sha: str


@dataclass(frozen=True, slots=True)
class LifecycleReconciliationInput:
    repository: str
    issue_number: int
    operational_state: IssueOperationalState
    lifecycle_snapshot: LifecycleStateSnapshot | None = None
    current_pull_request: PullRequestEvidence | None = None
    dependencies: tuple[DependencyEvidence, ...] = ()
    projections: tuple[ProjectionEvidence, ...] = ()
    exact_head_evidence: tuple[ExactHeadEvidence, ...] = ()
    admissions: tuple[LifecycleMutationAdmissionResult, ...] = ()
    input_id: str = ""
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _positive(self.issue_number, "issue_number")
        if type(self.repository) is not str or type(self.operational_state) is not IssueOperationalState:
            raise TypeError("invalid reconciliation identity/state")
        if self.lifecycle_snapshot is not None and type(self.lifecycle_snapshot) is not LifecycleStateSnapshot:
            raise TypeError("invalid lifecycle snapshot")
        if self.current_pull_request is not None and type(self.current_pull_request) is not PullRequestEvidence:
            raise TypeError("invalid current pull request")
        for name, kind in (("dependencies", DependencyEvidence), ("projections", ProjectionEvidence), ("exact_head_evidence", ExactHeadEvidence), ("admissions", LifecycleMutationAdmissionResult)):
            if any(type(v) is not kind for v in _tuple(getattr(self, name), name)):
                raise TypeError(f"invalid {name}")
        expected = _id("lifecycle-reconciliation-input", self.payload())
        if self.input_id and self.input_id != expected:
            raise ValueError("input_id does not match content")
        object.__setattr__(self, "input_id", expected)
        if len(_canonical(self.to_dict()).encode()) > MAX_BYTES:
            raise ValueError("input exceeds serialized bound")

    def payload(self) -> dict[str, object]:
        pr = self.current_pull_request
        return {
            "repository": self.repository, "issue_number": self.issue_number,
            "operational_state_id": self.operational_state.state_id,
            "lifecycle_snapshot_id": self.lifecycle_snapshot.snapshot_id if self.lifecycle_snapshot else None,
            "current_pr": None if pr is None else [pr.pull_request_number, pr.branch, pr.head_sha, pr.state.value, pr.evidence_id],
            "dependencies": sorted((v.issue_number, v.disposition.value, v.evidence_id) for v in self.dependencies),
            "projections": sorted((v.surface.value, v.evidence_id, v.readiness.value if v.readiness else None, v.blocked_dependencies, v.pull_request_number, v.pull_request_state.value if v.pull_request_state else None, v.head_sha) for v in self.projections),
            "exact_heads": sorted((v.evidence_id, v.tested_head_sha) for v in self.exact_head_evidence),
            "admission_ids": sorted(v.result_id for v in self.admissions), "side_effects_performed": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.payload(), "input_id": self.input_id}


@dataclass(frozen=True, slots=True)
class ReconciliationAction:
    category: ActionCategory
    reason_code: str
    surface: str
    observed: str
    expected: str
    required_mutation: str | None = None
    authorization_id: str | None = None
    admission_result_id: str | None = None
    expected_state_guards: tuple[str, ...] = ()
    action_id: str = ""

    def __post_init__(self) -> None:
        if self.reason_code not in REASON_CODES or type(self.category) is not ActionCategory:
            raise ValueError("invalid reconciliation action")
        guards = tuple(sorted(set(_tuple(self.expected_state_guards, "expected_state_guards"))))
        object.__setattr__(self, "expected_state_guards", guards)
        expected = _id("lifecycle-reconciliation-action", self.payload())
        if self.action_id and self.action_id != expected:
            raise ValueError("action_id does not match content")
        object.__setattr__(self, "action_id", expected)

    def payload(self) -> dict[str, object]:
        return {"category": self.category.value, "reason_code": self.reason_code, "surface": self.surface, "observed": self.observed, "expected": self.expected, "required_mutation": self.required_mutation, "authorization_id": self.authorization_id, "admission_result_id": self.admission_result_id, "expected_state_guards": self.expected_state_guards}

    def to_dict(self) -> dict[str, object]:
        return {**self.payload(), "action_id": self.action_id}


@dataclass(frozen=True, slots=True)
class LifecycleReconciliationResult:
    repository: str
    issue_number: int
    input_id: str
    operational_state_id: str
    lifecycle_snapshot_id: str | None
    outcome: ReconciliationOutcome
    reason_codes: tuple[str, ...]
    actions: tuple[ReconciliationAction, ...]
    implementation_authorization: AuthorizationState
    ready_for_review_authorization: AuthorizationState
    execution_authorization: AuthorizationState
    merge_authorization: AuthorizationState
    closure_authorization: AuthorizationState
    external_write_authorization: AuthorizationState
    result_id: str = ""
    schema_name: Literal["agent-os-lifecycle-reconciliation"] = SCHEMA_NAME
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        reasons = tuple(sorted(set(_tuple(self.reason_codes, "reason_codes"))))
        if any(v not in REASON_CODES for v in reasons):
            raise ValueError("unsupported reason code")
        actions = tuple(sorted(_tuple(self.actions, "actions"), key=lambda v: v.action_id))
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "actions", actions)
        expected = _id("lifecycle-reconciliation-result", self.payload())
        if self.result_id and self.result_id != expected:
            raise ValueError("result_id does not match content")
        object.__setattr__(self, "result_id", expected)

    def payload(self) -> dict[str, object]:
        return {"schema_name": self.schema_name, "schema_version": self.schema_version, "repository": self.repository, "issue_number": self.issue_number, "input_id": self.input_id, "operational_state_id": self.operational_state_id, "lifecycle_snapshot_id": self.lifecycle_snapshot_id, "outcome": self.outcome.value, "reason_codes": self.reason_codes, "actions": [v.to_dict() for v in self.actions], "implementation_authorization": self.implementation_authorization.value, "ready_for_review_authorization": self.ready_for_review_authorization.value, "execution_authorization": self.execution_authorization.value, "merge_authorization": self.merge_authorization.value, "closure_authorization": self.closure_authorization.value, "external_write_authorization": self.external_write_authorization.value, "side_effects_performed": False}

    def to_dict(self) -> dict[str, object]:
        return {**self.payload(), "result_id": self.result_id}


def _guards(e: LifecycleReconciliationInput) -> tuple[str, ...]:
    values = [f"operational-state-id={e.operational_state.state_id}", f"issue-state={e.operational_state.issue_state.value}"]
    if e.lifecycle_snapshot:
        values += [f"lifecycle-snapshot-id={e.lifecycle_snapshot.snapshot_id}", f"lifecycle-labels={','.join(e.lifecycle_snapshot.lifecycle_labels)}"]
    if e.current_pull_request:
        p = e.current_pull_request
        values += [f"pr-number={p.pull_request_number}", f"pr-head={p.head_sha}", f"pr-state={p.state.value}"]
    return tuple(values)


def _admission(e: LifecycleReconciliationInput, mutation: str) -> LifecycleMutationAdmissionResult | None:
    matches = [v for v in e.admissions if v.requested_mutation == mutation]
    if len(matches) != 1 or e.lifecycle_snapshot is None:
        return None
    value = matches[0]
    return value if value.admitted and value.status is AdmissionStatus.ADMITTED and value.snapshot_id == e.lifecycle_snapshot.snapshot_id else None


def _repair(reason: str, surface: str, observed: str, expected: str) -> ReconciliationAction:
    return ReconciliationAction(ActionCategory.PROJECTION_REPAIR, reason, surface, observed, expected)


def reconcile_lifecycle(e: LifecycleReconciliationInput) -> LifecycleReconciliationResult:
    if type(e) is not LifecycleReconciliationInput:
        raise TypeError("evidence must be LifecycleReconciliationInput")
    s, reasons, actions, decision = e.operational_state, set(), [], False
    if s.repository != e.repository or s.issue_number != e.issue_number:
        reasons.add("source.identity-mismatch"); decision = True
    if s.freshness_state is FreshnessState.STALE or s.outcome in {OperationalOutcome.CONFLICTING, OperationalOutcome.INVALID} or s.dependency_state is DependencyState.UNKNOWN or s.readiness is ReadinessState.NEEDS_DECISION:
        reasons.add("source.canonical-conflict"); decision = True
    if s.claim_state is ClaimState.CONFLICTING:
        reasons.add("claim.multiple-primary"); decision = True
    snap = e.lifecycle_snapshot
    if snap and (snap.repository != e.repository or snap.issue_number != e.issue_number):
        reasons.add("source.lifecycle-snapshot-conflict"); decision = True

    deps: dict[int, DependencyDisposition] = {}
    for v in e.dependencies:
        if v.issue_number in deps and deps[v.issue_number] is not v.disposition:
            reasons.add("source.conflicting-dependency-evidence"); decision = True
        deps[v.issue_number] = v.disposition
    surfaces = [v.surface for v in e.projections]
    if len(set(surfaces)) != len(surfaces):
        reasons.add("source.conflicting-projection-evidence"); decision = True
    mutations = [v.requested_mutation for v in e.admissions]
    if len(set(mutations)) != len(mutations):
        reasons.add("source.conflicting-admission-evidence"); decision = True

    pr = e.current_pull_request
    if pr:
        expected = {PrimaryPrState.DRAFT: PullRequestState.DRAFT, PrimaryPrState.READY: PullRequestState.READY, PrimaryPrState.MERGED: PullRequestState.MERGED}.get(s.primary_pr_state)
        if (s.primary_pr_numbers and pr.pull_request_number not in s.primary_pr_numbers) or (expected and pr.state is not expected):
            reasons.add("source.canonical-conflict"); decision = True
        if snap:
            snap_state = "none" if pr.state is PullRequestState.CLOSED_SUPERSEDED else ("draft" if pr.state is PullRequestState.DRAFT else "ready")
            if (snap.pull_request_number not in {None, pr.pull_request_number} or snap.source_head not in {None, pr.head_sha} or snap.pr_state != snap_state or snap.merged != (pr.state is PullRequestState.MERGED)):
                reasons.add("source.lifecycle-snapshot-conflict"); decision = True

    terminal_deps = {n for n, d in deps.items() if d is not DependencyDisposition.INCOMPLETE}
    for p in e.projections:
        stale = tuple(n for n in p.blocked_dependencies if n in terminal_deps)
        if stale:
            reasons.add("projection.completed-dependency-blocker"); actions.append(_repair("projection.completed-dependency-blocker", p.surface.value, f"blocked={','.join(map(str, stale))}", "remove terminal blockers"))
        if p.readiness is not None and p.readiness is not s.readiness:
            reasons.add("projection.readiness-stale"); actions.append(_repair("projection.readiness-stale", p.surface.value, p.readiness.value, s.readiness.value))
        if pr and p.pull_request_number == pr.pull_request_number:
            if p.head_sha and p.head_sha != pr.head_sha:
                reasons.add("projection.pr-description-head-stale"); actions.append(_repair("projection.pr-description-head-stale", p.surface.value, p.head_sha, pr.head_sha))
            if p.pull_request_state and p.pull_request_state is not pr.state:
                r = "claim.closed-pr-projected-active" if pr.state is PullRequestState.CLOSED_SUPERSEDED else "projection.pr-state-stale"
                reasons.add(r); actions.append(_repair(r, p.surface.value, p.pull_request_state.value, pr.state.value))
    if pr:
        for v in e.exact_head_evidence:
            if v.tested_head_sha != pr.head_sha:
                reasons.add("validation.exact-head-stale"); actions.append(ReconciliationAction(ActionCategory.OBSERVATION, "validation.exact-head-stale", "validation", v.tested_head_sha, pr.head_sha))

    if snap and s.issue_state is IssueState.OPEN:
        desired = {ReadinessState.READY: "status:ready", ReadinessState.BLOCKED: "status:blocked", ReadinessState.NEEDS_DECISION: "status:needs-decision"}.get(s.readiness)
        current = tuple(v for v in snap.lifecycle_labels if v.startswith("status:"))
        if desired and current != (desired,):
            reasons.add("lifecycle.status-label-stale")
            adm = _admission(e, "replace-lifecycle-labels")
            if adm is None: reasons.add("authorization.lifecycle-admission-required")
            actions.append(ReconciliationAction(ActionCategory.GOVERNED_MUTATION, "lifecycle.status-label-stale", "lifecycle-labels", ",".join(current) or "none", desired, "replace-lifecycle-labels", admission_result_id=adm.result_id if adm else None, expected_state_guards=_guards(e)))

    merged_open = s.issue_state is IssueState.OPEN and (s.primary_pr_state is PrimaryPrState.MERGED or (pr and pr.state is PullRequestState.MERGED))
    if merged_open:
        reasons.add("lifecycle.merged-pr-open-issue")
        adm = _admission(e, "close-issue")
        auth = s.closure_authorization.evidence_id if s.closure_authorization.state is AuthorizationState.AUTHORIZED else None
        if auth is None: reasons.add("authorization.closure-required")
        if adm is None: reasons.add("authorization.lifecycle-admission-required")
        actions.append(ReconciliationAction(ActionCategory.GOVERNED_MUTATION, "lifecycle.merged-pr-open-issue", "issue-state", "open", "closed", "close-issue", auth, adm.result_id if adm else None, _guards(e)))
    if s.issue_state is IssueState.CLOSED and s.terminal_disposition is TerminalDisposition.NONE and s.primary_pr_state is not PrimaryPrState.MERGED:
        reasons.add("lifecycle.closed-without-terminal-evidence"); decision = True

    if decision:
        controlling = next(v for v in sorted(reasons) if v.startswith("source.") or v in {"claim.multiple-primary", "lifecycle.closed-without-terminal-evidence"})
        actions = [ReconciliationAction(ActionCategory.MANUAL_DECISION, controlling, "manual-decision", "conflicting or incomplete canonical evidence", "resolve canonical evidence")]
        outcome = ReconciliationOutcome.NEEDS_DECISION
    else:
        outcome = ReconciliationOutcome.REQUIRED if actions else ReconciliationOutcome.CONSISTENT
    return LifecycleReconciliationResult(e.repository, e.issue_number, e.input_id, s.state_id, snap.snapshot_id if snap else None, outcome, tuple(reasons), tuple(actions), s.implementation_authorization.state, s.ready_for_review_authorization.state, s.execution_authorization.state, s.merge_authorization.state, s.closure_authorization.state, s.external_write_authorization.state)


def serialize_lifecycle_reconciliation_input(value: LifecycleReconciliationInput) -> str:
    return _canonical(value.to_dict())


def serialize_lifecycle_reconciliation_result(value: LifecycleReconciliationResult) -> str:
    return _canonical(value.to_dict())
