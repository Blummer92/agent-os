"""Focused tests for scripts/agent_os_execution_checkpoint/resume_planner.py.

Covers all seven resume classifications, the earliest-incomplete-stage
resume rule, the never-authorizes-the-next-stage guarantee, and the
delegation to a caller-supplied AgentOperatingModeDecision for authority.
"""
from __future__ import annotations

import hashlib

import pytest

from scripts.agent_os_execution_checkpoint.invalidation import BindingSnapshot
from scripts.agent_os_execution_checkpoint.models import (
    CANONICAL_STAGE_ORDER,
    CheckpointStage,
    ExecutionCheckpoint,
    InvalidationState,
    LifecycleState,
    StageStatus,
    WorktreeRole,
)
from scripts.agent_os_execution_checkpoint.mutation_intent import compute_mutation_intent_id
from scripts.agent_os_execution_checkpoint.resume_planner import (
    AuthorityCeiling,
    ResumePlan,
    StageClassification,
    authority_ceiling_from_decision,
    authority_permits_stage,
    plan_resume,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    ClaimState,
    DependencyState,
    FreshnessState,
    IssueOperationalState,
    IssueState,
    LifecycleStage,
    OperationalOutcome,
    PrimaryPrState,
    ReadinessState,
    TerminalDisposition,
    ValidationState,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    EnvironmentCapabilityEvidence,
    EnvironmentCapabilityState,
    evaluate_operating_mode_decision,
)

SHA40 = "7d01ad36d7f9c9cba41c9fee62a562b7689c2fbe"
SHA40_B = "1" * 39 + "f"
HEX64 = hashlib.sha256(b"x").hexdigest()
COMMAND_PLAN_ID = f"command-plan:{HEX64}"
BRANCH = "agent/895-execution-checkpoint"
REPOSITORY = "Blummer92/agent-os"
ISSUE_NUMBER = 895
EXECUTION_ID = "exe-1"
EVALUATED_AT = "2026-08-05T12:00:00Z"


def base_bindings(**overrides: object) -> BindingSnapshot:
    fields: dict[str, object] = {
        "source_sha": SHA40,
        "tested_sha": SHA40,
        "dependency_fingerprint": HEX64,
        "environment_fingerprint": HEX64,
        "worktree_fingerprint": HEX64,
        "branch": BRANCH,
        "acceptance_criteria_digest": HEX64,
        "governance_contract_digest": HEX64,
        "command_plan_id": COMMAND_PLAN_ID,
        "merge_base_sha": SHA40,
    }
    fields.update(overrides)
    return BindingSnapshot(**fields)


def make_checkpoint(
    stage: CheckpointStage,
    lifecycle: LifecycleStage,
    *,
    status: StageStatus = StageStatus.PASSED,
    invalidation_state: InvalidationState = InvalidationState.CURRENT,
    supersession_state: str | None = None,
    bindings: BindingSnapshot | None = None,
    mutation_intent_id: str | None = None,
    invocation_id: str = "inv-1",
    execution_id: str = EXECUTION_ID,
    evidence_hashes: tuple[tuple[str, str], ...] = (),
    recorded_at: str = EVALUATED_AT,
) -> ExecutionCheckpoint:
    b = bindings or base_bindings()
    is_mutating = stage in (
        CheckpointStage.IMPLEMENTATION_COMPLETE,
        CheckpointStage.COMMITTED,
        CheckpointStage.PUSHED,
        CheckpointStage.DRAFT_PR_OPENED,
        CheckpointStage.MERGED,
        CheckpointStage.ISSUE_CLOSED,
    )

    return ExecutionCheckpoint(
        schema="agent-os.execution-checkpoint",
        schema_version="1.0",
        repository=REPOSITORY,
        issue_number=ISSUE_NUMBER,
        invocation_id=invocation_id,
        execution_id=execution_id,
        branch=b.branch,
        worktree_fingerprint=b.worktree_fingerprint,
        worktree_role=WorktreeRole.PRIMARY,
        environment_fingerprint=b.environment_fingerprint,
        source_sha=b.source_sha,
        tested_sha=b.tested_sha,
        merge_base_sha=b.merge_base_sha,
        dependency_fingerprint=b.dependency_fingerprint,
        command_plan_id=b.command_plan_id,
        acceptance_criteria_digest=b.acceptance_criteria_digest,
        governance_contract_digest=b.governance_contract_digest,
        lifecycle_stage=lifecycle,
        checkpoint_stage=stage,
        stage_status=status,
        evidence_hashes=evidence_hashes,
        invalidation_state=invalidation_state,
        supersession_state=supersession_state,
        lifecycle_state=LifecycleState.ACTIVE,
        recorded_at=recorded_at,
        actor_id="github-service-agent",
        mutation_intent_id=mutation_intent_id,
        pre_read_digest=HEX64 if is_mutating and status is StageStatus.PASSED else None,
        post_write_digest=HEX64 if is_mutating and status is StageStatus.PASSED else None,
    )


