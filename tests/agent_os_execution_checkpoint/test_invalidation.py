"""Focused tests for scripts/agent_os_execution_checkpoint/invalidation.py.

One test per invalidation-matrix row, plus the structural proof that
AUTHORIZATION_CHANGED invalidates zero stages even when explicitly
asserted.
"""
from __future__ import annotations

import hashlib

import pytest

from scripts.agent_os_execution_checkpoint.invalidation import (
    ALL_STAGES,
    STAGE_INVALIDATION_TRIGGERS,
    TRIGGER_STAGES,
    BindingSnapshot,
    InvalidationTrigger,
    binding_snapshot_from_checkpoint,
    detect_triggers,
    is_stage_invalidated,
)
from scripts.agent_os_execution_checkpoint.models import (
    CANONICAL_STAGE_ORDER,
    CheckpointStage,
    ExecutionCheckpoint,
    InvalidationState,
    LifecycleState,
    StageStatus,
    WorktreeRole,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import LifecycleStage

SHA40 = "7d01ad36d7f9c9cba41c9fee62a562b7689c2fbe"
SHA40_B = "1" * 39 + "f"
HEX64 = hashlib.sha256(b"x").hexdigest()
HEX64_B = hashlib.sha256(b"y").hexdigest()
COMMAND_PLAN_ID = f"command-plan:{HEX64}"
COMMAND_PLAN_ID_B = f"command-plan:{HEX64_B}"


def base_bindings(**overrides: object) -> BindingSnapshot:
    fields: dict[str, object] = {
        "source_sha": SHA40,
        "tested_sha": SHA40,
        "dependency_fingerprint": HEX64,
        "environment_fingerprint": HEX64,
        "worktree_fingerprint": HEX64,
        "branch": "agent/895-execution-checkpoint",
        "acceptance_criteria_digest": HEX64,
        "governance_contract_digest": HEX64,
        "command_plan_id": COMMAND_PLAN_ID,
        "merge_base_sha": SHA40,
    }
    fields.update(overrides)
    return BindingSnapshot(**fields)


# --- structural coverage -----------------------------------------------------


def test_every_trigger_has_a_stage_sensitivity_entry() -> None:
    assert set(TRIGGER_STAGES) == set(InvalidationTrigger)


def test_stage_invalidation_triggers_is_the_exact_inversion_of_trigger_stages() -> None:
    for stage in CANONICAL_STAGE_ORDER:
        expected = frozenset(t for t, stages in TRIGGER_STAGES.items() if stage in stages)
        assert STAGE_INVALIDATION_TRIGGERS[stage] == expected


def test_authorization_changed_invalidates_zero_stages_structurally() -> None:
    assert TRIGGER_STAGES[InvalidationTrigger.AUTHORIZATION_CHANGED] == frozenset()
    for stage in CANONICAL_STAGE_ORDER:
        assert not is_stage_invalidated(stage, frozenset({InvalidationTrigger.AUTHORIZATION_CHANGED}))


def test_authorization_changed_invalidates_nothing_even_when_explicitly_asserted() -> None:
    """A documentation-only authorization change never invalidates dependency
    installation or any other evidence stage -- proven even when the caller
    explicitly asserts the trigger via extra_triggers."""

    recorded = base_bindings()
    current = base_bindings()  # identical bindings: no organic drift
    triggers = detect_triggers(
        recorded=recorded,
        current=current,
        extra_triggers=frozenset({InvalidationTrigger.AUTHORIZATION_CHANGED}),
    )
    assert triggers == frozenset({InvalidationTrigger.AUTHORIZATION_CHANGED})
    for stage in CANONICAL_STAGE_ORDER:
        assert not is_stage_invalidated(stage, triggers)


# --- one test per matrix row -------------------------------------------------


def test_source_sha_changed_invalidates_all_eleven_stages() -> None:
    triggers = detect_triggers(recorded=base_bindings(), current=base_bindings(source_sha=SHA40_B, tested_sha=SHA40_B))
    assert InvalidationTrigger.SOURCE_SHA_CHANGED in triggers
    for stage in CANONICAL_STAGE_ORDER:
        assert is_stage_invalidated(stage, frozenset({InvalidationTrigger.SOURCE_SHA_CHANGED}))


def test_tested_sha_differs_from_source_sha_invalidates_only_validation_stages() -> None:
    triggers = detect_triggers(recorded=base_bindings(), current=base_bindings(tested_sha=SHA40_B))
    assert InvalidationTrigger.TESTED_SHA_DIFFERS in triggers
    invalidated = {s for s in CANONICAL_STAGE_ORDER if is_stage_invalidated(s, frozenset({InvalidationTrigger.TESTED_SHA_DIFFERS}))}
    assert invalidated == {CheckpointStage.FOCUSED_TESTS_PASSED, CheckpointStage.AGGREGATE_VALIDATION_PASSED}


def test_dependency_fingerprint_changed_invalidates_only_validation_stages() -> None:
    triggers = detect_triggers(recorded=base_bindings(), current=base_bindings(dependency_fingerprint=HEX64_B))
    assert InvalidationTrigger.DEPENDENCY_CHANGED in triggers
    invalidated = {s for s in CANONICAL_STAGE_ORDER if is_stage_invalidated(s, frozenset({InvalidationTrigger.DEPENDENCY_CHANGED}))}
    assert invalidated == {CheckpointStage.FOCUSED_TESTS_PASSED, CheckpointStage.AGGREGATE_VALIDATION_PASSED}


def test_environment_fingerprint_changed_invalidates_only_validation_stages() -> None:
    triggers = detect_triggers(recorded=base_bindings(), current=base_bindings(environment_fingerprint=HEX64_B))
    assert InvalidationTrigger.ENVIRONMENT_CHANGED in triggers
    invalidated = {s for s in CANONICAL_STAGE_ORDER if is_stage_invalidated(s, frozenset({InvalidationTrigger.ENVIRONMENT_CHANGED}))}
    assert invalidated == {CheckpointStage.FOCUSED_TESTS_PASSED, CheckpointStage.AGGREGATE_VALIDATION_PASSED}


def test_worktree_fingerprint_changed_invalidates_implementation_through_committed() -> None:
    triggers = detect_triggers(recorded=base_bindings(), current=base_bindings(worktree_fingerprint=HEX64_B))
    assert InvalidationTrigger.WORKTREE_CHANGED in triggers
    invalidated = {s for s in CANONICAL_STAGE_ORDER if is_stage_invalidated(s, frozenset({InvalidationTrigger.WORKTREE_CHANGED}))}
    assert invalidated == {
        CheckpointStage.IMPLEMENTATION_COMPLETE,
        CheckpointStage.FOCUSED_TESTS_PASSED,
        CheckpointStage.AGGREGATE_VALIDATION_PASSED,
        CheckpointStage.COMMITTED,
    }


def test_branch_changed_invalidates_committed_through_issue_closed() -> None:
    triggers = detect_triggers(recorded=base_bindings(), current=base_bindings(branch="agent/895-other"))
    assert InvalidationTrigger.BRANCH_CHANGED in triggers
    invalidated = {s for s in CANONICAL_STAGE_ORDER if is_stage_invalidated(s, frozenset({InvalidationTrigger.BRANCH_CHANGED}))}
    assert invalidated == {
        CheckpointStage.COMMITTED,
        CheckpointStage.PUSHED,
        CheckpointStage.DRAFT_PR_OPENED,
        CheckpointStage.CI_PASSED,
        CheckpointStage.REVIEW_COMPLETE,
        CheckpointStage.MERGED,
        CheckpointStage.ISSUE_CLOSED,
    }


def test_acceptance_criteria_digest_changed_invalidates_all_eleven_stages() -> None:
    triggers = detect_triggers(recorded=base_bindings(), current=base_bindings(acceptance_criteria_digest=HEX64_B))
    assert InvalidationTrigger.ACCEPTANCE_CRITERIA_CHANGED in triggers
    for stage in CANONICAL_STAGE_ORDER:
        assert is_stage_invalidated(stage, frozenset({InvalidationTrigger.ACCEPTANCE_CRITERIA_CHANGED}))


def test_governance_contract_digest_changed_invalidates_all_eleven_stages() -> None:
    triggers = detect_triggers(recorded=base_bindings(), current=base_bindings(governance_contract_digest=HEX64_B))
    assert InvalidationTrigger.GOVERNANCE_CONTRACT_CHANGED in triggers
    for stage in CANONICAL_STAGE_ORDER:
        assert is_stage_invalidated(stage, frozenset({InvalidationTrigger.GOVERNANCE_CONTRACT_CHANGED}))


def test_command_plan_id_changed_invalidates_only_validation_stages() -> None:
    """Also covers 'required validation changed', folded into this field."""

    triggers = detect_triggers(recorded=base_bindings(), current=base_bindings(command_plan_id=COMMAND_PLAN_ID_B))
    assert InvalidationTrigger.COMMAND_PLAN_CHANGED in triggers
    invalidated = {s for s in CANONICAL_STAGE_ORDER if is_stage_invalidated(s, frozenset({InvalidationTrigger.COMMAND_PLAN_CHANGED}))}
    assert invalidated == {CheckpointStage.FOCUSED_TESTS_PASSED, CheckpointStage.AGGREGATE_VALIDATION_PASSED}


def test_pr_head_changed_invalidates_ci_passed_and_review_complete() -> None:
    triggers = detect_triggers(
        recorded=base_bindings(pr_head_sha=HEX64),
        current=base_bindings(pr_head_sha=HEX64_B),
    )
    assert InvalidationTrigger.PR_HEAD_CHANGED in triggers
    invalidated = {s for s in CANONICAL_STAGE_ORDER if is_stage_invalidated(s, frozenset({InvalidationTrigger.PR_HEAD_CHANGED}))}
    assert invalidated == {CheckpointStage.CI_PASSED, CheckpointStage.REVIEW_COMPLETE}


def test_pr_head_first_observed_is_not_treated_as_a_change() -> None:
    triggers = detect_triggers(recorded=base_bindings(pr_head_sha=None), current=base_bindings(pr_head_sha=HEX64))
    assert InvalidationTrigger.PR_HEAD_CHANGED not in triggers


def test_ci_result_stale_invalidates_only_ci_passed() -> None:
    triggers = detect_triggers(
        recorded=base_bindings(ci_result_digest=HEX64),
        current=base_bindings(ci_result_digest=HEX64_B),
    )
    assert InvalidationTrigger.CI_RESULT_STALE in triggers
    invalidated = {s for s in CANONICAL_STAGE_ORDER if is_stage_invalidated(s, frozenset({InvalidationTrigger.CI_RESULT_STALE}))}
    assert invalidated == {CheckpointStage.CI_PASSED}


def test_review_feedback_arrived_invalidates_only_review_complete() -> None:
    triggers = detect_triggers(
        recorded=base_bindings(review_state_digest=None),
        current=base_bindings(review_state_digest=HEX64),
    )
    assert InvalidationTrigger.REVIEW_FEEDBACK_ARRIVED in triggers
    invalidated = {s for s in CANONICAL_STAGE_ORDER if is_stage_invalidated(s, frozenset({InvalidationTrigger.REVIEW_FEEDBACK_ARRIVED}))}
    assert invalidated == {CheckpointStage.REVIEW_COMPLETE}


def test_merge_base_sha_changed_invalidates_aggregate_validation_and_ci_passed() -> None:
    triggers = detect_triggers(recorded=base_bindings(), current=base_bindings(merge_base_sha=SHA40_B))
    assert InvalidationTrigger.MERGE_BASE_CHANGED in triggers
    invalidated = {s for s in CANONICAL_STAGE_ORDER if is_stage_invalidated(s, frozenset({InvalidationTrigger.MERGE_BASE_CHANGED}))}
    assert invalidated == {CheckpointStage.AGGREGATE_VALIDATION_PASSED, CheckpointStage.CI_PASSED}


def test_issue_or_pr_lifecycle_changed_externally_invalidates_merged_and_closed() -> None:
    triggers = detect_triggers(
        recorded=base_bindings(external_lifecycle_digest=None),
        current=base_bindings(external_lifecycle_digest=HEX64),
    )
    assert InvalidationTrigger.LIFECYCLE_CHANGED_EXTERNALLY in triggers
    invalidated = {s for s in CANONICAL_STAGE_ORDER if is_stage_invalidated(s, frozenset({InvalidationTrigger.LIFECYCLE_CHANGED_EXTERNALLY}))}
    assert invalidated == {CheckpointStage.MERGED, CheckpointStage.ISSUE_CLOSED}


# --- no drift = no triggers --------------------------------------------------


def test_identical_bindings_produce_no_triggers_except_extras() -> None:
    triggers = detect_triggers(recorded=base_bindings(), current=base_bindings())
    assert triggers == frozenset()


# --- binding_snapshot_from_checkpoint ----------------------------------------


def _checkpoint_with_evidence(evidence_hashes: tuple[tuple[str, str], ...]) -> ExecutionCheckpoint:
    return ExecutionCheckpoint(
        schema="agent-os.execution-checkpoint",
        schema_version="1.0",
        repository="Blummer92/agent-os",
        issue_number=895,
        invocation_id="inv-1",
        execution_id="exe-1",
        branch="agent/895-execution-checkpoint",
        worktree_fingerprint=HEX64,
        worktree_role=WorktreeRole.PRIMARY,
        environment_fingerprint=HEX64,
        source_sha=SHA40,
        tested_sha=SHA40,
        merge_base_sha=SHA40,
        dependency_fingerprint=HEX64,
        command_plan_id=COMMAND_PLAN_ID,
        acceptance_criteria_digest=HEX64,
        governance_contract_digest=HEX64,
        lifecycle_stage=LifecycleStage.DRAFT_PR,
        checkpoint_stage=CheckpointStage.CI_PASSED,
        stage_status=StageStatus.PASSED,
        evidence_hashes=evidence_hashes,
        invalidation_state=InvalidationState.CURRENT,
        lifecycle_state=LifecycleState.ACTIVE,
        recorded_at="2026-08-05T12:00:00Z",
        actor_id="github-service-agent",
    )


def test_binding_snapshot_from_checkpoint_projects_evidence_observations() -> None:
    checkpoint = _checkpoint_with_evidence((("pr_head_sha", HEX64), ("ci_result", HEX64_B)))
    snapshot = binding_snapshot_from_checkpoint(checkpoint)
    assert snapshot.pr_head_sha == HEX64
    assert snapshot.ci_result_digest == HEX64_B
    assert snapshot.review_state_digest is None


def test_binding_snapshot_from_checkpoint_with_no_optional_evidence() -> None:
    checkpoint = _checkpoint_with_evidence(())
    snapshot = binding_snapshot_from_checkpoint(checkpoint)
    assert snapshot.pr_head_sha is None
    assert snapshot.ci_result_digest is None
    assert snapshot.review_state_digest is None
    assert snapshot.external_lifecycle_digest is None


# --- malformed inputs fail closed -------------------------------------------


def test_detect_triggers_rejects_non_binding_snapshot() -> None:
    with pytest.raises(TypeError):
        detect_triggers(recorded={}, current=base_bindings())


def test_is_stage_invalidated_rejects_non_checkpoint_stage() -> None:
    with pytest.raises(TypeError):
        is_stage_invalidated("preflight-complete", frozenset())


def test_all_stages_matches_canonical_stage_order() -> None:
    assert ALL_STAGES == frozenset(CANONICAL_STAGE_ORDER)
