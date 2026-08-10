from __future__ import annotations

import pytest

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
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    AdmissionStatus,
    LifecycleMutationAdmissionResult,
    LifecycleStateSnapshot,
)
from scripts.agent_os_issue_acceptance.lifecycle_reconciliation import (
    ActionCategory,
    DependencyDisposition,
    DependencyEvidence,
    ExactHeadEvidence,
    LifecycleReconciliationInput,
    ProjectionEvidence,
    ProjectionSurface,
    PullRequestEvidence,
    PullRequestState,
    ReconciliationOutcome,
    reconcile_lifecycle,
    serialize_lifecycle_reconciliation_input,
    serialize_lifecycle_reconciliation_result,
)

SOURCE = "a" * 40
HEAD = "b" * 40
OLD_HEAD = "c" * 40
APPROVAL = "approval:" + "1" * 64
EVIDENCE = "issueplan-current-state:" + "2" * 64


def authority(state: AuthorizationState) -> AuthorityProjection:
    return AuthorityProjection(
        state=state,
        evidence_id=APPROVAL if state in {AuthorizationState.AUTHORIZED, AuthorizationState.STALE} else None,
    )


def state(*, readiness=ReadinessState.READY, dependency=DependencyState.CLEAR, claims=(), issue_state=IssueState.OPEN, terminal=TerminalDisposition.NONE, closure=AuthorizationState.NOT_AUTHORIZED):
    return build_issue_operational_state(
        IssueOperationalEvidence(
            repository="Blummer92/agent-os",
            issue_number=996,
            source_revision=SOURCE,
            observed_at="2026-08-09T17:10:00Z",
            evidence_ids=(EVIDENCE,),
            source_state=SourceState.COMPLETE,
            issue_state=issue_state,
            lifecycle_stage=LifecycleStage.IMPLEMENTATION if issue_state is IssueState.OPEN else LifecycleStage.CLOSED,
            terminal_disposition=terminal,
            readiness=readiness,
            implementation_authorization=authority(AuthorizationState.AUTHORIZED),
            ready_for_review_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            execution_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            merge_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            closure_authorization=authority(closure),
            external_write_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            dependency_state=dependency,
            primary_claims=claims,
            validation_state=ValidationState.NOT_RUN,
            freshness_state=FreshnessState.CURRENT,
            observed_labels=("status:ready",),
        )
    )


def claim(number=997, *, value="draft", head=HEAD, branch="agent/996-lifecycle-reconciliation"):
    return PrimaryIssueClaim(pull_request_number=number, branch=branch, head_sha=head, state=value)


def pr(*, value=PullRequestState.DRAFT, head=HEAD):
    return PullRequestEvidence(997, "agent/996-lifecycle-reconciliation", head, value, "pr:997")


def snapshot(*, status="status:ready", value="draft", merged=False, head=HEAD):
    return LifecycleStateSnapshot(
        repository="Blummer92/agent-os", issue_number=996,
        pull_request_number=997 if value != "none" else None,
        source_head=head if value != "none" else None, base_head=SOURCE,
        pr_state=value, merged=merged, issue_state="open", review_state="clear",
        unresolved_threads=0, lifecycle_labels=(status,), observed_revision="revision-1",
    )


def input_for(current_state, **changes):
    data = {"repository": "Blummer92/agent-os", "issue_number": 996, "operational_state": current_state}
    data.update(changes)
    return LifecycleReconciliationInput(**data)


def test_completed_dependency_still_projected_as_blocking_is_repaired():
    evidence = input_for(state(), dependencies=(DependencyEvidence(934, DependencyDisposition.COMPLETED, "issue:934"),), projections=(ProjectionEvidence(ProjectionSurface.ROADMAP, "roadmap:330", blocked_dependencies=(934,)),))
    result = reconcile_lifecycle(evidence)
    assert result.outcome is ReconciliationOutcome.REQUIRED
    assert "projection.completed-dependency-blocker" in result.reason_codes
    assert result.actions[0].category is ActionCategory.PROJECTION_REPAIR


def test_active_draft_pr_overrides_stale_blocked_issue_projection():
    current = state(claims=(claim(),))
    result = reconcile_lifecycle(input_for(current, lifecycle_snapshot=snapshot(), current_pull_request=pr(), projections=(ProjectionEvidence(ProjectionSurface.ISSUE_BODY, "issue-body:996", readiness=ReadinessState.BLOCKED),)))
    assert result.outcome is ReconciliationOutcome.REQUIRED
    assert "projection.readiness-stale" in result.reason_codes
    assert result.actions[0].expected == "ready"


