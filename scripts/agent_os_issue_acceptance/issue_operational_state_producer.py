"""Canonical production composition boundary for #1441 operational state.

This module deliberately owns no operational-state, readiness, authorization,
or lifecycle semantics. It accepts already-owned canonical Agent OS evidence
for one exact issue identity -- the existing #862 readiness evaluation, the
existing approval/merge/lifecycle-mutation authorization applicability
results, and directly supplied source/lifecycle/dependency/claim/validation/
freshness evidence that the caller has already verified against its owning
contract -- and adapts that evidence into ``IssueOperationalEvidence`` before
invoking the existing, unchanged ``build_issue_operational_state``.

It performs no GitHub, network, filesystem, subprocess, Scheduler, provider,
Cloud Build, GCP, or Notion I/O; creates no authorization; evaluates no
readiness, lifecycle, or dependency semantics; and persists nothing. External
callers remain responsible for reacquiring current evidence through the
owning contracts (``readiness.py``, ``approval_records.py``,
``merge_authorization.py``, ``lifecycle_mutation_guard.py``, and the source of
truth for issue/PR/dependency/validation/freshness facts) before invoking
this producer.

``execution_authorization`` and ``external_write_authorization`` have no
dedicated evidence-producing evaluator anywhere in this package today. The
``IssueOperationalEvidence``/``AuthorityProjection`` contract already defines
``AuthorizationState.NOT_APPLICABLE`` for exactly this case -- an
authorization dimension that does not apply to the issue being projected --
so this producer defaults those two dimensions to ``NOT_APPLICABLE`` unless
the caller supplies an already-produced ``AuthorityProjection`` for one
because the issue does request an execution or external-write mutation.
Supplying ``NOT_APPLICABLE`` by default is using the existing contract, not
inventing a new one.
"""

from __future__ import annotations

from dataclasses import dataclass

from .approval_records import ApprovalApplicabilityResult
from .lifecycle_mutation_guard import LifecycleMutationAdmissionResult
from .merge_authorization import MergeAuthorizationApplicabilityResult
from .readiness import ReadinessOutcome, ReadinessResult
from .issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueOperationalState,
    IssueState,
    LifecycleStage,
    PrimaryIssueClaim,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)

_READINESS_MAP = {
    ReadinessOutcome.READY: ReadinessState.READY,
    ReadinessOutcome.BLOCKED: ReadinessState.BLOCKED,
    ReadinessOutcome.NEEDS_DECISION: ReadinessState.NEEDS_DECISION,
}

_NOT_APPLICABLE = AuthorityProjection(state=AuthorizationState.NOT_APPLICABLE)


