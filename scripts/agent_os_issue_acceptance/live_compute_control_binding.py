"""Live production binding into the #1451 -> #1441 -> #1439/#1419 chain (#1460).

Target flow (unchanged from the issue):

```text
Live GitHub/runtime evidence
  -> existing canonical owners/providers
  -> thin exact-type production adapters (this module)
  -> #1451 acquire_issue_operational_state(...)
  -> #1441 IssueOperationalState
  -> #1439 compute-control producer
  -> #1419 agent-os-compute-control-projection/1.0
```

This module owns no readiness, authorization, dependency, claim, validation,
freshness, or compute-control semantics of its own. It is a binding/adapter
boundary only: it performs (or accepts pre-performed) reads through existing
canonical evidence owners, translates their already-typed results into the
exact #1451 injected-evidence shapes, and invokes the unchanged #1451/#1439
composition functions exactly once each.

## Canonical owner for each #1451 input

- ``CurrentIssueSnapshot`` -- ``LiveCurrentIssueSnapshotReader`` below, which
  composes the existing
  ``scripts.agent_os_candidate_packet_live_input.LiveIssueReader`` (one
  authorized single-issue GitHub read over a caller-injected
  ``SingleIssueTransport``) with the existing
  ``scripts.agent_os_github_issue_provider.revision.issue_source_revision``
  content-addressed issue-revision function. ``source_revision`` (the
  repository SHA), ``lifecycle_stage``, and an optional
  ``terminal_disposition`` override remain caller-supplied: no canonical live
  PR-linkage or lifecycle-stage classifier exists anywhere in this repository
  today (confirmed by inspection of ``08_Tooling/agent-os-execution-service``
  and every ``scripts.agent_os_*`` package), and inventing one here would
  create a second claim/lifecycle authority, which #1460 explicitly forbids.
  Everything this reader *can* derive from the raw GitHub issue payload alone
  (``issue_state``, ``observed_labels``, the content-addressed
  ``issue_source_revision``, and ``terminal_disposition`` from GitHub's own
  ``state_reason`` field) it derives; it never reads issue body prose as
  authorization/dependency/validation/claim truth.
- Approval applicability (``ApprovalApplicabilityResult``) -- caller-supplied,
  produced by the existing sole canonical evaluator
  ``scripts.agent_os_issue_acceptance.approval_records.evaluate_approval_applicability``.
  That evaluator requires the full candidate-packet evidence graph (an
  approval record, a draft-task proposal, IssuePlan current-state evidence,
  and repository-state evidence); this thin binder does not reconstruct that
  graph, only wires the evaluator's already-produced result into #1451.
- ``DependencyState`` / ``ValidationState`` -- ``dependency_state_from_evidence``
  and ``validation_state_from_evidence`` below, which translate the existing
  canonical ``DependencyEvidence`` / ``ValidationEvidence`` vocabulary
  (``scripts.agent_os_candidate_packet.stage_models``) into #1451's
  vocabulary. Callers obtain that evidence from the existing production
  ``RepositoryEvidenceReader`` implementation,
  ``scripts.agent_os_candidate_packet_live_input.LiveRepositoryEvidenceReader``,
  which is itself already the sole production adapter over the #1185/#1197
  ``DependencyReadinessEvidence`` dependency-readiness authority and the
  ``scripts.agent_os_remote_validation`` advisory pre-PR evidence authority.
  This module calls the caller-injected reader directly (a genuine live
  read), not a fabricated value.
- ``PrimaryIssueClaim`` tuple -- caller-supplied. No canonical live PR-linkage
  reader exists in this repository; #1460 forbids inventing a new claim
  authority.
- ``FreshnessState`` -- caller-supplied. No general-purpose currentness
  evidence owner exists outside domain-specific ones already reused above
  (dependency readiness, IssuePlan current-state, approval invalidation);
  #1460 forbids inventing a new freshness authority.
- Merge applicability, Ready-for-Review admission, closure admission,
  execution authorization, external-write authorization -- all caller-
  supplied, produced by the existing ``merge_authorization.py`` /
  ``lifecycle_mutation_guard.py`` evaluators and the existing execution /
  external-write authorization reacquisition owners; passed through
  unchanged and exactly as optional as #1451 already allows.

## No second GitHub client

This module creates no GitHub client. ``LiveCurrentIssueSnapshotReader`` is
parameterized over an injected ``SingleIssueTransport`` -- the same seam
``scripts.agent_os_candidate_packet_live_input.LiveIssueReader`` already
uses. A caller may satisfy that seam with any existing conforming
transport, such as the paginated-listing-adjacent PyGithub client
construction already used by
``scripts.agent_os_github_issue_provider.transport.PyGithubRestTransport``
(reusing the exact same ``github.Github`` + ``requester.requestJsonAndCheck``
pattern for a single-issue ``GET``).

``08_Tooling/agent-os-execution-service``'s
``host_github_read_transport.HostGitHubReadTransport`` already implements
this exact protocol, but it cannot be imported here: that package imports
*from* ``scripts.agent_os_candidate_packet_live_input`` (see its own
docstring), so the dependency direction runs execution-service -> scripts,
not the reverse. Importing it back from this ``scripts`` package would
invert that direction and was investigated and rejected for #1460 -- this is
exactly the "reverse import direction is not set up" case the issue asked to
check for. No second transport implementation is added by this module either;
it only accepts one.

## Exposed governed callable

``acquire_live_compute_control_projection(evidence)`` is the smallest
governed production/runtime callable #1420 needs: given one
``LiveComputeControlEvidence`` bundle of already-acquired canonical evidence,
it performs the one live issue read, translates every #1451 input, invokes
the unchanged #1451 -> #1441 -> #1439/#1419 chain exactly once, and returns
the serialized ``agent-os-compute-control-projection/1.0`` payload. It
performs no Notion write, no merge, no closure, and no other external-system
mutation; #1424 remains the sole destination writer.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.agent_os_candidate_packet.post_pr_lane_plan import PostPrLanePlan
from scripts.agent_os_candidate_packet.stage_models import (
    DependencyEvidence,
    EvidenceStatus,
    IssueReadStatus,
    RepositoryEvidenceReader,
    ValidationEvidence,
)
from scripts.agent_os_candidate_packet_live_input import (
    LiveIssueReader,
    SingleIssueTransport,
)
from scripts.agent_os_github_issue_provider.revision import issue_source_revision
from scripts.agent_os_remote_validation.models import ValidationPlan
from scripts.agent_os_remote_validation.provenance import (
    EvidenceApplicabilityProjection,
)

from .approval_records import ApprovalApplicabilityResult
from .coding_command_center_handoff import CodingCommandCenterEvidence
from .compute_control_producer import (
    ComputeControlProductionEvidence,
    produce_serialized_compute_control_projection,
)
from .compute_control_projection import (
    ActiveExecutionReference,
    ValidationHeadReference,
)
from .executor_route import ExecutorRouteDecision
from .issue_operational_state import (
    AuthorityProjection,
    DependencyState,
    FreshnessState,
    IssueState,
    LifecycleStage,
    PrimaryIssueClaim,
    SourceState,
    TerminalDisposition,
    ValidationState,
)
from .issue_operational_state_acquisition import (
    CurrentIssueSnapshot,
    acquire_issue_operational_state,
)
from .lifecycle_mutation_guard import LifecycleMutationAdmissionResult
from .merge_authorization import MergeAuthorizationApplicabilityResult
from .validation_failure_classifier import ValidationFailureClassificationResult

_STATE_REASON_TO_TERMINAL_DISPOSITION = {
    "completed": TerminalDisposition.COMPLETED,
    "not_planned": TerminalDisposition.NOT_PLANNED,
}


def dependency_state_from_evidence(evidence: DependencyEvidence) -> DependencyState:
    """Project the existing canonical ``DependencyEvidence`` into #1451's vocabulary.

    ``NEEDS_DECISION`` and ``UNAVAILABLE`` both fail closed to ``UNKNOWN``:
    #1451's ``DependencyState`` has no third "needs a human" member, and
    ``UNKNOWN`` is already its honest "not proven clear" fail-closed value.
    """
    if type(evidence) is not DependencyEvidence:
        raise TypeError("evidence must be exact DependencyEvidence")
    if evidence.status is EvidenceStatus.RESOLVED_CLEAR:
        return DependencyState.CLEAR
    if evidence.status is EvidenceStatus.RESOLVED_BLOCKED:
        return DependencyState.BLOCKED
    return DependencyState.UNKNOWN


def validation_state_from_evidence(evidence: ValidationEvidence) -> ValidationState:
    """Project the existing canonical ``ValidationEvidence`` into #1451's vocabulary.

    ``NEEDS_DECISION`` maps to ``PENDING``: both mean current evidence is
    insufficient to proceed without further resolution. An ``UNAVAILABLE``
    result is mapped only when its own reason codes truthfully identify why
    (no structured source configured -> ``NOT_RUN``; stale advisory evidence
    -> ``STALE``); any other ``UNAVAILABLE`` reason (a subject or validation
    -plan identity mismatch, or an unrecognized advisory status) cannot be
    truthfully mapped to any #1451 ``ValidationState`` member, so this
    function fails closed by raising rather than guessing.
    """
    if type(evidence) is not ValidationEvidence:
        raise TypeError("evidence must be exact ValidationEvidence")
    if evidence.status is EvidenceStatus.RESOLVED_CLEAR:
        return ValidationState.PASSED
    if evidence.status is EvidenceStatus.RESOLVED_BLOCKED:
        return ValidationState.FAILED
    if evidence.status is EvidenceStatus.NEEDS_DECISION:
        return ValidationState.PENDING
    if "validation.advisory-stale" in evidence.reason_codes:
        return ValidationState.STALE
    if "validation.no-structured-source-configured" in evidence.reason_codes:
        return ValidationState.NOT_RUN
    raise ValueError(
        "validation evidence cannot be truthfully mapped to a ValidationState; "
        f"reason_codes={evidence.reason_codes!r}"
    )


def _label_names(item: object) -> tuple[str, ...]:
    labels = item.get("labels") if isinstance(item, dict) else None
    if labels is None:
        return ()
    names: list[str] = []
    for label in labels:
        value = label.get("name") if isinstance(label, dict) else label
        if isinstance(value, str) and value.strip():
            names.append(value)
    return tuple(sorted(set(names)))


@dataclass(frozen=True, slots=True)
class LiveCurrentIssueSnapshotReader:
    """Production ``CurrentIssueSnapshotReader`` over one injected ``SingleIssueTransport``.

    Only fields the raw GitHub issue payload can truthfully answer are
    derived here (``issue_state``, ``observed_labels``, the content-addressed
    ``issue_source_revision``, and ``terminal_disposition`` from GitHub's own
    structured ``state_reason`` field). ``source_revision`` (the repository
    SHA under evaluation) and ``lifecycle_stage`` are supplied by the caller,
    who already knows its current checkout SHA and has already reacquired
    whatever primary claim/lifecycle evidence it holds -- deriving either
    here would require inventing a PR-linkage or lifecycle-stage authority,
    which #1460 explicitly forbids.
    """

    transport: SingleIssueTransport
    source_revision: str
    observed_at: str
    lifecycle_stage: LifecycleStage
    terminal_disposition_override: TerminalDisposition | None = None

    def __post_init__(self) -> None:
        if self.transport is None:
            raise TypeError("transport is required")
        if type(self.source_revision) is not str or not self.source_revision:
            raise TypeError("source_revision must be non-empty built-in text")
        if type(self.observed_at) is not str or not self.observed_at:
            raise TypeError("observed_at must be non-empty built-in text")
        if type(self.lifecycle_stage) is not LifecycleStage:
            raise TypeError("lifecycle_stage must be exact LifecycleStage")
        if (
            self.terminal_disposition_override is not None
            and type(self.terminal_disposition_override) is not TerminalDisposition
        ):
            raise TypeError(
                "terminal_disposition_override must be exact TerminalDisposition or None"
            )

    def read_current_issue(
        self, repository: str, issue_number: int
    ) -> CurrentIssueSnapshot:
        result = LiveIssueReader(transport=self.transport).read_issue(
            repository, issue_number
        )
        if result.status is not IssueReadStatus.OK:
            raise ValueError(f"live issue read did not succeed: {result.status.value}")
        item = result.item
        if not isinstance(item, dict):
            raise ValueError("live issue read returned no item despite an OK status")

        revision = issue_source_revision(item)

        raw_state = item.get("state")
        if raw_state == "open":
            issue_state = IssueState.OPEN
        elif raw_state == "closed":
            issue_state = IssueState.CLOSED
        else:
            raise ValueError("issue state field is missing or unsupported")

        terminal_disposition = self.terminal_disposition_override
        if terminal_disposition is None:
            terminal_disposition = _STATE_REASON_TO_TERMINAL_DISPOSITION.get(
                item.get("state_reason"), TerminalDisposition.NONE
            )

        body = item.get("body")
        body = "" if body is None else body
        if type(body) is not str:
            raise ValueError("issue body field is malformed")

        return CurrentIssueSnapshot(
            repository=repository,
            issue_number=issue_number,
            body=body,
            source_revision=self.source_revision,
            issue_source_revision=revision,
            observed_at=self.observed_at,
            evidence_ids=(revision,),
            source_state=SourceState.COMPLETE,
            issue_state=issue_state,
            lifecycle_stage=self.lifecycle_stage,
            terminal_disposition=terminal_disposition,
            observed_labels=_label_names(item),
        )


@dataclass(frozen=True, slots=True)
class LiveComputeControlEvidence:
    """Already-acquired canonical evidence for one #1460 production call.

    Every field here is either produced by this module's own live read
    (the issue snapshot, via ``issue_transport`` and ``dependency_reader``)
    or is a caller-supplied result from an existing canonical evaluator, as
    documented on each field and in this module's docstring. Nothing here
    infers meaning from issue prose or labels.
    """

    repository: str
    issue_number: int
    issue_transport: SingleIssueTransport
    source_revision: str
    observed_at: str
    lifecycle_stage: LifecycleStage
    approval_applicability: ApprovalApplicabilityResult
    primary_claims: tuple[PrimaryIssueClaim, ...]
    freshness_state: FreshnessState
    terminal_disposition: TerminalDisposition | None = None
    dependency_reader: RepositoryEvidenceReader | None = None
    current_head_sha: str | None = None
    primary_claim: PrimaryIssueClaim | None = None
    merge_applicability: MergeAuthorizationApplicabilityResult | None = None
    ready_for_review_admission: LifecycleMutationAdmissionResult | None = None
    closure_admission: LifecycleMutationAdmissionResult | None = None
    execution_authorization: AuthorityProjection | None = None
    external_write_authorization: AuthorityProjection | None = None
    executor_route_decision: ExecutorRouteDecision | None = None
    validation_classification: ValidationFailureClassificationResult | None = None
    validation_evidence_reference: str | None = None
    post_pr_lane_plan: PostPrLanePlan | None = None
    handoff_target: str | None = None
    validation_plan: ValidationPlan | None = None
    evidence_applicability: EvidenceApplicabilityProjection | None = None
    validation_head_reference: ValidationHeadReference | None = None
    active_execution: ActiveExecutionReference | None = None
    measured_compute_metadata_reference: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.repository) is not str
            or not self.repository
            or "/" not in self.repository
        ):
            raise ValueError("repository must use owner/name form")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise TypeError("issue_number must be a positive built-in integer")
        if self.issue_transport is None:
            raise TypeError("issue_transport is required")
        if type(self.source_revision) is not str or not self.source_revision:
            raise TypeError("source_revision must be non-empty built-in text")
        if type(self.observed_at) is not str or not self.observed_at:
            raise TypeError("observed_at must be non-empty built-in text")
        if type(self.lifecycle_stage) is not LifecycleStage:
            raise TypeError("lifecycle_stage must be exact LifecycleStage")
        if type(self.approval_applicability) is not ApprovalApplicabilityResult:
            raise TypeError(
                "approval_applicability must be exact ApprovalApplicabilityResult"
            )
        if type(self.primary_claims) is not tuple or any(
            type(claim) is not PrimaryIssueClaim for claim in self.primary_claims
        ):
            raise TypeError(
                "primary_claims must be an exact tuple[PrimaryIssueClaim, ...]"
            )
        if type(self.freshness_state) is not FreshnessState:
            raise TypeError("freshness_state must be exact FreshnessState")
        if (
            self.terminal_disposition is not None
            and type(self.terminal_disposition) is not TerminalDisposition
        ):
            raise TypeError(
                "terminal_disposition must be exact TerminalDisposition or None"
            )
        for name, expected in (
            ("merge_applicability", MergeAuthorizationApplicabilityResult),
            ("ready_for_review_admission", LifecycleMutationAdmissionResult),
            ("closure_admission", LifecycleMutationAdmissionResult),
            ("execution_authorization", AuthorityProjection),
            ("external_write_authorization", AuthorityProjection),
        ):
            value = getattr(self, name)
            if value is not None and type(value) is not expected:
                raise TypeError(f"{name} must be exact {expected.__name__} or None")


def acquire_live_compute_control_projection(
    evidence: LiveComputeControlEvidence,
) -> dict[str, object]:
    """Produce one exact current serialized ``agent-os-compute-control-projection/1.0``.

    This is the smallest governed production/runtime callable #1420 needs: it
    performs the one live issue read, wires every already-acquired canonical
    evidence input into the exact #1451 shapes, invokes
    ``acquire_issue_operational_state`` and the unchanged #1439/#1419
    composition exactly once each, and returns the serialized projection.
    Missing or malformed required evidence raises rather than fabricating a
    projection; no GitHub write, Notion write, or other external-system
    mutation is performed.
    """
    if type(evidence) is not LiveComputeControlEvidence:
        raise TypeError("evidence must be exact LiveComputeControlEvidence")
    evidence.__post_init__()

    reader = LiveCurrentIssueSnapshotReader(
        transport=evidence.issue_transport,
        source_revision=evidence.source_revision,
        observed_at=evidence.observed_at,
        lifecycle_stage=evidence.lifecycle_stage,
        terminal_disposition_override=evidence.terminal_disposition,
    )

    def approval_acquirer(
        _snapshot: CurrentIssueSnapshot,
    ) -> ApprovalApplicabilityResult:
        return evidence.approval_applicability

    def dependency_acquirer(_snapshot: CurrentIssueSnapshot) -> DependencyState:
        if evidence.dependency_reader is None:
            return DependencyState.UNKNOWN
        return dependency_state_from_evidence(
            evidence.dependency_reader.read_dependency_evidence(
                evidence.repository, evidence.issue_number
            )
        )

    def claim_acquirer(
        _snapshot: CurrentIssueSnapshot,
    ) -> tuple[PrimaryIssueClaim, ...]:
        return evidence.primary_claims

    def validation_acquirer(_snapshot: CurrentIssueSnapshot) -> ValidationState:
        if evidence.dependency_reader is None:
            return ValidationState.NOT_RUN
        return validation_state_from_evidence(
            evidence.dependency_reader.read_validation_evidence(
                evidence.repository, evidence.issue_number
            )
        )

    def freshness_acquirer(_snapshot: CurrentIssueSnapshot) -> FreshnessState:
        return evidence.freshness_state

    def merge_acquirer(
        _snapshot: CurrentIssueSnapshot,
    ) -> MergeAuthorizationApplicabilityResult | None:
        return evidence.merge_applicability

    def ready_for_review_acquirer(
        _snapshot: CurrentIssueSnapshot,
    ) -> LifecycleMutationAdmissionResult | None:
        return evidence.ready_for_review_admission

    def closure_acquirer(
        _snapshot: CurrentIssueSnapshot,
    ) -> LifecycleMutationAdmissionResult | None:
        return evidence.closure_admission

    def execution_authorization_acquirer(
        _snapshot: CurrentIssueSnapshot,
    ) -> AuthorityProjection:
        assert evidence.execution_authorization is not None  # guarded by caller below
        return evidence.execution_authorization

    def external_write_authorization_acquirer(
        _snapshot: CurrentIssueSnapshot,
    ) -> AuthorityProjection:
        assert (
            evidence.external_write_authorization is not None
        )  # guarded by caller below
        return evidence.external_write_authorization

    acquired = acquire_issue_operational_state(
        repository=evidence.repository,
        issue_number=evidence.issue_number,
        issue_reader=reader,
        approval_acquirer=approval_acquirer,
        dependency_acquirer=dependency_acquirer,
        claim_acquirer=claim_acquirer,
        validation_acquirer=validation_acquirer,
        freshness_acquirer=freshness_acquirer,
        merge_acquirer=merge_acquirer,
        ready_for_review_acquirer=ready_for_review_acquirer,
        closure_acquirer=closure_acquirer,
        execution_authorization_acquirer=(
            execution_authorization_acquirer
            if evidence.execution_authorization is not None
            else None
        ),
        external_write_authorization_acquirer=(
            external_write_authorization_acquirer
            if evidence.external_write_authorization is not None
            else None
        ),
    )
    state = acquired.operational_state

    handoff_evidence = CodingCommandCenterEvidence(
        operational_state=state,
        source_revision=state.source_revision,
        observed_head_sha=evidence.current_head_sha,
        executor_route_decision=evidence.executor_route_decision,
        validation_classification=evidence.validation_classification,
        validation_evidence_reference=evidence.validation_evidence_reference,
        post_pr_lane_plan=evidence.post_pr_lane_plan,
        handoff_target=evidence.handoff_target,
    )

    projection_evidence = ComputeControlProductionEvidence(
        operational_state=state,
        current_head_sha=evidence.current_head_sha,
        primary_claim=evidence.primary_claim,
        handoff_evidence=handoff_evidence,
        validation_plan=evidence.validation_plan,
        evidence_applicability=evidence.evidence_applicability,
        validation_head_reference=evidence.validation_head_reference,
        active_execution=evidence.active_execution,
        measured_compute_metadata_reference=evidence.measured_compute_metadata_reference,
    )

    return produce_serialized_compute_control_projection(projection_evidence)