def mutating_intent(stage_value: str, parent: str | None) -> str:
    return compute_mutation_intent_id(
        repository=REPOSITORY,
        issue_number=ISSUE_NUMBER,
        execution_id=EXECUTION_ID,
        checkpoint_stage=stage_value,
        target_ref=BRANCH,
        content_digest=HEX64,
        parent_checkpoint_id=parent,
    )


def build_decision(mode: str, implementation_state: AuthorizationState = AuthorizationState.AUTHORIZED) -> object:
    state = IssueOperationalState(
        schema_name="agent-os-issue-operational-state",
        schema_version="1.0",
        repository=REPOSITORY,
        issue_number=ISSUE_NUMBER,
        source_revision=SHA40,
        observed_at=EVALUATED_AT,
        evidence_ids=(),
        primary_claim_ids=(),
        outcome=OperationalOutcome.READY,
        issue_state=IssueState.OPEN,
        lifecycle_stage=LifecycleStage.IMPLEMENTATION,
        terminal_disposition=TerminalDisposition.NONE,
        readiness=ReadinessState.READY,
        implementation_authorization=AuthorityProjection(
            state=implementation_state,
            evidence_id=(f"approval:{HEX64}" if implementation_state is not AuthorizationState.NOT_APPLICABLE else None),
        ),
        ready_for_review_authorization=AuthorityProjection(state=AuthorizationState.NOT_AUTHORIZED),
        execution_authorization=AuthorityProjection(state=AuthorizationState.NOT_AUTHORIZED),
        merge_authorization=AuthorityProjection(state=AuthorizationState.NOT_AUTHORIZED),
        closure_authorization=AuthorityProjection(state=AuthorizationState.NOT_AUTHORIZED),
        external_write_authorization=AuthorityProjection(state=AuthorizationState.NOT_AUTHORIZED),
        dependency_state=DependencyState.CLEAR,
        claim_state=ClaimState.NONE,
        active_branch=None,
        primary_pr_numbers=(),
        primary_pr_state=PrimaryPrState.NONE,
        validation_state=ValidationState.NOT_RUN,
        freshness_state=FreshnessState.CURRENT,
        reconciliation_required=False,
        blocker_codes=(),
        reason_codes=(),
    )
    env = EnvironmentCapabilityEvidence(
        local_execution_state=EnvironmentCapabilityState.VERIFIED,
        push_state=EnvironmentCapabilityState.VERIFIED,
        evidence_id=f"env:{HEX64}",
    )
    return evaluate_operating_mode_decision(state, mode, env)


def decisions_by_stage(plan: ResumePlan) -> dict[CheckpointStage, StageClassification]:
    return {d.stage: d.classification for d in plan.stage_decisions}


# --- resume_point / earliest-incomplete-stage rule --------------------------


def test_no_evidence_resumes_at_the_first_stage() -> None:
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(),
    )
    assert plan.resume_point is CheckpointStage.PREFLIGHT_COMPLETE
    assert all(d.classification is StageClassification.RERUN_REQUIRED for d in plan.stage_decisions)


