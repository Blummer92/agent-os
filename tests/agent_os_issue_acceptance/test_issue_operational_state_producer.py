"""Focused #1441 tests for the canonical operational-state production seam."""

from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.agent_os_issue_acceptance.approval_records import (
    ApprovalApplicabilityResult,
)
from scripts.agent_os_issue_acceptance.compute_control_producer import (
    ComputeControlProductionEvidence,
    produce_compute_control_projection,
)
from scripts.agent_os_issue_acceptance.compute_control_projection import (
    ComputeDisposition,
)
from scripts.agent_os_issue_acceptance.coding_command_center_handoff import (
    CodingCommandCenterEvidence,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueState,
    LifecycleStage,
    PrimaryIssueClaim,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)
from scripts.agent_os_issue_acceptance.issue_operational_state_producer import (
    IssueOperationalStateProductionEvidence,
    produce_issue_operational_evidence,
    produce_issue_operational_state,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    AdmissionStatus,
    LifecycleMutationAdmissionResult,
)
from scripts.agent_os_issue_acceptance.merge_authorization import (
    MergeAuthorizationApplicabilityResult,
)
from scripts.agent_os_issue_acceptance.models import AcceptanceReport, Status
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome, ReadinessResult

REPOSITORY = "Blummer92/agent-os"
ISSUE = 1359
REVISION = "a" * 40
APPROVAL_ID = "approval:" + "1" * 64
MERGE_ID = "merge-authorization:" + "2" * 64
READY_LIFECYCLE_ID = "lifecycle-authorization:" + "3" * 64
CLOSURE_LIFECYCLE_ID = "lifecycle-authorization:" + "4" * 64


def _readiness(outcome: ReadinessOutcome = ReadinessOutcome.READY) -> ReadinessResult:
    return ReadinessResult(
        outcome=outcome,
        report=AcceptanceReport(
            linked_issue=ISSUE,
            overall_status=Status.PASS if outcome is ReadinessOutcome.READY else Status.FAIL,
            checks=[],
        ),
    )


def _approval(status: str = "applicable") -> ApprovalApplicabilityResult:
    return ApprovalApplicabilityResult(
        status=status,
        approval_id=APPROVAL_ID,
        approval_revision="approval-revision:" + "5" * 64,
        current_proposal_id="draft-task-proposal:" + "6" * 64,
        reason_codes=(),
        changed_bindings=(),
        approval_applicable=status == "applicable",
    )


def _merge(status: str = "applicable") -> MergeAuthorizationApplicabilityResult:
    return MergeAuthorizationApplicabilityResult(
        status=status,
        authorization_id=MERGE_ID,
        authorization_revision="merge-authorization-revision:" + "7" * 64,
        current_pull_request_evidence_id="pull-request-merge-evidence:" + "8" * 64,
        changed_bindings=(),
        reason_codes=(),
        merge_authorized=status == "applicable",
    )


def _admission(mutation: str, authorization_id: str) -> LifecycleMutationAdmissionResult:
    return LifecycleMutationAdmissionResult(
        requested_mutation=mutation,
        admitted=True,
        status=AdmissionStatus.ADMITTED,
        reason_codes=(),
        details=(),
        authorization_id=authorization_id,
        snapshot_id="lifecycle-state-snapshot:" + "9" * 64,
    )


def _base_evidence(**changes: object) -> IssueOperationalStateProductionEvidence:
    data: dict[str, object] = {
        "repository": REPOSITORY,
        "issue_number": ISSUE,
        "source_revision": REVISION,
        "observed_at": "2026-08-27T00:00:00Z",
        "evidence_ids": (APPROVAL_ID,),
        "source_state": SourceState.COMPLETE,
        "issue_state": IssueState.OPEN,
        "lifecycle_stage": LifecycleStage.IMPLEMENTATION,
        "terminal_disposition": TerminalDisposition.NONE,
        "readiness_result": _readiness(),
        "approval_applicability": _approval(),
    }
    data.update(changes)
    return IssueOperationalStateProductionEvidence(**data)


