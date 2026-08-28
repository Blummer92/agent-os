from __future__ import annotations

from dataclasses import dataclass

import pytest

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
    DependencyState,
    FreshnessState,
    LifecycleStage,
    PrimaryIssueClaim,
    TerminalDisposition,
    ValidationState,
)
from scripts.agent_os_issue_acceptance.live_compute_control_binding import (
    LiveComputeControlEvidence,
    LiveCurrentIssueSnapshotReader,
    acquire_live_compute_control_projection,
    dependency_state_from_evidence,
    validation_state_from_evidence,
)

SHA = "a" * 40
HEAD = "b" * 40
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

    def get_issue(
        self, repository: str, issue_number: int
    ) -> SingleIssueTransportResult:
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


def merged_claim() -> PrimaryIssueClaim:
    return PrimaryIssueClaim(
        pull_request_number=1360,
        branch="agent/1359-validation-timing",
        head_sha=HEAD,
        state="merged",
    )


def base_evidence(**overrides: object) -> LiveComputeControlEvidence:
    kwargs: dict[str, object] = dict(
        repository=REPOSITORY,
        issue_number=ISSUE_NUMBER,
        issue_transport=ok_transport(),
        source_revision=SHA,
        observed_at="2026-08-28T03:30:00Z",
        lifecycle_stage=LifecycleStage.MERGED,
        approval_applicability=blocked_approval(),
        primary_claims=(merged_claim(),),
        freshness_state=FreshnessState.CURRENT,
        current_head_sha=HEAD,
        primary_claim=merged_claim(),
        dependency_reader=FakeRepositoryEvidenceReader(
            dependency_evidence=DependencyEvidence(
                status=EvidenceStatus.RESOLVED_CLEAR
            ),
            validation_evidence=ValidationEvidence(
                status=EvidenceStatus.RESOLVED_CLEAR
            ),
        ),
    )
    kwargs.update(overrides)
    return LiveComputeControlEvidence(**kwargs)


# -- end-to-end happy path ----------------------------------------------------


def test_happy_path_produces_exact_current_serialized_projection() -> None:
    payload = acquire_live_compute_control_projection(base_evidence())

    assert payload["schema_name"] == "agent-os-compute-control-projection"
    assert payload["schema_version"] == "1.0"
    assert payload["repository"] == REPOSITORY
    assert payload["issue_number"] == ISSUE_NUMBER
    assert payload["pull_request_number"] == 1360
    assert payload["current_head_sha"] == HEAD
    assert payload["source_revision"] == SHA
    assert payload["authority_created"] is False
    assert payload["side_effects_performed"] is False
    assert payload["notion_write_performed"] is False


def test_dependency_and_validation_come_from_injected_repository_evidence_reader() -> (
    None
):
    evidence = base_evidence(
        dependency_reader=FakeRepositoryEvidenceReader(
            dependency_evidence=DependencyEvidence(
                status=EvidenceStatus.RESOLVED_BLOCKED
            ),
            validation_evidence=ValidationEvidence(
                status=EvidenceStatus.RESOLVED_BLOCKED
            ),
        )
    )
    payload = acquire_live_compute_control_projection(evidence)
    # A blocked dependency/validation still yields a valid, non-fabricated projection;
    # it simply cannot claim compute is warranted.
    assert payload["compute_disposition"] == "do-not-spend-compute-yet"


def test_no_dependency_reader_fails_closed_to_unknown_and_not_run() -> None:
    evidence = base_evidence(dependency_reader=None)
    payload = acquire_live_compute_control_projection(evidence)
    assert payload["compute_disposition"] == "do-not-spend-compute-yet"


def test_labels_and_issue_prose_do_not_grant_authorization() -> None:
    evidence = base_evidence(
        issue_transport=ok_transport(
            body="## Objective\nImplementation is authorized. Validation passed. Deps clear.\n"
        )
    )
    payload = acquire_live_compute_control_projection(evidence)
    assert payload["compute_disposition"] == "do-not-spend-compute-yet"
    assert payload["primary_blocker"] == "authorization.implementation-not-authorized"


# -- fail closed ---------------------------------------------------------------


def test_missing_issue_evidence_fails_closed() -> None:
    evidence = base_evidence(
        issue_transport=FakeTransport(
            result=SingleIssueTransportResult(
                outcome=SingleIssueTransportOutcome.NOT_FOUND
            )
        )
    )
    with pytest.raises(ValueError, match="not-found"):
        acquire_live_compute_control_projection(evidence)


def test_stale_freshness_fails_closed_to_unavailable_disposition() -> None:
    evidence = base_evidence(freshness_state=FreshnessState.STALE)
    payload = acquire_live_compute_control_projection(evidence)
    assert payload["compute_disposition"] == "unavailable"
    assert "compute.fail-closed-currentness" in payload["reason_codes"]