def test_all_stages_reusable_when_full_history_exists_and_authority_reaches_closed() -> None:
    checkpoints = []
    parent = None
    for stage in CANONICAL_STAGE_ORDER:
        lifecycle = {
            CheckpointStage.PREFLIGHT_COMPLETE: LifecycleStage.PLANNING,
            CheckpointStage.IMPLEMENTATION_COMPLETE: LifecycleStage.IMPLEMENTATION,
            CheckpointStage.FOCUSED_TESTS_PASSED: LifecycleStage.IMPLEMENTATION,
            CheckpointStage.AGGREGATE_VALIDATION_PASSED: LifecycleStage.IMPLEMENTATION,
            CheckpointStage.COMMITTED: LifecycleStage.IMPLEMENTATION,
            CheckpointStage.PUSHED: LifecycleStage.DRAFT_PR,
            CheckpointStage.DRAFT_PR_OPENED: LifecycleStage.DRAFT_PR,
            CheckpointStage.CI_PASSED: LifecycleStage.DRAFT_PR,
            CheckpointStage.REVIEW_COMPLETE: LifecycleStage.REVIEW,
            CheckpointStage.MERGED: LifecycleStage.MERGED,
            CheckpointStage.ISSUE_CLOSED: LifecycleStage.CLOSED,
        }[stage]
        intent = mutating_intent(stage.value, parent) if stage in (
            CheckpointStage.IMPLEMENTATION_COMPLETE,
            CheckpointStage.COMMITTED,
            CheckpointStage.PUSHED,
            CheckpointStage.DRAFT_PR_OPENED,
            CheckpointStage.MERGED,
            CheckpointStage.ISSUE_CLOSED,
        ) else None
        cp = make_checkpoint(stage, lifecycle, mutation_intent_id=intent)
        checkpoints.append(cp)
        parent = cp.checkpoint_id

    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(),
        stored_checkpoints=tuple(checkpoints),
    )
    assert plan.resume_point is None
    assert all(d.classification is StageClassification.REUSABLE for d in plan.stage_decisions)


def test_earlier_reusable_stages_do_not_block_a_later_resume_point() -> None:
    cp1 = make_checkpoint(CheckpointStage.PREFLIGHT_COMPLETE, LifecycleStage.PLANNING)
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(cp1,),
    )
    by_stage = decisions_by_stage(plan)
    assert by_stage[CheckpointStage.PREFLIGHT_COMPLETE] is StageClassification.REUSABLE
    assert by_stage[CheckpointStage.FOCUSED_TESTS_PASSED] is StageClassification.RERUN_REQUIRED
    assert plan.resume_point is CheckpointStage.IMPLEMENTATION_COMPLETE


# --- invalidation drift downgrades a previously-passed stage ----------------


def test_source_sha_drift_invalidates_reusability_even_if_stored_status_is_current() -> None:
    stale_bindings = base_bindings(source_sha=SHA40_B, tested_sha=SHA40_B)
    cp1 = make_checkpoint(CheckpointStage.PREFLIGHT_COMPLETE, LifecycleStage.PLANNING, bindings=stale_bindings)
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(cp1,),
    )
    by_stage = decisions_by_stage(plan)
    assert by_stage[CheckpointStage.PREFLIGHT_COMPLETE] is StageClassification.RERUN_REQUIRED


# --- the 7 classifications ----------------------------------------------


def test_classification_reusable() -> None:
    cp1 = make_checkpoint(CheckpointStage.PREFLIGHT_COMPLETE, LifecycleStage.PLANNING)
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(cp1,),
    )
    assert decisions_by_stage(plan)[CheckpointStage.PREFLIGHT_COMPLETE] is StageClassification.REUSABLE


def test_classification_rerun_required_when_no_evidence() -> None:
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(),
    )
    assert decisions_by_stage(plan)[CheckpointStage.PREFLIGHT_COMPLETE] is StageClassification.RERUN_REQUIRED


def test_classification_manual_review_for_uncertain_outcome_never_blindly_retried() -> None:
    cp1 = make_checkpoint(CheckpointStage.PREFLIGHT_COMPLETE, LifecycleStage.PLANNING, status=StageStatus.UNCERTAIN)
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(cp1,),
    )
    decision = next(d for d in plan.stage_decisions if d.stage is CheckpointStage.PREFLIGHT_COMPLETE)
    assert decision.classification is StageClassification.MANUAL_REVIEW
    assert decision.evidence_checkpoint_id == cp1.checkpoint_id