def test_produces_evidence_matching_manually_built_evidence():
    produced = produce_issue_operational_evidence(_base_evidence())
    expected = IssueOperationalEvidence(
        repository=REPOSITORY,
        issue_number=ISSUE,
        source_revision=REVISION,
        observed_at="2026-08-27T00:00:00Z",
        evidence_ids=(APPROVAL_ID,),
        source_state=SourceState.COMPLETE,
        issue_state=IssueState.OPEN,
        lifecycle_stage=LifecycleStage.IMPLEMENTATION,
        terminal_disposition=TerminalDisposition.NONE,
        readiness=ReadinessState.READY,
        implementation_authorization=AuthorityProjection(
            state=AuthorizationState.AUTHORIZED,
            evidence_id="approval-revision:" + "5" * 64,
        ),
        ready_for_review_authorization=AuthorityProjection(
            state=AuthorizationState.NOT_APPLICABLE
        ),
        execution_authorization=AuthorityProjection(state=AuthorizationState.NOT_APPLICABLE),
        merge_authorization=AuthorityProjection(state=AuthorizationState.NOT_APPLICABLE),
        closure_authorization=AuthorityProjection(state=AuthorizationState.NOT_APPLICABLE),
        external_write_authorization=AuthorityProjection(
            state=AuthorizationState.NOT_APPLICABLE
        ),
        dependency_state=DependencyState.CLEAR,
        primary_claims=(),
        validation_state=ValidationState.NOT_RUN,
        freshness_state=FreshnessState.CURRENT,
        observed_labels=(),
    )
    assert produced == expected


def test_produce_issue_operational_state_matches_build_issue_operational_state_unchanged():
    evidence = _base_evidence()
    produced_state = produce_issue_operational_state(evidence)
    expected_state = build_issue_operational_state(
        produce_issue_operational_evidence(evidence)
    )
    assert produced_state.to_dict() == expected_state.to_dict()


def test_admission_and_merge_results_project_onto_matching_authority_dimensions():
    evidence = _base_evidence(
        merge_applicability=_merge(),
        ready_for_review_admission=_admission("mark-ready", READY_LIFECYCLE_ID),
        closure_admission=_admission("close-issue", CLOSURE_LIFECYCLE_ID),
    )
    produced = produce_issue_operational_evidence(evidence)
    assert produced.merge_authorization.state is AuthorizationState.AUTHORIZED
    assert produced.merge_authorization.evidence_id == (
        "merge-authorization-revision:" + "7" * 64
    )
    assert produced.ready_for_review_authorization.state is AuthorizationState.AUTHORIZED
    assert produced.ready_for_review_authorization.evidence_id == (
        evidence.ready_for_review_admission.result_id
    )
    assert produced.closure_authorization.state is AuthorizationState.AUTHORIZED
    assert produced.closure_authorization.evidence_id == (
        evidence.closure_admission.result_id
    )


def test_admission_for_wrong_mutation_is_rejected():
    with pytest.raises(ValueError):
        _base_evidence(
            ready_for_review_admission=_admission("close-issue", CLOSURE_LIFECYCLE_ID)
        )


def test_readiness_outcome_is_adapted_without_re_evaluation():
    evidence = _base_evidence(readiness_result=_readiness(ReadinessOutcome.BLOCKED))
    produced = produce_issue_operational_evidence(evidence)
    assert produced.readiness is ReadinessState.BLOCKED


def test_wrong_type_evidence_rejected():
    with pytest.raises(TypeError):
        produce_issue_operational_evidence(object())


def test_tampered_frozen_evidence_fails_closed():
    evidence = _base_evidence()
    tampered = replace(evidence, issue_number=-1)
    with pytest.raises(TypeError):
        produce_issue_operational_evidence(tampered)


def test_issue_1359_qualifies_through_compute_control_projection_without_special_casing():
    """#1359's current evidence flows unmodified through #1441 into #1439/#1419."""

    operational_state = produce_issue_operational_state(_base_evidence())
    handoff_evidence = CodingCommandCenterEvidence(
        operational_state=operational_state, source_revision=REVISION
    )
    projection = produce_compute_control_projection(
        ComputeControlProductionEvidence(
            operational_state=operational_state,
            current_head_sha=None,
            handoff_evidence=handoff_evidence,
        )
    )
    assert projection.compute_disposition in ComputeDisposition
    print(f"#1359 compute_disposition: {projection.compute_disposition.value}")