@dataclass(frozen=True, slots=True)
class IssueOperationalStateProductionEvidence:
    """Already-owned canonical evidence needed for one #1441 production call.

    Every field that has an existing canonical evidence-producing type in this
    package is accepted as that exact type and adapted without re-evaluation:
    ``readiness_result`` (``readiness.evaluate_issue_readiness*``),
    ``approval_applicability`` (``approval_records.evaluate_approval_applicability``,
    projected onto ``implementation_authorization``), ``merge_applicability``
    (``merge_authorization.evaluate_merge_authorization_applicability``,
    projected onto ``merge_authorization``), and ``ready_for_review_admission``
    / ``closure_admission`` (``lifecycle_mutation_guard.evaluate_lifecycle_mutation``
    for the ``mark-ready`` and ``close-issue`` mutations respectively,
    projected onto ``ready_for_review_authorization`` and
    ``closure_authorization``).

    Fields with no dedicated object producer in this package -- terminal
    lifecycle/source/dependency/claim/validation/freshness facts, and the
    ``execution``/``external-write`` authorization dimensions when an issue
    does request one of those mutations -- are supplied directly, already
    verified by the caller against their owning contract (issue/PR source of
    truth, dependency graph, validation run, and observation staleness
    check). This boundary does not re-derive any of them.
    """

    repository: str
    issue_number: int
    source_revision: str
    observed_at: str
    evidence_ids: tuple[str, ...]
    source_state: SourceState
    issue_state: IssueState
    lifecycle_stage: LifecycleStage
    terminal_disposition: TerminalDisposition
    readiness_result: ReadinessResult
    approval_applicability: ApprovalApplicabilityResult
    merge_applicability: MergeAuthorizationApplicabilityResult | None = None
    ready_for_review_admission: LifecycleMutationAdmissionResult | None = None
    closure_admission: LifecycleMutationAdmissionResult | None = None
    execution_authorization: AuthorityProjection = _NOT_APPLICABLE
    external_write_authorization: AuthorityProjection = _NOT_APPLICABLE
    dependency_state: DependencyState = DependencyState.CLEAR
    primary_claims: tuple[PrimaryIssueClaim, ...] = ()
    validation_state: ValidationState = ValidationState.NOT_RUN
    freshness_state: FreshnessState = FreshnessState.CURRENT
    observed_labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.readiness_result) is not ReadinessResult:
            raise TypeError("readiness_result must be exact ReadinessResult")
        if type(self.approval_applicability) is not ApprovalApplicabilityResult:
            raise TypeError(
                "approval_applicability must be exact ApprovalApplicabilityResult"
            )
        if (
            self.merge_applicability is not None
            and type(self.merge_applicability) is not MergeAuthorizationApplicabilityResult
        ):
            raise TypeError(
                "merge_applicability must be exact MergeAuthorizationApplicabilityResult or None"
            )
        for name, expected_mutation in (
            ("ready_for_review_admission", "mark-ready"),
            ("closure_admission", "close-issue"),
        ):
            admission = getattr(self, name)
            if admission is None:
                continue
            if type(admission) is not LifecycleMutationAdmissionResult:
                raise TypeError(f"{name} must be exact LifecycleMutationAdmissionResult or None")
            if admission.requested_mutation != expected_mutation:
                raise ValueError(f"{name} must carry the {expected_mutation!r} admission")
        for name in ("execution_authorization", "external_write_authorization"):
            projection = getattr(self, name)
            if type(projection) is not AuthorityProjection:
                raise TypeError(f"{name} must be exact AuthorityProjection")


def _admission_projection(
    admission: LifecycleMutationAdmissionResult | None,
) -> AuthorityProjection:
    if admission is None:
        return _NOT_APPLICABLE
    return AuthorityProjection.from_lifecycle_admission(admission)


def _merge_projection(
    applicability: MergeAuthorizationApplicabilityResult | None,
) -> AuthorityProjection:
    if applicability is None:
        return _NOT_APPLICABLE
    return AuthorityProjection.from_merge_authorization_applicability(applicability)


def produce_issue_operational_evidence(
    evidence: IssueOperationalStateProductionEvidence,
) -> IssueOperationalEvidence:
    """Adapt already-owned canonical evidence into ``IssueOperationalEvidence``."""

    if type(evidence) is not IssueOperationalStateProductionEvidence:
        raise TypeError(
            "evidence must be exact IssueOperationalStateProductionEvidence"
        )
    # Re-run producer invariants so a tampered frozen object fails closed.
    evidence.__post_init__()

    try:
        readiness = _READINESS_MAP[evidence.readiness_result.outcome]
    except KeyError as exc:
        raise ValueError("unsupported readiness outcome") from exc

    return IssueOperationalEvidence(
        repository=evidence.repository,
        issue_number=evidence.issue_number,
        source_revision=evidence.source_revision,
        observed_at=evidence.observed_at,
        evidence_ids=evidence.evidence_ids,
        source_state=evidence.source_state,
        issue_state=evidence.issue_state,
        lifecycle_stage=evidence.lifecycle_stage,
        terminal_disposition=evidence.terminal_disposition,
        readiness=readiness,
        implementation_authorization=AuthorityProjection.from_approval_applicability(
            evidence.approval_applicability
        ),
        ready_for_review_authorization=_admission_projection(
            evidence.ready_for_review_admission
        ),
        execution_authorization=evidence.execution_authorization,
        merge_authorization=_merge_projection(evidence.merge_applicability),
        closure_authorization=_admission_projection(evidence.closure_admission),
        external_write_authorization=evidence.external_write_authorization,
        dependency_state=evidence.dependency_state,
        primary_claims=evidence.primary_claims,
        validation_state=evidence.validation_state,
        freshness_state=evidence.freshness_state,
        observed_labels=evidence.observed_labels,
    )


def produce_issue_operational_state(
    evidence: IssueOperationalStateProductionEvidence,
) -> IssueOperationalState:
    """Produce one canonical #1441 ``IssueOperationalState`` from current evidence."""

    return build_issue_operational_state(produce_issue_operational_evidence(evidence))