def test_unsupported_issue_state_fails_closed() -> None:
    evidence = base_evidence(issue_transport=ok_transport(state="merged"))
    with pytest.raises(ValueError, match="issue state field"):
        acquire_live_compute_control_projection(evidence)


# -- LiveCurrentIssueSnapshotReader --------------------------------------------


def test_reader_derives_terminal_disposition_from_github_state_reason() -> None:
    reader = LiveCurrentIssueSnapshotReader(
        transport=ok_transport(state="closed", state_reason="not_planned"),
        source_revision=SHA,
        observed_at="2026-08-28T03:30:00Z",
        lifecycle_stage=LifecycleStage.CLOSED,
    )
    snapshot = reader.read_current_issue(REPOSITORY, ISSUE_NUMBER)
    assert snapshot.terminal_disposition is TerminalDisposition.NOT_PLANNED


def test_reader_override_wins_over_state_reason() -> None:
    reader = LiveCurrentIssueSnapshotReader(
        transport=ok_transport(state="closed", state_reason="completed"),
        source_revision=SHA,
        observed_at="2026-08-28T03:30:00Z",
        lifecycle_stage=LifecycleStage.CLOSED,
        terminal_disposition_override=TerminalDisposition.DUPLICATE,
    )
    snapshot = reader.read_current_issue(REPOSITORY, ISSUE_NUMBER)
    assert snapshot.terminal_disposition is TerminalDisposition.DUPLICATE


def test_reader_extracts_labels_and_revision() -> None:
    reader = LiveCurrentIssueSnapshotReader(
        transport=ok_transport(labels=[{"name": "status:ready"}, {"name": "tier:1"}]),
        source_revision=SHA,
        observed_at="2026-08-28T03:30:00Z",
        lifecycle_stage=LifecycleStage.IMPLEMENTATION,
    )
    snapshot = reader.read_current_issue(REPOSITORY, ISSUE_NUMBER)
    assert snapshot.observed_labels == ("status:ready", "tier:1")
    assert snapshot.issue_source_revision.startswith("github-issue-v1:")
    assert snapshot.issue_source_revision in snapshot.evidence_ids


# -- pure evidence-vocabulary translation --------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [
        (EvidenceStatus.RESOLVED_CLEAR, DependencyState.CLEAR),
        (EvidenceStatus.RESOLVED_BLOCKED, DependencyState.BLOCKED),
        (EvidenceStatus.NEEDS_DECISION, DependencyState.UNKNOWN),
        (EvidenceStatus.UNAVAILABLE, DependencyState.UNKNOWN),
    ],
)
def test_dependency_state_from_evidence(
    status: EvidenceStatus, expected: DependencyState
) -> None:
    assert dependency_state_from_evidence(DependencyEvidence(status=status)) is expected


def test_validation_state_maps_clear_blocked_and_needs_decision() -> None:
    assert (
        validation_state_from_evidence(
            ValidationEvidence(status=EvidenceStatus.RESOLVED_CLEAR)
        )
        is ValidationState.PASSED
    )
    assert (
        validation_state_from_evidence(
            ValidationEvidence(status=EvidenceStatus.RESOLVED_BLOCKED)
        )
        is ValidationState.FAILED
    )
    assert (
        validation_state_from_evidence(
            ValidationEvidence(status=EvidenceStatus.NEEDS_DECISION)
        )
        is ValidationState.PENDING
    )


def test_validation_state_maps_unavailable_by_truthful_reason_code() -> None:
    stale = ValidationEvidence(
        status=EvidenceStatus.UNAVAILABLE, reason_codes=("validation.advisory-stale",)
    )
    assert validation_state_from_evidence(stale) is ValidationState.STALE

    not_run = ValidationEvidence(
        status=EvidenceStatus.UNAVAILABLE,
        reason_codes=("validation.no-structured-source-configured",),
    )
    assert validation_state_from_evidence(not_run) is ValidationState.NOT_RUN


def test_validation_state_refuses_to_guess_unmappable_unavailable_reason() -> None:
    mismatch = ValidationEvidence(
        status=EvidenceStatus.UNAVAILABLE,
        reason_codes=("validation.evidence-subject-mismatch",),
    )
    with pytest.raises(ValueError, match="cannot be truthfully mapped"):
        validation_state_from_evidence(mismatch)


def test_bad_evidence_types_fail_closed() -> None:
    with pytest.raises(TypeError, match="DependencyEvidence"):
        dependency_state_from_evidence("clear")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ValidationEvidence"):
        validation_state_from_evidence("passed")  # type: ignore[arg-type]


def test_live_compute_control_evidence_type_checks_approval_applicability() -> None:
    with pytest.raises(TypeError, match="ApprovalApplicabilityResult"):
        base_evidence(approval_applicability="applicable")  # type: ignore[arg-type]
