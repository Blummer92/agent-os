from __future__ import annotations

from scripts.agent_os_execution_checkpoint.models import CANONICAL_STAGE_ORDER
from scripts.agent_os_execution_checkpoint.resume_planner import (
    RESUME_PLAN_SCHEMA_NAME,
    RESUME_PLAN_SCHEMA_VERSION,
    ResumePlan,
    StageClassification,
    StageDecision,
)
from workflow_scheduler.execution.continuation import (
    ContinuationDisposition,
    ExistingExecutionIdentity,
    ExistingWorkEvidence,
    plan_execution_continuation,
)
from workflow_scheduler.execution.host_local_lease_adapter import HostLocalLeaseObservation
from workflow_scheduler.execution.single_issue_pilot import (
    PilotLeaseRequest,
    pilot_holder_identity,
    pilot_lease_identity,
)

SHA_A = "a" * 40
SHA_B = "b" * 40
BASE_A = "c" * 40
BASE_B = "d" * 40


def _identity(**overrides) -> ExistingExecutionIdentity:
    values = dict(
        repository="Blummer92/agent-os",
        issue_number=1188,
        branch="agent/1188-execution-continuation",
        base_sha=BASE_A,
        head_sha=SHA_A,
        invocation_id="invocation-1188",
        execution_id="execution-1188",
        candidate_identity="candidate:1188",
        checkpoint_lineage_identity="checkpoint-lineage:1188",
        authorization_identity="authorization:1188",
        executor_identity="governed-runner",
        scope_identity="scope:1188",
    )
    values.update(overrides)
    return ExistingExecutionIdentity(**values)


def _plan(*, classification: StageClassification = StageClassification.RERUN_REQUIRED) -> ResumePlan:
    decisions = tuple(
        StageDecision(
            stage=stage,
            classification=classification,
            evidence_checkpoint_id=None,
            reason="fixture",
        )
        for stage in CANONICAL_STAGE_ORDER
    )
    return ResumePlan(
        schema_name=RESUME_PLAN_SCHEMA_NAME,
        schema_version=RESUME_PLAN_SCHEMA_VERSION,
        repository="Blummer92/agent-os",
        issue_number=1188,
        execution_id="execution-1188",
        stage_decisions=decisions,
        resume_point=CANONICAL_STAGE_ORDER[0],
        evaluated_at="2026-08-15T22:00:00Z",
    )


def _work(**overrides) -> ExistingWorkEvidence:
    values = dict(
        repository="Blummer92/agent-os",
        issue_number=1188,
        branch="agent/1188-execution-continuation",
        current_base_sha=BASE_A,
        current_head_sha=SHA_A,
        primary_pr_count=1,
        branch_present=True,
        draft_pr_present=True,
        checkpoint_lineage_present=True,
        authorization_applicable=True,
        authorization_current=True,
        source_of_truth_current=True,
        ownership_current=True,
        scope_current=True,
        excluded_surface_present=False,
        head_advance_in_scope=True,
        existing_execution=_identity(),
        base_behind=False,
        branch_conflicted=False,
    )
    values.update(overrides)
    return ExistingWorkEvidence(**values)


def _lease_request(*, source_head_sha: str = SHA_A) -> PilotLeaseRequest:
    return PilotLeaseRequest(
        repository="Blummer92/agent-os",
        issue_number=1188,
        invocation_id="invocation-1188",
        branch="agent/1188-execution-continuation",
        workspace_request_id="workspace-1188",
        projection_id="projection-1188",
        approval_id="approval-1188",
        source_head_sha=source_head_sha,
    )


def _inactive_lease(request: PilotLeaseRequest) -> HostLocalLeaseObservation:
    return HostLocalLeaseObservation(
        lease_identity=pilot_lease_identity(request),
        active=False,
        ambiguous=False,
        generation=2,
    )


def test_existing_valid_work_is_resumable_not_a_generic_stop() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(), resume_plan=_plan(), lease_request=request, lease_observation=_inactive_lease(request)
    )
    assert decision.disposition is ContinuationDisposition.RESUMABLE_EXISTING_WORK
    assert decision.execution_id == "execution-1188"
    assert decision.resume_point == CANONICAL_STAGE_ORDER[0].value
    assert "existing.resumable" in decision.reason_codes
    assert decision.continuation_authorized is False
    assert decision.retry_authorized is False


def test_active_canonical_execution_lease_blocks_duplicate_executor() -> None:
    request = _lease_request()
    observation = HostLocalLeaseObservation(
        lease_identity=pilot_lease_identity(request),
        active=True,
        ambiguous=False,
        generation=3,
        holder_identity=pilot_holder_identity(request),
    )
    decision = plan_execution_continuation(
        _work(), resume_plan=_plan(), lease_request=request, lease_observation=observation
    )
    assert decision.disposition is ContinuationDisposition.ACTIVE_CONFLICT
    assert "lease.active-canonical-holder" in decision.reason_codes
    assert "do not create duplicate work" in decision.recommended_action


