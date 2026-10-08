"""Production-consumer proof for lifecycle_stage_acquisition.py (#3433).

Proves the acquired stage reaches the existing production composition entry
point -- ``LiveCandidateEvidenceReader.read_candidate_evidence_detailed``
(the #3329 ``CanonicalCandidateEvidenceReader`` consumed by the shadow
selection seam) -- and not merely that the acquirer can run standalone.

The test composes, with fixture evidence only and zero network access:

    verified PR-lineage fixtures
      -> acquire_lifecycle_stage
      -> lifecycle_stage_from_acquisition
      -> LiveCandidateEvidence (all other canonical inputs fixture-supplied)
      -> LiveCandidateEvidenceReader.read_candidate_evidence_detailed
      -> CandidateIssueEvidence.operational_state.lifecycle_stage

and asserts the shadow invariants hold: exactly one live read, no writes,
``side_effects_performed`` false, and the existing fail-closed reason when
the acquirer cannot establish a stage.

What this does not prove: a live GitHub PR-lineage reader does not exist
yet, so shadow-run still supplies ``lifecycle_stage=None`` in production.
That reader is the explicit remaining prerequisite; this file proves the
composition seam is ready for it.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.agent_os_candidate_packet.executable_lane_selection import (
    CandidateIssueEvidence,
)
from scripts.agent_os_candidate_packet.stage_models import (
    DependencyEvidence,
    EvidenceStatus,
    ValidationEvidence,
)
from scripts.agent_os_candidate_packet_live_input import (
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)
from scripts.agent_os_issue_acceptance.approval_records import (
    ApprovalApplicabilityResult,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    FreshnessState,
    IssueState,
    LifecycleStage,
)
from scripts.agent_os_issue_acceptance.lifecycle_stage_acquisition import (
    LifecycleStageAcquisitionRequest,
    PrLineageEnumeration,
    VerifiedPrLineage,
    acquire_lifecycle_stage,
    lifecycle_stage_from_acquisition,
)
from scripts.agent_os_issue_acceptance.live_candidate_evidence_reader import (
    REASON_MISSING_LIFECYCLE_STAGE,
    LiveCandidateEvidence,
    LiveCandidateEvidenceReader,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    EnvironmentCapabilityEvidence,
    EnvironmentCapabilityState,
)

REPOSITORY = "Blummer92/agent-os"
ISSUE_NUMBER = 3433
SOURCE_REVISION = "9" * 40
ISSUE_REVISION = "github-issue-v1:" + "a" * 64
OBSERVED_AT = "2026-10-08T15:00:00Z"


def issue_item(**changes: object) -> dict[str, object]:
    base = {
        "number": ISSUE_NUMBER,
        "title": "AI-NAV-LIFECYCLE1 -- Acquire canonical lifecycle stage",
        "state": "open",
        "body": "## Objective\nAcquire canonical lifecycle stage.\n",
        "html_url": f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}",
        "created_at": "2026-10-08T15:08:11Z",
        "updated_at": "2026-10-08T15:32:15Z",
        "closed_at": None,
        "state_reason": None,
        "labels": [{"name": "status:ready"}],
    }
    base.update(changes)
    return base


@dataclass
class FakeTransport:
    result: SingleIssueTransportResult
    calls: int = 0

    def get_issue(
        self, repository: str, issue_number: int
    ) -> SingleIssueTransportResult:
        self.calls += 1
        return self.result


@dataclass
class FakeRepositoryEvidenceReader:
    dependency_evidence: DependencyEvidence
    validation_evidence: ValidationEvidence

    def read_dependency_evidence(
        self, repository: str, issue_number: int
    ) -> DependencyEvidence:
        return self.dependency_evidence

    def read_validation_evidence(
        self, repository: str, issue_number: int
    ) -> ValidationEvidence:
        return self.validation_evidence


def ok_transport(**item_changes: object) -> FakeTransport:
    return FakeTransport(
        result=SingleIssueTransportResult(
            outcome=SingleIssueTransportOutcome.OK, item=issue_item(**item_changes)
        )
    )


def blocked_approval() -> ApprovalApplicabilityResult:
    return ApprovalApplicabilityResult(
        status="blocked",
        approval_id=None,
        approval_revision=None,
        current_proposal_id=None,
        reason_codes=(),
        changed_bindings=(),
        approval_applicable=False,
        details=("approval-record:absent",),
    )


def unverified_environment() -> EnvironmentCapabilityEvidence:
    return EnvironmentCapabilityEvidence(
        local_execution_state=EnvironmentCapabilityState.NOT_VERIFIED,
        push_state=EnvironmentCapabilityState.NOT_VERIFIED,
    )


def clear_evidence_reader() -> FakeRepositoryEvidenceReader:
    return FakeRepositoryEvidenceReader(
        dependency_evidence=DependencyEvidence(status=EvidenceStatus.RESOLVED_CLEAR),
        validation_evidence=ValidationEvidence(status=EvidenceStatus.RESOLVED_CLEAR),
    )


def ready_pr_lineage() -> tuple[VerifiedPrLineage, ...]:
    return (
        VerifiedPrLineage(
            pull_request_number=1201,
            repository=REPOSITORY,
            is_open=True,
            is_draft=False,
            is_merged=False,
            head_sha="b" * 40,
            branch="agent/3433-lifecycle-stage-acquisition",
            pr_title="Implement #3433",
            pr_body="Implements the canonical lifecycle-stage acquirer.\n\nCloses #3433",
            observed_at=OBSERVED_AT,
        ),
    )


def acquisition_request(
    pr_lineage: tuple[VerifiedPrLineage, ...],
) -> LifecycleStageAcquisitionRequest:
    return LifecycleStageAcquisitionRequest(
        repository=REPOSITORY,
        issue_number=ISSUE_NUMBER,
        issue_state=IssueState.OPEN,
        issue_source_revision=ISSUE_REVISION,
        source_revision=SOURCE_REVISION,
        observed_at=OBSERVED_AT,
        pr_lineage=pr_lineage,
        lineage_enumeration=PrLineageEnumeration(
            complete=True, enumeration_note="all pages consumed; total matched"
        ),
    )


def evidence_bundle(
    transport: FakeTransport, lifecycle_stage: LifecycleStage | None
) -> LiveCandidateEvidence:
    return LiveCandidateEvidence(
        repository=REPOSITORY,
        issue_transport=transport,
        observed_at=OBSERVED_AT,
        source_revision=SOURCE_REVISION,
        lifecycle_stage=lifecycle_stage,
        primary_claims=(),
        approval_applicability=blocked_approval(),
        freshness_state=FreshnessState.CURRENT,
        requested_mode="planning",
        environment=unverified_environment(),
        dependency_depth=0,
        substitutable=False,
        dependency_reader=clear_evidence_reader(),
    )


def test_acquired_stage_reaches_production_consumer() -> None:
    """The #3433 acquirer's output flows through the real production reader
    into ``CandidateIssueEvidence.operational_state.lifecycle_stage``."""
    transport = ok_transport()

    acquisition = acquire_lifecycle_stage(acquisition_request(ready_pr_lineage()))
    stage = lifecycle_stage_from_acquisition(acquisition)
    assert stage is LifecycleStage.REVIEW

    reader = LiveCandidateEvidenceReader(evidence_bundle(transport, stage))
    outcome = reader.read_candidate_evidence_detailed(REPOSITORY, ISSUE_NUMBER)

    assert outcome.failure_reason is None
    evidence = outcome.evidence
    assert type(evidence) is CandidateIssueEvidence
    assert evidence.issue_number == ISSUE_NUMBER
    # The acquisition result reaches the existing consumer: the composed
    # operational state carries the acquired stage.
    assert evidence.operational_state.lifecycle_stage is LifecycleStage.REVIEW
    assert type(evidence.operational_state.lifecycle_stage) is LifecycleStage
    # The state_id join is preserved through the mode evaluation.
    assert (
        evidence.mode_decision.source_operational_state_id
        == evidence.operational_state.state_id
    )
    # Shadow path stays non-mutating: one live read, no side effects.
    assert transport.calls == 1
    assert evidence.operational_state.side_effects_performed is False


def test_draft_pr_stage_reaches_production_consumer() -> None:
    transport = ok_transport()
    draft_lineage = (
        VerifiedPrLineage(
            pull_request_number=1202,
            repository=REPOSITORY,
            is_open=True,
            is_draft=True,
            is_merged=False,
            head_sha="c" * 40,
            branch="agent/3433-lifecycle-stage-acquisition",
            pr_title="Implement #3433",
            pr_body="Implements the canonical lifecycle-stage acquirer.\n\nCloses #3433",
            observed_at=OBSERVED_AT,
        ),
    )

    acquisition = acquire_lifecycle_stage(acquisition_request(draft_lineage))
    stage = lifecycle_stage_from_acquisition(acquisition)
    assert stage is LifecycleStage.DRAFT_PR

    reader = LiveCandidateEvidenceReader(evidence_bundle(transport, stage))
    outcome = reader.read_candidate_evidence_detailed(REPOSITORY, ISSUE_NUMBER)

    assert outcome.failure_reason is None
    assert outcome.evidence is not None
    assert outcome.evidence.operational_state.lifecycle_stage is LifecycleStage.DRAFT_PR
    assert transport.calls == 1


def test_unacquirable_stage_preserves_fail_closed_reason() -> None:
    """When the acquirer cannot establish a stage, the production reader
    keeps its existing named fail-closed reason -- no stage is manufactured
    to make selection appear."""
    transport = ok_transport()

    acquisition = acquire_lifecycle_stage(acquisition_request(()))
    assert lifecycle_stage_from_acquisition(acquisition) is None

    reader = LiveCandidateEvidenceReader(
        evidence_bundle(transport, lifecycle_stage_from_acquisition(acquisition))
    )
    outcome = reader.read_candidate_evidence_detailed(REPOSITORY, ISSUE_NUMBER)

    assert outcome.evidence is None
    assert outcome.failure_reason == REASON_MISSING_LIFECYCLE_STAGE
    # The fail-closed check runs before any live read.
    assert transport.calls == 0
