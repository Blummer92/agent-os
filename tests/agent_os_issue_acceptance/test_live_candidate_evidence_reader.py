"""Focused coverage for scripts/agent_os_issue_acceptance/live_candidate_evidence_reader.py (#3329).

Fixture-driven: one complete-evidence success case proving the canonical
composition, and one fail-closed case per unavailable/stale/conflicting
evidence class, each asserting the exact named reason. No network access.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

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
    LifecycleStage,
    PrimaryIssueClaim,
)
from scripts.agent_os_issue_acceptance.live_candidate_evidence_reader import (
    REASON_COMPOSITION_CONTRACT_VIOLATION,
    REASON_MISSING_APPROVAL_APPLICABILITY,
    REASON_MISSING_DEPENDENCY_DEPTH,
    REASON_MISSING_ENVIRONMENT,
    REASON_MISSING_FRESHNESS_STATE,
    REASON_MISSING_LIFECYCLE_STAGE,
    REASON_MISSING_PRIMARY_CLAIMS,
    REASON_MISSING_REPOSITORY_SOURCE_REVISION,
    REASON_MISSING_REQUESTED_MODE,
    REASON_MISSING_SUBSTITUTABLE,
    REASON_REPOSITORY_MISMATCH,
    CandidateEvidenceReadOutcome,
    LiveCandidateEvidence,
    LiveCandidateEvidenceReader,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    EnvironmentCapabilityEvidence,
    EnvironmentCapabilityState,
)

SHA = "a" * 40
REPOSITORY = "Blummer92/agent-os"
ISSUE_NUMBER = 1359


def issue_item(**changes: object) -> dict[str, object]:
    base = {
        "number": ISSUE_NUMBER,
        "title": "Measure aggregate validation timing",
        "state": "open",
        "body": "## Objective\nMeasure aggregate validation timing.\n",
        "html_url": f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-28T03:00:00Z",
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


def failing_transport(outcome: SingleIssueTransportOutcome) -> FakeTransport:
    return FakeTransport(result=SingleIssueTransportResult(outcome=outcome))


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


def base_bundle_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = dict(
        repository=REPOSITORY,
        issue_transport=ok_transport(),
        observed_at="2026-10-05T18:00:00Z",
        source_revision=SHA,
        lifecycle_stage=LifecycleStage.IMPLEMENTATION,
        primary_claims=(),
        approval_applicability=blocked_approval(),
        freshness_state=FreshnessState.CURRENT,
        requested_mode="planning",
        environment=unverified_environment(),
        dependency_depth=0,
        substitutable=False,
        dependency_reader=clear_evidence_reader(),
    )
    kwargs.update(overrides)
    return kwargs


def make_reader(**overrides: object) -> LiveCandidateEvidenceReader:
    return LiveCandidateEvidenceReader(LiveCandidateEvidence(**base_bundle_kwargs(**overrides)))


def test_complete_evidence_composes_exact_candidate_issue_evidence() -> None:
    transport = ok_transport()
    reader = make_reader(issue_transport=transport)

    evidence = reader.read_candidate_evidence(REPOSITORY, ISSUE_NUMBER)

    assert type(evidence) is CandidateIssueEvidence
    assert evidence.issue_number == ISSUE_NUMBER
    assert evidence.operational_state.issue_number == ISSUE_NUMBER
    # The state_id join is preserved through the mode evaluation.
    assert (
        evidence.mode_decision.source_operational_state_id
        == evidence.operational_state.state_id
    )
    assert evidence.dependency_depth == 0
    assert evidence.substitutable is False
    # One live read per admitted candidate: no second fetch, no client built.
    assert transport.calls == 1
    # Repository SHA and content-addressed issue revision stay distinct.
    state = evidence.operational_state
    assert state.source_revision == SHA
    assert len(state.evidence_ids) == 1
    assert state.evidence_ids[0].startswith("github-issue-v1:")
    assert state.evidence_ids[0] != SHA


@pytest.mark.parametrize(
    ("missing_field", "expected_reason"),
    [
        ("source_revision", REASON_MISSING_REPOSITORY_SOURCE_REVISION),
        ("lifecycle_stage", REASON_MISSING_LIFECYCLE_STAGE),
        ("primary_claims", REASON_MISSING_PRIMARY_CLAIMS),
        ("approval_applicability", REASON_MISSING_APPROVAL_APPLICABILITY),
        ("freshness_state", REASON_MISSING_FRESHNESS_STATE),
        ("dependency_depth", REASON_MISSING_DEPENDENCY_DEPTH),
        ("substitutable", REASON_MISSING_SUBSTITUTABLE),
        ("requested_mode", REASON_MISSING_REQUESTED_MODE),
        ("environment", REASON_MISSING_ENVIRONMENT),
    ],
)
def test_each_missing_canonical_input_fails_closed_with_named_reason(
    missing_field: str, expected_reason: str
) -> None:
    transport = ok_transport()
    reader = make_reader(issue_transport=transport, **{missing_field: None})

    outcome = reader.read_candidate_evidence_detailed(REPOSITORY, ISSUE_NUMBER)

    assert outcome.evidence is None
    assert outcome.failure_reason == expected_reason
    # Fail-closed checks run before any live read: no manufactured fetch.
    assert transport.calls == 0
    # The protocol surface stays None, so the seam reports
    # shadow-selection.candidate-evidence-incomplete.
    assert reader.read_candidate_evidence(REPOSITORY, ISSUE_NUMBER) is None


@pytest.mark.parametrize(
    ("outcome_status", "expected_reason"),
    [
        (
            SingleIssueTransportOutcome.NOT_FOUND,
            "candidate-evidence.issue-read-failed:not-found",
        ),
        (
            SingleIssueTransportOutcome.API_ERROR,
            "candidate-evidence.issue-read-failed:api-error",
        ),
        (
            SingleIssueTransportOutcome.PERMISSION_DENIED,
            "candidate-evidence.issue-read-failed:permission-denied",
        ),
        (
            SingleIssueTransportOutcome.MALFORMED_RESPONSE,
            "candidate-evidence.issue-read-failed:malformed-response",
        ),
    ],
)
def test_transport_failure_fails_closed_with_transport_reason(
    outcome_status: SingleIssueTransportOutcome, expected_reason: str
) -> None:
    reader = make_reader(issue_transport=failing_transport(outcome_status))

    outcome = reader.read_candidate_evidence_detailed(REPOSITORY, ISSUE_NUMBER)

    assert outcome.evidence is None
    assert outcome.failure_reason == expected_reason


def test_repository_mismatch_fails_closed() -> None:
    reader = make_reader()

    outcome = reader.read_candidate_evidence_detailed("other/repo", ISSUE_NUMBER)

    assert outcome.evidence is None
    assert outcome.failure_reason == REASON_REPOSITORY_MISMATCH


def test_unmappable_validation_evidence_fails_closed_as_contract_violation() -> None:
    reader = make_reader(
        dependency_reader=FakeRepositoryEvidenceReader(
            dependency_evidence=DependencyEvidence(
                status=EvidenceStatus.RESOLVED_CLEAR
            ),
            validation_evidence=ValidationEvidence(
                status=EvidenceStatus.UNAVAILABLE,
                reason_codes=("validation.unrecognized-advisory-status",),
            ),
        )
    )

    outcome = reader.read_candidate_evidence_detailed(REPOSITORY, ISSUE_NUMBER)

    assert outcome.evidence is None
    assert outcome.failure_reason == REASON_COMPOSITION_CONTRACT_VIOLATION
    assert outcome.failure_detail


def test_malformed_issue_payload_fails_closed_as_contract_violation() -> None:
    reader = make_reader(issue_transport=ok_transport(state="weird"))

    outcome = reader.read_candidate_evidence_detailed(REPOSITORY, ISSUE_NUMBER)

    assert outcome.evidence is None
    assert outcome.failure_reason == REASON_COMPOSITION_CONTRACT_VIOLATION


def test_outcome_requires_exactly_one_branch() -> None:
    with pytest.raises(ValueError):
        CandidateEvidenceReadOutcome(evidence=None, failure_reason=None)
    with pytest.raises(ValueError):
        CandidateEvidenceReadOutcome(
            evidence=make_reader().read_candidate_evidence(REPOSITORY, ISSUE_NUMBER),
            failure_reason=REASON_MISSING_REQUESTED_MODE,
        )


def test_bundle_rejects_malformed_required_shapes() -> None:
    with pytest.raises(ValueError):
        LiveCandidateEvidence(**base_bundle_kwargs(repository="not-owner-name-form"))
    with pytest.raises(TypeError):
        LiveCandidateEvidence(**base_bundle_kwargs(issue_transport=None))
    with pytest.raises(TypeError):
        LiveCandidateEvidence(**base_bundle_kwargs(dependency_depth="0"))
    with pytest.raises(TypeError):
        LiveCandidateEvidence(**base_bundle_kwargs(substitutable=1))


def test_supplied_claims_compose_through_operational_state() -> None:
    claim = PrimaryIssueClaim(
        pull_request_number=1360,
        branch="agent/1359-validation-timing",
        head_sha="b" * 40,
        state="merged",
    )
    reader = make_reader(primary_claims=(claim,))

    evidence = reader.read_candidate_evidence(REPOSITORY, ISSUE_NUMBER)

    assert type(evidence) is CandidateIssueEvidence
    assert evidence.operational_state.primary_claim_ids == (claim.claim_id,)


def test_reader_composes_through_real_shadow_seam_to_selected() -> None:
    """End-to-end: the production reader feeds the real post-#3326 shadow seam.

    A complete fixture evidence bundle yields a real read-only
    ``ShadowIssueSelectionResult.SELECTED`` with zero mutation; the repository
    SHA and the content-addressed issue revision stay distinct through the
    seam's own revision joins.
    """
    from agent_os_execution_service.shadow_issue_selection import (
        ShadowSelectionStatus,
        select_shadow_issue,
    )
    from scripts.agent_os_github_issue_provider.revision import issue_source_revision
    from scripts.agent_os_issue_acceptance.github_issue_source import (
        GitHubIssuePageResponse,
    )

    payload = issue_item()
    revision = issue_source_revision(payload)
    page_item = dict(payload)
    page_item["source_revision"] = revision

    class _PageReader:
        def read_issue_page(self, repository, *, page, per_page, state):
            return GitHubIssuePageResponse(
                items=(page_item,),
                next_page=None,
                complete=True,
                terminal_page_proven=True,
            )

    reader = make_reader(
        approval_applicability=ApprovalApplicabilityResult(
            status="applicable",
            approval_id=None,
            approval_revision="approval:" + "d" * 64,
            current_proposal_id=None,
            reason_codes=(),
            changed_bindings=(),
            approval_applicable=True,
        ),
        substitutable=True,
    )
    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at="2026-10-05T18:00:00Z",
        campaign_id="test-campaign",
        page_reader=_PageReader(),
        issue_transport=ok_transport(),
        candidate_evidence_reader=reader,
    )
    assert result.status is ShadowSelectionStatus.SELECTED
    assert result.selected_issue_number == ISSUE_NUMBER
    assert result.selected_issue_revision == revision
    assert result.repository_source_revision == SHA
    assert result.reason_codes == ("shadow-selection.current",)
    assert result.execution_authorized is False
    assert result.side_effects_performed is False