def test_old_exact_head_validation_becomes_stale_after_new_commit():
    current = state(claims=(claim(),))
    result = reconcile_lifecycle(input_for(current, lifecycle_snapshot=snapshot(), current_pull_request=pr(), exact_head_evidence=(ExactHeadEvidence("validation:old", OLD_HEAD),)))
    action = next(item for item in result.actions if item.reason_code == "validation.exact-head-stale")
    assert action.observed == OLD_HEAD
    assert action.expected == HEAD
    assert action.category is ActionCategory.OBSERVATION


def test_ready_for_review_fact_does_not_grant_merge_authority():
    current = state(claims=(claim(value="ready"),))
    result = reconcile_lifecycle(input_for(current, lifecycle_snapshot=snapshot(value="ready"), current_pull_request=pr(value=PullRequestState.READY)))
    assert result.outcome is ReconciliationOutcome.CONSISTENT
    assert result.merge_authorization is AuthorizationState.NOT_AUTHORIZED
    assert result.side_effects_performed is False


def test_merged_pr_open_issue_requires_closure_authority_and_admission():
    current = state(claims=(claim(value="merged"),))
    result = reconcile_lifecycle(input_for(current, lifecycle_snapshot=snapshot(value="ready", merged=True), current_pull_request=pr(value=PullRequestState.MERGED)))
    assert result.outcome is ReconciliationOutcome.REQUIRED
    assert "lifecycle.merged-pr-open-issue" in result.reason_codes
    assert "authorization.closure-required" in result.reason_codes
    assert "authorization.lifecycle-admission-required" in result.reason_codes
    action = next(item for item in result.actions if item.reason_code == "lifecycle.merged-pr-open-issue")
    assert action.required_mutation == "close-issue"
    assert action.authorization_id is None
    assert action.admission_result_id is None


def test_closed_superseded_pr_projected_active_is_projection_repair():
    current = state()
    result = reconcile_lifecycle(input_for(current, lifecycle_snapshot=snapshot(value="none", head=HEAD), current_pull_request=pr(value=PullRequestState.CLOSED_SUPERSEDED), projections=(ProjectionEvidence(ProjectionSurface.PR_DESCRIPTION, "pr-body:997", pull_request_number=997, pull_request_state=PullRequestState.READY),)))
    assert "claim.closed-pr-projected-active" in result.reason_codes
    assert result.outcome is ReconciliationOutcome.REQUIRED


def test_duplicate_primary_claims_fail_closed_to_needs_decision():
    current = state(claims=(claim(), claim(998, branch="agent/996-other", head="d" * 40)))
    result = reconcile_lifecycle(input_for(current))
    assert result.outcome is ReconciliationOutcome.NEEDS_DECISION
    assert "claim.multiple-primary" in result.reason_codes
    assert len(result.actions) == 1
    assert result.actions[0].category is ActionCategory.MANUAL_DECISION


def test_stale_lifecycle_label_requires_existing_admission_not_inferred_authority():
    current = state(claims=(claim(),))
    result = reconcile_lifecycle(input_for(current, lifecycle_snapshot=snapshot(status="status:blocked"), current_pull_request=pr()))
    assert "lifecycle.status-label-stale" in result.reason_codes
    assert "authorization.lifecycle-admission-required" in result.reason_codes
    action = next(item for item in result.actions if item.reason_code == "lifecycle.status-label-stale")
    assert action.category is ActionCategory.GOVERNED_MUTATION
    assert action.admission_result_id is None
    assert f"operational-state-id={current.state_id}" in action.expected_state_guards
    assert f"pr-head={HEAD}" in action.expected_state_guards


def test_matching_lifecycle_admission_is_preserved_on_recommendation():
    current = state(claims=(claim(),))
    snap = snapshot(status="status:blocked")
    admission = LifecycleMutationAdmissionResult(requested_mutation="replace-lifecycle-labels", admitted=True, status=AdmissionStatus.ADMITTED, reason_codes=(), details=(), authorization_id="lifecycle-authorization:1", snapshot_id=snap.snapshot_id)
    result = reconcile_lifecycle(input_for(current, lifecycle_snapshot=snap, current_pull_request=pr(), admissions=(admission,)))
    action = next(item for item in result.actions if item.reason_code == "lifecycle.status-label-stale")
    assert action.admission_result_id == admission.result_id
    assert "authorization.lifecycle-admission-required" not in result.reason_codes