def test_active_holder_drift_blocks_and_never_takes_over() -> None:
    request = _lease_request()
    observation = HostLocalLeaseObservation(
        lease_identity=pilot_lease_identity(request),
        active=True,
        ambiguous=False,
        generation=3,
        holder_identity="pilot-holder:" + "f" * 64,
    )
    decision = plan_execution_continuation(
        _work(), resume_plan=_plan(), lease_request=request, lease_observation=observation
    )
    assert decision.disposition is ContinuationDisposition.ACTIVE_CONFLICT
    assert "lease.active-holder-drift" in decision.reason_codes
    assert decision.retry_authorized is False


def test_lease_request_must_bind_discovered_execution_identity() -> None:
    request = _lease_request(source_head_sha=SHA_B)
    decision = plan_execution_continuation(
        _work(), resume_plan=_plan(), lease_request=request, lease_observation=_inactive_lease(request)
    )
    assert decision.disposition is ContinuationDisposition.NEEDS_DECISION
    assert "lease.request-identity-mismatch" in decision.reason_codes


def test_head_advanced_rebinds_when_scope_and_authorization_remain_valid() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(current_head_sha=SHA_B),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )
    assert decision.disposition is ContinuationDisposition.HEAD_ADVANCED
    assert decision.observed_head_sha == SHA_A
    assert decision.current_head_sha == SHA_B
    assert decision.resume_point is None
    assert "resume-plan.rebind-required" in decision.reason_codes
    assert "invalidate head-bound evidence" in decision.recommended_action


def test_head_advanced_outside_scope_fails_closed() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(current_head_sha=SHA_B, head_advance_in_scope=False),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )
    assert decision.disposition is ContinuationDisposition.SCOPE_DRIFT
    assert "head.advanced-out-of-scope" in decision.reason_codes


def test_base_behind_routes_to_1187_not_head_advanced() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(current_base_sha=BASE_B, base_behind=True),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )
    assert decision.disposition is ContinuationDisposition.STALE_EXISTING_WORK
    assert "branch.base-behind-route-gh-life3" in decision.reason_codes
    assert "#1187" in decision.recommended_action
    assert decision.branch_refresh_authorized is False


def test_duplicate_primary_prs_fail_closed() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(primary_pr_count=2),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )
    assert decision.disposition is ContinuationDisposition.NEEDS_DECISION
    assert "existing.multiple-primary-prs" in decision.reason_codes


def test_stale_authorization_reacquires_evidence_instead_of_inferencing_authority() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(authorization_current=False),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )
    assert decision.disposition is ContinuationDisposition.STALE_EXISTING_WORK
    assert "authorization.stale" in decision.reason_codes


def test_missing_current_lease_observation_is_stale_not_permission_to_run() -> None:
    decision = plan_execution_continuation(
        _work(), resume_plan=_plan(), lease_request=_lease_request(), lease_observation=None
    )
    assert decision.disposition is ContinuationDisposition.STALE_EXISTING_WORK
    assert "lease.current-observation-required" in decision.reason_codes


def test_ambiguous_orphaned_lease_requires_manual_review() -> None:
    request = _lease_request()
    observation = HostLocalLeaseObservation(
        lease_identity=pilot_lease_identity(request),
        active=True,
        ambiguous=True,
        generation=2,
        reason="orphan",
    )
    decision = plan_execution_continuation(
        _work(), resume_plan=_plan(), lease_request=request, lease_observation=observation
    )
    assert decision.disposition is ContinuationDisposition.NEEDS_DECISION
    assert "lease.ambiguous" in decision.reason_codes


def test_resume_plan_manual_review_remains_manual_review() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(),
        resume_plan=_plan(classification=StageClassification.MANUAL_REVIEW),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )
    assert decision.disposition is ContinuationDisposition.NEEDS_DECISION
    assert "resume-plan.manual-review" in decision.reason_codes


def test_resume_plan_must_bind_same_execution_lineage() -> None:
    request = _lease_request()
    different = _identity(execution_id="execution-other")
    decision = plan_execution_continuation(
        _work(existing_execution=different),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )
    assert decision.disposition is ContinuationDisposition.NEEDS_DECISION
    assert "resume-plan.identity-mismatch" in decision.reason_codes


def test_no_existing_work_continues_normal_lane_without_lease_requirement() -> None:
    decision = plan_execution_continuation(
        _work(
            primary_pr_count=0,
            branch_present=False,
            draft_pr_present=False,
            checkpoint_lineage_present=False,
            existing_execution=None,
        ),
        resume_plan=None,
        lease_request=None,
        lease_observation=None,
    )
    assert decision.disposition is ContinuationDisposition.NO_EXISTING_WORK
    assert decision.merge_authorized is False
    assert decision.issue_closure_authorized is False
