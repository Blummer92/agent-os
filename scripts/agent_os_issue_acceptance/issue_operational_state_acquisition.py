"""Canonical acquisition boundary for real-issue IssueOperationalState production.

This reporting-domain coordinator owns no readiness, authorization, lifecycle,
dependency, claim, validation, or freshness semantics. It reacquires one current
issue snapshot through an injected read owner, delegates every derived meaning to
its existing canonical evaluator/owner, validates exact identity joins, and then
invokes the unchanged #1441 producer exactly once.

The module creates no GitHub client, performs no mutation, persists nothing, and
never treats issue prose or labels as authorization/dependency/validation truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .approval_records import ApprovalApplicabilityResult
from .issue_operational_state import (
    AuthorityProjection,
    DependencyState,
    FreshnessState,
    IssueOperationalState,
    IssueState,
    LifecycleStage,
    PrimaryIssueClaim,
    SourceState,
    TerminalDisposition,
    ValidationState,
)
from .issue_operational_state_producer import (
    IssueOperationalStateProductionEvidence,
    produce_issue_operational_state,
)
from .lifecycle_mutation_guard import LifecycleMutationAdmissionResult
from .merge_authorization import MergeAuthorizationApplicabilityResult
from .readiness import ReadinessResult, evaluate_issue_readiness


@dataclass(frozen=True, slots=True)
class CurrentIssueSnapshot:
    """Bounded current issue/source facts supplied by the existing read owner."""

    repository: str
    issue_number: int
    body: str
    source_revision: str
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
        if type(self.evidence_ids) is not tuple:
            raise TypeError("evidence_ids must be an exact tuple")
        if type(self.observed_labels) is not tuple:
            raise TypeError("observed_labels must be an exact tuple")
        for name, enum_type in (
            ("source_state", SourceState),
            ("issue_state", IssueState),
            ("lifecycle_stage", LifecycleStage),
            ("terminal_disposition", TerminalDisposition),
        ):
            if type(getattr(self, name)) is not enum_type:
                raise TypeError(f"{name} must be exact {enum_type.__name__}")


class CurrentIssueSnapshotReader(Protocol):
    def read_current_issue(self, repository: str, issue_number: int) -> CurrentIssueSnapshot:
        """Return one exact current issue snapshot or raise on unavailable/ambiguous input."""


@dataclass(frozen=True, slots=True)
class AcquiredIssueOperationalEvidence:
    """Exact current evidence bundle returned with the produced state for audit."""

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


def acquire_issue_operational_state(
    *,
    repository: str,
    issue_number: int,
    issue_reader: CurrentIssueSnapshotReader,
    approval_acquirer: ApprovalAcquirer,
    dependency_acquirer: DependencyAcquirer,
    claim_acquirer: ClaimAcquirer,
    validation_acquirer: ValidationAcquirer,
    freshness_acquirer: FreshnessAcquirer,
    merge_acquirer: MergeAcquirer | None = None,
    ready_for_review_acquirer: LifecycleAcquirer | None = None,
    closure_acquirer: LifecycleAcquirer | None = None,
    execution_authorization_acquirer: AuthorityAcquirer | None = None,
    external_write_authorization_acquirer: AuthorityAcquirer | None = None,
) -> AcquiredIssueOperationalEvidence:
    """Reacquire canonical current evidence and invoke #1441 once.

    The injected acquisition functions are adapters to the already-owned canonical
    evidence producers. This function deliberately does not inspect issue prose or
    labels to derive authorization, dependencies, claims, validation, or freshness.
    """

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
    if type(dependency_state) is not DependencyState:
        raise TypeError("dependency_acquirer must return exact DependencyState")
    validation_state = validation_acquirer(snapshot)
    if type(validation_state) is not ValidationState:
        raise TypeError("validation_acquirer must return exact ValidationState")
    freshness_state = freshness_acquirer(snapshot)
    if type(freshness_state) is not FreshnessState:
        raise TypeError("freshness_acquirer must return exact FreshnessState")
    primary_claims = claim_acquirer(snapshot)
    if type(primary_claims) is not tuple or any(
        type(claim) is not PrimaryIssueClaim for claim in primary_claims
    ):
        raise TypeError("claim_acquirer must return tuple[PrimaryIssueClaim, ...]")

    readiness_result = evaluate_issue_readiness(
        snapshot.body,
        dependency_blocked=dependency_state is DependencyState.BLOCKED,
        validation_pending=validation_state is ValidationState.PENDING,
    )
    approval_applicability = approval_acquirer(snapshot)
    if type(approval_applicability) is not ApprovalApplicabilityResult:
        raise TypeError("approval_acquirer must return exact ApprovalApplicabilityResult")

    merge_applicability = merge_acquirer(snapshot) if merge_acquirer is not None else None
    ready_admission = (
        ready_for_review_acquirer(snapshot)
        if ready_for_review_acquirer is not None
        else None
    )
    closure_admission = closure_acquirer(snapshot) if closure_acquirer is not None else None

    optional_authorities: dict[str, AuthorityProjection] = {}
    if execution_authorization_acquirer is not None:
        projection = execution_authorization_acquirer(snapshot)
        if type(projection) is not AuthorityProjection:
            raise TypeError("execution authorization acquirer must return exact AuthorityProjection")
        optional_authorities["execution_authorization"] = projection
    if external_write_authorization_acquirer is not None:
        projection = external_write_authorization_acquirer(snapshot)
        if type(projection) is not AuthorityProjection:
            raise TypeError("external-write authorization acquirer must return exact AuthorityProjection")
        optional_authorities["external_write_authorization"] = projection

    production_evidence = IssueOperationalStateProductionEvidence(
        repository=snapshot.repository,
        issue_number=snapshot.issue_number,
        source_revision=snapshot.source_revision,
        observed_at=snapshot.observed_at,
        evidence_ids=snapshot.evidence_ids,
        source_state=snapshot.source_state,
        issue_state=snapshot.issue_state,
        lifecycle_stage=snapshot.lifecycle_stage,
        terminal_disposition=snapshot.terminal_disposition,
        readiness_result=readiness_result,
        approval_applicability=approval_applicability,
        merge_applicability=merge_applicability,
        ready_for_review_admission=ready_admission,
        closure_admission=closure_admission,
        dependency_state=dependency_state,
        primary_claims=primary_claims,
        validation_state=validation_state,
        freshness_state=freshness_state,
        observed_labels=snapshot.observed_labels,
        **optional_authorities,
    )
    state = produce_issue_operational_state(production_evidence)
    return AcquiredIssueOperationalEvidence(
        snapshot=snapshot,
        readiness_result=readiness_result,
        approval_applicability=approval_applicability,
        dependency_state=dependency_state,
        primary_claims=primary_claims,
        validation_state=validation_state,
        freshness_state=freshness_state,
        operational_state=state,
    )
