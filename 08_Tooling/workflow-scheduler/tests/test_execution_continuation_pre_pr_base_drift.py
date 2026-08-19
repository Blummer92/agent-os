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
BASE_A = "c" * 40
BASE_B = "d" * 40


def _identity() -> ExistingExecutionIdentity:
    return ExistingExecutionIdentity(
        repository="Blummer92/agent-os",
        issue_number=1209,
        branch="agent/1209-pre-pr-base-drift",
        base_sha=BASE_A,
        head_sha=SHA_A,
        invocation_id="invocation-1209",
        execution_id="execution-1209",
        candidate_identity="candidate:1209",
        checkpoint_lineage_identity="checkpoint-lineage:1209",
        authorization_identity="authorization:1209",
        executor_identity="governed-runner",
        scope_identity="scope:1209",
    )


def _plan() -> ResumePlan:
    decisions = tuple(
        StageDecision(
            stage=stage,
            classification=StageClassification.RERUN_REQUIRED,
            evidence_checkpoint_id=None,
            reason="fixture",
        )
        for stage in CANONICAL_STAGE_ORDER
    )
    return ResumePlan(
        schema_name=RESUME_PLAN_SCHEMA_NAME,
        schema_version=RESUME_PLAN_SCHEMA_VERSION,
        repository="Blummer92/agent-os",
        issue_number=1209,
        execution_id="execution-1209",
        stage_decisions=decisions,
        resume_point=CANONICAL_STAGE_ORDER[0],
        evaluated_at="2026-08-16T18:00:00Z",
    )


def _work(**overrides) -> ExistingWorkEvidence:
    values = dict(
        repository="Blummer92/agent-os",
        issue_number=1209,
        branch="agent/1209-pre-pr-base-drift",
        current_base_sha=BASE_B,
        current_head_sha=SHA_A,
        primary_pr_count=0,
        branch_present=True,
        draft_pr_present=False,
        checkpoint_lineage_present=True,
        authorization_applicable=True,
        authorization_current=True,
        source_of_truth_current=True,
        ownership_current=True,
        scope_current=True,
        excluded_surface_present=False,
        head_advance_in_scope=True,
        existing_execution=_identity(),
        base_behind=True,
        branch_conflicted=False,
    )
    values.update(overrides)
    return ExistingWorkEvidence(**values)


def _lease_request() -> PilotLeaseRequest:
    return PilotLeaseRequest(
        repository="Blummer92/agent-os",
        issue_number=1209,
        invocation_id="invocation-1209",
        branch="agent/1209-pre-pr-base-drift",
        workspace_request_id="workspace-1209",
        projection_id="projection-1209",
        approval_id="approval-1209",
        source_head_sha=SHA_A,
    )


def _inactive_lease(request: PilotLeaseRequest) -> HostLocalLeaseObservation:
    return HostLocalLeaseObservation(
        lease_identity=pilot_lease_identity(request),
        active=False,
        ambiguous=False,
        generation=2,
    )


def test_pre_pr_base_behind_replans_instead_of_routing_to_1187() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )

    assert decision.disposition is ContinuationDisposition.STALE_EXISTING_WORK
    assert "branch.base-behind-pre-pr-replan" in decision.reason_codes
    assert "#1187" in decision.recommended_action
    assert "do not invoke" in decision.recommended_action
    assert "developer-loop" in decision.recommended_action
    assert decision.branch_refresh_authorized is False
    assert decision.retry_authorized is False


def test_existing_primary_pr_base_behind_preserves_1187_route() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(primary_pr_count=1, draft_pr_present=True),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )

    assert decision.disposition is ContinuationDisposition.STALE_EXISTING_WORK
    assert "branch.base-behind-route-gh-life3" in decision.reason_codes
    assert "#1187" in decision.recommended_action
    assert "do not invoke" not in decision.recommended_action
    assert decision.branch_refresh_authorized is False


def test_non_draft_primary_pr_base_behind_still_preserves_1187_route() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(primary_pr_count=1, draft_pr_present=False),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )

    assert "branch.base-behind-route-gh-life3" in decision.reason_codes


def test_pre_pr_conflict_stops_before_base_drift_routing() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(branch_conflicted=True),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )

    assert decision.disposition is ContinuationDisposition.NEEDS_DECISION
    assert decision.reason_codes == ("branch.conflicted",)


def test_pre_pr_active_lease_remains_the_concurrency_authority() -> None:
    request = _lease_request()
    observation = HostLocalLeaseObservation(
        lease_identity=pilot_lease_identity(request),
        active=True,
        ambiguous=False,
        generation=3,
        holder_identity=pilot_holder_identity(request),
    )
    decision = plan_execution_continuation(
        _work(),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=observation,
    )

    assert decision.disposition is ContinuationDisposition.ACTIVE_CONFLICT
    assert "lease.active-canonical-holder" in decision.reason_codes
    assert decision.branch_refresh_authorized is False


def test_pre_pr_ambiguous_lease_never_becomes_permission_to_continue() -> None:
    request = _lease_request()
    observation = HostLocalLeaseObservation(
        lease_identity=pilot_lease_identity(request),
        active=True,
        ambiguous=True,
        generation=3,
        holder_identity=pilot_holder_identity(request),
        reason="ambiguous fixture",
    )
    decision = plan_execution_continuation(
        _work(),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=observation,
    )

    assert decision.disposition is ContinuationDisposition.NEEDS_DECISION
    assert decision.reason_codes == ("lease.ambiguous",)
    assert decision.branch_refresh_authorized is False


def test_pre_pr_stale_authorization_fails_before_base_drift_routing() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(authorization_current=False),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )

    assert decision.disposition is ContinuationDisposition.STALE_EXISTING_WORK
    assert decision.reason_codes == ("authorization.stale",)


def test_pre_pr_current_continues_developer_loop_without_pr_lifecycle_routing() -> None:
    request = _lease_request()
    decision = plan_execution_continuation(
        _work(base_behind=False, current_base_sha=BASE_A),
        resume_plan=_plan(),
        lease_request=request,
        lease_observation=_inactive_lease(request),
    )

    assert decision.disposition is ContinuationDisposition.RESUMABLE_EXISTING_WORK
    assert decision.reason_codes == ("existing.resumable", "lease.no-active-conflict")
    assert decision.resume_point == CANONICAL_STAGE_ORDER[0].value
    assert "branch.base-behind-pre-pr-replan" not in decision.reason_codes
    assert "branch.base-behind-route-gh-life3" not in decision.reason_codes
    assert decision.branch_refresh_authorized is False
    assert decision.continuation_authorized is False
    assert decision.retry_authorized is False
    assert decision.merge_authorized is False
    assert decision.issue_closure_authorized is False
    assert decision.external_writes_authorized is False