def test_conflicting_dependency_evidence_fails_closed():
    current = state()
    result = reconcile_lifecycle(input_for(current, dependencies=(DependencyEvidence(934, DependencyDisposition.COMPLETED, "one"), DependencyEvidence(934, DependencyDisposition.INCOMPLETE, "two"))))
    assert result.outcome is ReconciliationOutcome.NEEDS_DECISION
    assert "source.conflicting-dependency-evidence" in result.reason_codes


def test_merged_implementation_and_stale_roadmap_are_both_reported():
    current = state(claims=(claim(value="merged"),))
    result = reconcile_lifecycle(input_for(current, lifecycle_snapshot=snapshot(value="ready", merged=True), current_pull_request=pr(value=PullRequestState.MERGED), dependencies=(DependencyEvidence(934, DependencyDisposition.COMPLETED, "issue:934"),), projections=(ProjectionEvidence(ProjectionSurface.ROADMAP, "roadmap:330", blocked_dependencies=(934,)),)))
    assert "projection.completed-dependency-blocker" in result.reason_codes
    assert "lifecycle.merged-pr-open-issue" in result.reason_codes


def test_projection_and_exact_head_evidence_validate_nested_values():
    with pytest.raises(TypeError):
        ProjectionEvidence(ProjectionSurface.ROADMAP, "roadmap:330", readiness="ready")
    with pytest.raises(TypeError):
        ProjectionEvidence(ProjectionSurface.PR_DESCRIPTION, "pr:997", pull_request_state="ready")
    with pytest.raises(ValueError):
        ProjectionEvidence(ProjectionSurface.PR_DESCRIPTION, "pr:997", head_sha="not-a-sha")
    with pytest.raises(ValueError):
        ExactHeadEvidence("validation:bad", "not-a-sha")


def test_mismatched_closure_admission_authorization_fails_closed():
    current = state(claims=(claim(value="merged"),), closure=AuthorizationState.AUTHORIZED)
    snap = snapshot(value="ready", merged=True)
    admission = LifecycleMutationAdmissionResult(requested_mutation="close-issue", admitted=True, status=AdmissionStatus.ADMITTED, reason_codes=(), details=(), authorization_id="different-authorization", snapshot_id=snap.snapshot_id)
    result = reconcile_lifecycle(input_for(current, lifecycle_snapshot=snap, current_pull_request=pr(value=PullRequestState.MERGED), admissions=(admission,)))
    assert result.outcome is ReconciliationOutcome.NEEDS_DECISION
    assert "source.conflicting-admission-evidence" in result.reason_codes
    assert result.actions[0].category is ActionCategory.MANUAL_DECISION


def test_equivalent_supplied_evidence_is_deterministic_and_authority_preserving():
    current = state(claims=(claim(),))
    projections_a = (
        ProjectionEvidence(ProjectionSurface.ROADMAP, "roadmap:330", blocked_dependencies=(934,)),
        ProjectionEvidence(ProjectionSurface.PR_DESCRIPTION, "pr-body:997", pull_request_number=997, head_sha=OLD_HEAD),
    )
    projections_b = tuple(reversed(projections_a))
    heads_a = (ExactHeadEvidence("validation:old-2", "d" * 40), ExactHeadEvidence("validation:old", OLD_HEAD))
    heads_b = tuple(reversed(heads_a))
    dependencies_a = (DependencyEvidence(935, DependencyDisposition.INCOMPLETE, "b"), DependencyEvidence(934, DependencyDisposition.COMPLETED, "a"))
    dependencies_b = tuple(reversed(dependencies_a))
    a = input_for(current, lifecycle_snapshot=snapshot(), current_pull_request=pr(), dependencies=dependencies_a, projections=projections_a, exact_head_evidence=heads_a)
    b = input_for(current, lifecycle_snapshot=snapshot(), current_pull_request=pr(), dependencies=dependencies_b, projections=projections_b, exact_head_evidence=heads_b)
    ra, rb = reconcile_lifecycle(a), reconcile_lifecycle(b)
    assert ra.actions
    assert a.input_id == b.input_id
    assert serialize_lifecycle_reconciliation_input(a) == serialize_lifecycle_reconciliation_input(b)
    assert ra.result_id == rb.result_id
    assert serialize_lifecycle_reconciliation_result(ra) == serialize_lifecycle_reconciliation_result(rb)
    assert ra.implementation_authorization is current.implementation_authorization.state
    assert ra.merge_authorization is current.merge_authorization.state
    assert ra.closure_authorization is current.closure_authorization.state
    assert ra.external_write_authorization is current.external_write_authorization.state