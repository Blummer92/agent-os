from __future__ import annotations

from agent_os_execution_service.failed_repair_admission import (
    evaluate_failed_repair_admission,
)


def activation(**overrides):
    value = {
        "attempt_id": "pr-2115-head-a-validation-1",
        "retry_reentry_outcome": "consumed",
        "selected_lesson_ids": ["LL-51", "LL-52"],
        "mutation_admissible": True,
    }
    value.update(overrides)
    return value


def admission(**overrides):
    value = {
        "activation_result": activation(),
        "check_state": "red",
        "required_check_configuration_state": "current",
        "review_state": "clear",
        "branch_freshness": "current",
        "mergeability": "mergeable",
    }
    value.update(overrides)
    return evaluate_failed_repair_admission(**value)


def test_consumed_lessons_are_preserved_on_exact_attempt_record():
    result = admission()
    assert result.attempt_id == "pr-2115-head-a-validation-1"
    assert result.selected_lesson_ids == ("LL-51", "LL-52")
    assert result.retry_reentry_outcome == "consumed"
    assert result.mutation_admissible is True
    assert result.next_action == "continue-authorized-repair-mutation"


def test_missing_retry_reentry_blocks_next_mutation():
    result = admission(
        activation_result=activation(
            retry_reentry_outcome="unavailable-or-failed",
            selected_lesson_ids=[],
            mutation_admissible=False,
        )
    )
    assert result.mutation_admissible is False
    assert "retry-specific-lessons-not-consumed" in result.reason_codes
    assert result.next_action == "reenter-ckr6-for-exact-failed-attempt"


def test_required_check_drift_is_not_conflated_with_red_check():
    result = admission(required_check_configuration_state="drifted")
    assert result.mutation_admissible is False
    assert "required-check-configuration-drift" in result.reason_codes
    assert result.next_action == "reconcile-required-check-configuration-before-code-repair"


def test_branch_behind_routes_to_existing_branch_owner_not_ci_edit():
    result = admission(branch_freshness="behind", mergeability="unknown")
    assert result.mutation_admissible is False
    assert "branch-freshness-blocking-or-unresolved" in result.reason_codes
    assert result.next_action == "route-branch-state-through-existing-refresh-conflict-owner"
    assert result.workflow_authorized is False


def test_mergeability_conflict_signal_alone_never_authorizes_workflow_change():
    result = admission(mergeability="conflicting")
    assert result.mutation_admissible is False
    assert "mergeability-conflict-signal" in result.reason_codes
    assert result.workflow_authorized is False
    assert result.github_writes_authorized is False


def test_review_state_is_diagnosed_independently():
    result = admission(review_state="requested-changes")
    assert result.mutation_admissible is False
    assert "review-state-blocking-or-unresolved" in result.reason_codes
    assert result.next_action == "resolve-or-reacquire-review-state"


def test_red_check_can_still_admit_repair_when_other_dimensions_are_current():
    result = admission(check_state="red")
    assert result.mutation_admissible is True
    assert result.reason_codes == ("retry-lessons-and-diagnostics-converged",)