def test_uncertain_record_outranks_matching_passed_record() -> None:
    passed = make_checkpoint(
        CheckpointStage.PREFLIGHT_COMPLETE,
        LifecycleStage.PLANNING,
        invocation_id="inv-passed",
        recorded_at="2026-08-05T12:00:00Z",
    )
    uncertain = make_checkpoint(
        CheckpointStage.PREFLIGHT_COMPLETE,
        LifecycleStage.PLANNING,
        status=StageStatus.UNCERTAIN,
        invocation_id="inv-uncertain",
        recorded_at="2026-08-05T13:00:00Z",
    )
    assert passed.reuse_key == uncertain.reuse_key

    plan = plan_resume(
        repository=REPOSITORY,
        issue_number=ISSUE_NUMBER,
        execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT,
        current_bindings=base_bindings(),
        stored_checkpoints=(passed, uncertain),
    )
    decision = next(
        item
        for item in plan.stage_decisions
        if item.stage is CheckpointStage.PREFLIGHT_COMPLETE
    )

    assert decision.classification is StageClassification.MANUAL_REVIEW
    assert decision.evidence_checkpoint_id == uncertain.checkpoint_id


def test_matching_passed_checkpoints_from_separate_invocations_are_reusable() -> None:
    cp1 = make_checkpoint(
        CheckpointStage.PREFLIGHT_COMPLETE,
        LifecycleStage.PLANNING,
        invocation_id="inv-1",
    )
    cp2 = make_checkpoint(
        CheckpointStage.PREFLIGHT_COMPLETE,
        LifecycleStage.PLANNING,
        invocation_id="inv-2",
        evidence_hashes=(("distinguishing_marker", HEX64),),
    )
    assert cp1.checkpoint_id != cp2.checkpoint_id
    assert cp1.reuse_key == cp2.reuse_key

    plan = plan_resume(
        repository=REPOSITORY,
        issue_number=ISSUE_NUMBER,
        execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT,
        current_bindings=base_bindings(),
        stored_checkpoints=(cp1, cp2),
    )

    decision = next(
        item
        for item in plan.stage_decisions
        if item.stage is CheckpointStage.PREFLIGHT_COMPLETE
    )
    assert decision.classification is StageClassification.REUSABLE
    assert decision.evidence_checkpoint_id == max(
        cp1.checkpoint_id,
        cp2.checkpoint_id,
    )


def test_classification_quarantined() -> None:
    cp1 = make_checkpoint(CheckpointStage.PREFLIGHT_COMPLETE, LifecycleStage.PLANNING)
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(cp1,),
        quarantined_checkpoint_ids=frozenset({cp1.checkpoint_id}),
    )
    decision = next(d for d in plan.stage_decisions if d.stage is CheckpointStage.PREFLIGHT_COMPLETE)
    assert decision.classification is StageClassification.QUARANTINED
    assert decision.evidence_checkpoint_id == cp1.checkpoint_id


def test_classification_superseded() -> None:
    cp1 = make_checkpoint(
        CheckpointStage.PREFLIGHT_COMPLETE, LifecycleStage.PLANNING,
        invalidation_state=InvalidationState.SUPERSEDED,
        supersession_state=f"agent-os.execution-checkpoint:{HEX64}",
    )
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(cp1,),
    )
    assert decisions_by_stage(plan)[CheckpointStage.PREFLIGHT_COMPLETE] is StageClassification.SUPERSEDED


def test_classification_complete_but_unauthorized_to_continue() -> None:
    cp1 = make_checkpoint(CheckpointStage.PREFLIGHT_COMPLETE, LifecycleStage.PLANNING)
    decision = build_decision("planning")
    assert decision.maximum_permitted_stage is LifecycleStage.PLANNING
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(cp1,),
        authority_decision=decision,
    )
    by_stage = decisions_by_stage(plan)
    assert by_stage[CheckpointStage.PREFLIGHT_COMPLETE] is StageClassification.REUSABLE
    assert by_stage[CheckpointStage.IMPLEMENTATION_COMPLETE] is StageClassification.COMPLETE_BUT_UNAUTHORIZED_TO_CONTINUE
    assert plan.resume_point is CheckpointStage.IMPLEMENTATION_COMPLETE


