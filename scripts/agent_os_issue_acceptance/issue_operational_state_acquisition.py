"""Canonical acquisition boundary for current IssueOperationalState evidence.

This coordinator reacquires one issue snapshot through an injected read owner,
delegates derived meaning to existing canonical evaluators, validates identity
joins, and builds the canonical IssueOperationalState directly. It owns no
readiness, authorization, lifecycle, dependency, claim, validation, or freshness
authority and performs no I/O beyond the injected read/acquisition callables.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Protocol

from .approval_records import ApprovalApplicabilityResult
from .issue_operational_state import (
    AuthorityProjection, AuthorizationState, DependencyState, FreshnessState,
    IssueOperationalEvidence, IssueOperationalState, IssueState, LifecycleStage,
    PrimaryIssueClaim, ReadinessState, SourceState, TerminalDisposition,
    ValidationState, build_issue_operational_state,
)
from .lifecycle_mutation_guard import LifecycleMutationAdmissionResult
from .merge_authorization import MergeAuthorizationApplicabilityResult
from .readiness import ReadinessOutcome, ReadinessResult, evaluate_issue_readiness

_REPOSITORY_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ISSUE_REVISION_RE = re.compile(r"^github-issue-v1:[0-9a-f]{64}$")
_NOT_APPLICABLE = AuthorityProjection(state=AuthorizationState.NOT_APPLICABLE)
_READINESS_MAP = {
    ReadinessOutcome.READY: ReadinessState.READY,
    ReadinessOutcome.BLOCKED: ReadinessState.BLOCKED,
    ReadinessOutcome.NEEDS_DECISION: ReadinessState.NEEDS_DECISION,
}


@dataclass(frozen=True, slots=True)
class CurrentIssueSnapshot:
    repository: str
    issue_number: int
    body: str
    source_revision: str
    issue_source_revision: str
    observed_at: str
    evidence_ids: tuple[str, ...]
    source_state: SourceState
    issue_state: IssueState
    lifecycle_stage: LifecycleStage
    terminal_disposition: TerminalDisposition
    observed_labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.repository) is not str or not self.repository:
            raise ValueError("repository must be a non-empty built-in string")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise TypeError("issue_number must be a positive built-in integer")
        if type(self.body) is not str:
            raise TypeError("body must be a built-in string")
        if type(self.source_revision) is not str or not _REPOSITORY_SHA_RE.fullmatch(self.source_revision):
            raise ValueError("source_revision must be the lowercase 40-character repository SHA")
        if type(self.issue_source_revision) is not str or not _ISSUE_REVISION_RE.fullmatch(self.issue_source_revision):
            raise ValueError("issue_source_revision must use github-issue-v1:<64 lowercase hex>")
        if type(self.evidence_ids) is not tuple:
            raise TypeError("evidence_ids must be an exact tuple")
        if self.issue_source_revision not in self.evidence_ids:
            raise ValueError("issue_source_revision must be preserved in evidence_ids")
        if type(self.observed_labels) is not tuple:
            raise TypeError("observed_labels must be an exact tuple")
        for name, enum_type in (
            ("source_state", SourceState), ("issue_state", IssueState),
            ("lifecycle_stage", LifecycleStage), ("terminal_disposition", TerminalDisposition),
        ):
            if type(getattr(self, name)) is not enum_type:
                raise TypeError(f"{name} must be exact {enum_type.__name__}")


class CurrentIssueSnapshotReader(Protocol):
    def read_current_issue(self, repository: str, issue_number: int) -> CurrentIssueSnapshot: ...


@dataclass(frozen=True, slots=True)
class AcquiredIssueOperationalEvidence:
    snapshot: CurrentIssueSnapshot
    readiness_result: ReadinessResult
    approval_applicability: ApprovalApplicabilityResult
    dependency_state: DependencyState
    primary_claims: tuple[PrimaryIssueClaim, ...]
    validation_state: ValidationState
    freshness_state: FreshnessState
    operational_state: IssueOperationalState


ApprovalAcquirer = Callable[[CurrentIssueSnapshot], ApprovalApplicabilityResult]
DependencyAcquirer = Callable[[CurrentIssueSnapshot], DependencyState]
ClaimAcquirer = Callable[[CurrentIssueSnapshot], tuple[PrimaryIssueClaim, ...]]
ValidationAcquirer = Callable[[CurrentIssueSnapshot], ValidationState]
FreshnessAcquirer = Callable[[CurrentIssueSnapshot], FreshnessState]
MergeAcquirer = Callable[[CurrentIssueSnapshot], MergeAuthorizationApplicabilityResult | None]
LifecycleAcquirer = Callable[[CurrentIssueSnapshot], LifecycleMutationAdmissionResult | None]
AuthorityAcquirer = Callable[[CurrentIssueSnapshot], AuthorityProjection]


def _admission_projection(admission: LifecycleMutationAdmissionResult | None) -> AuthorityProjection:
    return _NOT_APPLICABLE if admission is None else AuthorityProjection.from_lifecycle_admission(admission)


def _merge_projection(applicability: MergeAuthorizationApplicabilityResult | None) -> AuthorityProjection:
    return _NOT_APPLICABLE if applicability is None else AuthorityProjection.from_merge_authorization_applicability(applicability)


def acquire_issue_operational_state(
    *, repository: str, issue_number: int, issue_reader: CurrentIssueSnapshotReader,
    approval_acquirer: ApprovalAcquirer, dependency_acquirer: DependencyAcquirer,
    claim_acquirer: ClaimAcquirer, validation_acquirer: ValidationAcquirer,
    freshness_acquirer: FreshnessAcquirer, merge_acquirer: MergeAcquirer | None = None,
    ready_for_review_acquirer: LifecycleAcquirer | None = None,
    closure_acquirer: LifecycleAcquirer | None = None,
    execution_authorization_acquirer: AuthorityAcquirer | None = None,
    external_write_authorization_acquirer: AuthorityAcquirer | None = None,
) -> AcquiredIssueOperationalEvidence:
    if type(repository) is not str or not repository or "/" not in repository:
        raise ValueError("repository must use owner/name form")
    if type(issue_number) is not int or issue_number < 1:
        raise TypeError("issue_number must be a positive built-in integer")
    if issue_reader is None:
        raise TypeError("issue_reader is required")

    snapshot = issue_reader.read_current_issue(repository, issue_number)
    if type(snapshot) is not CurrentIssueSnapshot:
        raise TypeError("issue_reader must return exact CurrentIssueSnapshot")
    snapshot.__post_init__()
    if snapshot.repository.casefold() != repository.casefold():
        raise ValueError("current issue snapshot repository identity mismatch")
    if snapshot.issue_number != issue_number:
        raise ValueError("current issue snapshot issue identity mismatch")

    dependency_state = dependency_acquirer(snapshot)
    validation_state = validation_acquirer(snapshot)
    freshness_state = freshness_acquirer(snapshot)
    primary_claims = claim_acquirer(snapshot)
    if type(dependency_state) is not DependencyState:
        raise TypeError("dependency_acquirer must return exact DependencyState")
    if type(validation_state) is not ValidationState:
        raise TypeError("validation_acquirer must return exact ValidationState")
    if type(freshness_state) is not FreshnessState:
        raise TypeError("freshness_acquirer must return exact FreshnessState")
    if type(primary_claims) is not tuple or any(type(claim) is not PrimaryIssueClaim for claim in primary_claims):
        raise TypeError("claim_acquirer must return tuple[PrimaryIssueClaim, ...]")

    readiness_result = evaluate_issue_readiness(
        snapshot.body,
        dependency_blocked=dependency_state is DependencyState.BLOCKED,
        validation_pending=validation_state is ValidationState.PENDING,
    )
    approval_applicability = approval_acquirer(snapshot)
    if type(approval_applicability) is not ApprovalApplicabilityResult:
        raise TypeError("approval_acquirer must return exact ApprovalApplicabilityResult")
    try:
        readiness = _READINESS_MAP[readiness_result.outcome]
    except KeyError as exc:
        raise ValueError("unsupported readiness outcome") from exc

    merge_applicability = merge_acquirer(snapshot) if merge_acquirer else None
    ready_admission = ready_for_review_acquirer(snapshot) if ready_for_review_acquirer else None
    closure_admission = closure_acquirer(snapshot) if closure_acquirer else None
    if ready_admission is not None and (
        type(ready_admission) is not LifecycleMutationAdmissionResult
        or ready_admission.requested_mutation != "mark-ready"
    ):
        raise ValueError("ready_for_review_acquirer must return mark-ready admission or None")
    if closure_admission is not None and (
        type(closure_admission) is not LifecycleMutationAdmissionResult
        or closure_admission.requested_mutation != "close-issue"
    ):
        raise ValueError("closure_acquirer must return close-issue admission or None")

    execution = _NOT_APPLICABLE
    if execution_authorization_acquirer:
        execution = execution_authorization_acquirer(snapshot)
        if type(execution) is not AuthorityProjection:
            raise TypeError("execution authorization acquirer must return exact AuthorityProjection")
    external_write = _NOT_APPLICABLE
    if external_write_authorization_acquirer:
        external_write = external_write_authorization_acquirer(snapshot)
        if type(external_write) is not AuthorityProjection:
            raise TypeError("external-write authorization acquirer must return exact AuthorityProjection")

    state = build_issue_operational_state(IssueOperationalEvidence(
        repository=snapshot.repository,
        issue_number=snapshot.issue_number,
        source_revision=snapshot.source_revision,
        observed_at=snapshot.observed_at,
        evidence_ids=snapshot.evidence_ids,
        source_state=snapshot.source_state,
        issue_state=snapshot.issue_state,
        lifecycle_stage=snapshot.lifecycle_stage,
        terminal_disposition=snapshot.terminal_disposition,
        readiness=readiness,
        implementation_authorization=AuthorityProjection.from_approval_applicability(approval_applicability),
        ready_for_review_authorization=_admission_projection(ready_admission),
        execution_authorization=execution,
        merge_authorization=_merge_projection(merge_applicability),
        closure_authorization=_admission_projection(closure_admission),
        external_write_authorization=external_write,
        dependency_state=dependency_state,
        primary_claims=primary_claims,
        validation_state=validation_state,
        freshness_state=freshness_state,
        observed_labels=snapshot.observed_labels,
    ))
    return AcquiredIssueOperationalEvidence(
        snapshot=snapshot, readiness_result=readiness_result,
        approval_applicability=approval_applicability, dependency_state=dependency_state,
        primary_claims=primary_claims, validation_state=validation_state,
        freshness_state=freshness_state, operational_state=state,
    )