def test_classification_blocked_for_explicit_not_authorized_mutation() -> None:
    decision = build_decision("build", implementation_state=AuthorizationState.NOT_AUTHORIZED)
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(),
        stored_checkpoints=(make_checkpoint(CheckpointStage.PREFLIGHT_COMPLETE, LifecycleStage.PLANNING),),
        authority_decision=decision,
    )
    by_stage = decisions_by_stage(plan)
    assert by_stage[CheckpointStage.IMPLEMENTATION_COMPLETE] is StageClassification.BLOCKED


def test_all_seven_classifications_are_reachable() -> None:
    assert {c.value for c in StageClassification} == {
        "reusable", "rerun-required", "blocked", "manual-review",
        "quarantined", "superseded", "complete-but-unauthorized-to-continue",
    }


# --- store-unavailable behavior ------------------------------------------


def test_store_unavailable_forces_read_only_rerun_and_mutating_manual_review() -> None:
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(),
        store_available=False,
    )
    by_stage = decisions_by_stage(plan)
    assert by_stage[CheckpointStage.PREFLIGHT_COMPLETE] is StageClassification.RERUN_REQUIRED
    assert by_stage[CheckpointStage.FOCUSED_TESTS_PASSED] is StageClassification.RERUN_REQUIRED
    assert by_stage[CheckpointStage.IMPLEMENTATION_COMPLETE] is StageClassification.MANUAL_REVIEW
    assert by_stage[CheckpointStage.PUSHED] is StageClassification.MANUAL_REVIEW
    assert plan.resume_point is CheckpointStage.PREFLIGHT_COMPLETE


# --- a plan never authorizes the next stage ---------------------------------


def test_resume_plan_always_carries_false_authority_fields() -> None:
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(),
    )
    assert plan.repository_implementation_authorized is False
    assert plan.execution_authorized is False
    assert plan.github_writes_authorized is False
    assert plan.merge_authorized is False
    assert plan.issue_closure_authorized is False
    assert plan.external_writes_authorized is False


# --- determinism / identity -------------------------------------------------


def test_plan_id_is_deterministic_for_identical_inputs() -> None:
    cp1 = make_checkpoint(CheckpointStage.PREFLIGHT_COMPLETE, LifecycleStage.PLANNING)
    plan_a = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(cp1,),
    )
    plan_b = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at="2026-08-05T18:45:00Z", current_bindings=base_bindings(), stored_checkpoints=(cp1,),
    )
    assert plan_a.plan_id == plan_b.plan_id  # evaluated_at is observational


def test_stage_decisions_are_always_in_canonical_order() -> None:
    plan = plan_resume(
        repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
        evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=(),
    )
    assert tuple(d.stage for d in plan.stage_decisions) == CANONICAL_STAGE_ORDER


# --- authority_permits_stage / authority_ceiling_from_decision --------------


def test_authority_permits_stage_fails_closed_with_no_ceiling() -> None:
    assert authority_permits_stage(CheckpointStage.PREFLIGHT_COMPLETE, None) is False


def test_authority_ceiling_from_decision_rejects_non_decision() -> None:
    with pytest.raises(TypeError):
        authority_ceiling_from_decision({"not": "a decision"})


def test_authority_permits_stage_respects_ceiling_ordering() -> None:
    ceiling = AuthorityCeiling(maximum_permitted_stage=LifecycleStage.DRAFT_PR)
    assert authority_permits_stage(CheckpointStage.PUSHED, ceiling) is True
    assert authority_permits_stage(CheckpointStage.REVIEW_COMPLETE, ceiling) is False


# --- malformed inputs fail closed -------------------------------------------


def test_plan_resume_rejects_non_tuple_stored_checkpoints() -> None:
    with pytest.raises(TypeError):
        plan_resume(
            repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
            evaluated_at=EVALUATED_AT, current_bindings=base_bindings(), stored_checkpoints=[],
        )


def test_plan_resume_rejects_non_binding_snapshot() -> None:
    with pytest.raises(TypeError):
        plan_resume(
            repository=REPOSITORY, issue_number=ISSUE_NUMBER, execution_id=EXECUTION_ID,
            evaluated_at=EVALUATED_AT, current_bindings={}, stored_checkpoints=(),
        )
