from __future__ import annotations

import pytest

from workflow_scheduler.execution.red_ci_continuation import (
    RedCiCheckpoint,
    RedCiEvidence,
    RedCiFailureClass,
    RedCiNextAction,
    ValidationState,
    plan_red_ci_continuation,
)

SHA_A = "a" * 40
SHA_B = "b" * 40


def _checkpoint(**overrides) -> RedCiCheckpoint:
    values = dict(
        repository="Blummer92/agent-os",
        issue_number=1251,
        pull_request_number=1400,
        branch="agent/1251-red-ci-continuation",
        head_sha=SHA_A,
        failing_check_identity="Agent OS Validation Gate",
        failing_run_identity="run:100",
        failing_conclusion="failure",
        last_completed_lifecycle_action="authoritative-aggregate-observed",
        checkpoint_lineage_identity="checkpoint-lineage:1251",
        scheduler_execution_identity="execution:1251",
        scheduler_lease_identity="lease:1251",
        scheduler_lease_generation=4,
    )
    values.update(overrides)
    return RedCiCheckpoint(**values)


def _evidence(**overrides) -> RedCiEvidence:
    values = dict(
        checkpoint=_checkpoint(),
        current_head_sha=SHA_A,
        authorization_current=True,
        scope_current=True,
        excluded_surface_required=False,
        evidence_ambiguous=False,
        infrastructure_or_tooling_failure=False,
        repository_failure_attributable=True,
        diagnostic_actionable_evidence=True,
        alternate_diagnostic_surface_available=False,
        diagnostic_surface_attempts=("github-actions",),
        repair_applied=False,
        focused_validation=ValidationState.NOT_RUN,
        aggregate_validation=ValidationState.NOT_RUN,
        aggregate_head_sha=None,
        blocking_review_conversation=False,
    )
    values.update(overrides)
    return RedCiEvidence(**values)


def test_current_head_repository_failure_resumes_same_lineage_for_repair() -> None:
    decision = plan_red_ci_continuation(_evidence())
    assert decision.failure_class is RedCiFailureClass.REPOSITORY_REPAIRABLE
    assert decision.next_action is RedCiNextAction.REPAIR_EXISTING_LINEAGE
    assert decision.branch == "agent/1251-red-ci-continuation"
    assert decision.pull_request_number == 1400
    assert decision.scheduler_lease_identity == "lease:1251"
    assert decision.scheduler_lease_generation == 4
    assert decision.continuation_authorized is False
    assert decision.retry_authorized is False
    assert decision.merge_authorized is False


def test_interrupted_checkpoint_is_deterministic_and_preserves_identity() -> None:
    first = plan_red_ci_continuation(_evidence())
    second = plan_red_ci_continuation(_evidence())
    assert first == second
    assert first.decision_id == second.decision_id
    assert first.checkpoint_lineage_identity == "checkpoint-lineage:1251"


def test_one_unavailable_diagnostic_surface_can_switch_once_to_authorized_alternative() -> None:
    decision = plan_red_ci_continuation(
        _evidence(
            diagnostic_actionable_evidence=False,
            alternate_diagnostic_surface_available=True,
            diagnostic_surface_attempts=("github-actions",),
        )
    )
    assert decision.failure_class is RedCiFailureClass.DIAGNOSTIC_SURFACE_UNAVAILABLE
    assert decision.next_action is RedCiNextAction.DIAGNOSE_EXISTING_FAILURE
    assert "alternate diagnostic surface" in decision.recommended_action


def test_all_diagnostic_surfaces_unavailable_returns_one_explicit_blocker() -> None:
    decision = plan_red_ci_continuation(
        _evidence(
            diagnostic_actionable_evidence=False,
            alternate_diagnostic_surface_available=False,
            diagnostic_surface_attempts=("github-actions", "connector-status"),
        )
    )
    assert decision.next_action is RedCiNextAction.BLOCKED_DIAGNOSTIC_SURFACE
    assert decision.reason_codes == ("diagnostic.no-actionable-surface",)


def test_diagnostic_discovery_is_bounded_and_repeated_surface_is_rejected() -> None:
    with pytest.raises(ValueError, match="bounded attempt count"):
        _evidence(
            diagnostic_actionable_evidence=False,
            diagnostic_surface_attempts=("a", "b", "c"),
        )
    with pytest.raises(ValueError, match="must not repeat"):
        _evidence(
            diagnostic_actionable_evidence=False,
            diagnostic_surface_attempts=("github-actions", "github-actions"),
        )


def test_head_move_invalidates_old_diagnosis_and_routes_to_reacquire() -> None:
    decision = plan_red_ci_continuation(_evidence(current_head_sha=SHA_B))
    assert decision.failure_class is RedCiFailureClass.STALE_HEAD
    assert decision.next_action is RedCiNextAction.REACQUIRE_HEAD
    assert "head.bound-evidence-invalid" in decision.reason_codes


def test_infrastructure_failure_never_fabricates_product_repair() -> None:
    decision = plan_red_ci_continuation(
        _evidence(infrastructure_or_tooling_failure=True, repository_failure_attributable=False)
    )
    assert decision.failure_class is RedCiFailureClass.INFRASTRUCTURE_OR_TOOLING
    assert decision.next_action is RedCiNextAction.NEEDS_DECISION
    assert "do not fabricate" in decision.recommended_action


def test_repair_requires_focused_validation_before_aggregate() -> None:
    decision = plan_red_ci_continuation(_evidence(repair_applied=True))
    assert decision.next_action is RedCiNextAction.RUN_FOCUSED_VALIDATION


def test_focused_failure_returns_to_diagnosis_on_same_checkpoint_lineage() -> None:
    decision = plan_red_ci_continuation(
        _evidence(repair_applied=True, focused_validation=ValidationState.FAILED)
    )
    assert decision.next_action is RedCiNextAction.DIAGNOSE_EXISTING_FAILURE
    assert decision.checkpoint_lineage_identity == "checkpoint-lineage:1251"


def test_focused_pass_requires_one_exact_head_aggregate() -> None:
    decision = plan_red_ci_continuation(
        _evidence(repair_applied=True, focused_validation=ValidationState.PASSED)
    )
    assert decision.next_action is RedCiNextAction.RUN_EXACT_HEAD_AGGREGATE
    assert "one authoritative aggregate" in decision.recommended_action


def test_stale_aggregate_cannot_satisfy_readiness() -> None:
    decision = plan_red_ci_continuation(
        _evidence(
            repair_applied=True,
            focused_validation=ValidationState.PASSED,
            aggregate_validation=ValidationState.PASSED,
            aggregate_head_sha=SHA_B,
        )
    )
    assert decision.failure_class is RedCiFailureClass.STALE_HEAD
    assert decision.next_action is RedCiNextAction.REACQUIRE_HEAD


def test_new_red_exact_head_aggregate_becomes_next_durable_checkpoint() -> None:
    decision = plan_red_ci_continuation(
        _evidence(
            repair_applied=True,
            focused_validation=ValidationState.PASSED,
            aggregate_validation=ValidationState.FAILED,
            aggregate_head_sha=SHA_A,
        )
    )
    assert decision.next_action is RedCiNextAction.DIAGNOSE_EXISTING_FAILURE
    assert "next durable checkpoint" in decision.recommended_action


def test_green_exact_head_aggregate_is_ready_for_review_eligible_only() -> None:
    decision = plan_red_ci_continuation(
        _evidence(
            repair_applied=True,
            focused_validation=ValidationState.PASSED,
            aggregate_validation=ValidationState.PASSED,
            aggregate_head_sha=SHA_A,
        )
    )
    assert decision.next_action is RedCiNextAction.READY_FOR_REVIEW
    assert decision.merge_authorized is False
    assert decision.issue_closure_authorized is False
    assert decision.external_writes_authorized is False


def test_blocking_review_prevents_ready_for_review_despite_green_aggregate() -> None:
    decision = plan_red_ci_continuation(
        _evidence(
            repair_applied=True,
            focused_validation=ValidationState.PASSED,
            aggregate_validation=ValidationState.PASSED,
            aggregate_head_sha=SHA_A,
            blocking_review_conversation=True,
        )
    )
    assert decision.next_action is RedCiNextAction.NEEDS_DECISION
    assert decision.reason_codes == ("review.blocking-conversation",)


def test_excluded_surface_or_scope_drift_fails_closed() -> None:
    decision = plan_red_ci_continuation(
        _evidence(excluded_surface_required=True, scope_current=False)
    )
    assert decision.failure_class is RedCiFailureClass.EXCLUDED_OR_SCOPE_EXPANSION
    assert decision.next_action is RedCiNextAction.NEEDS_DECISION
    assert "scope.excluded-surface-required" in decision.reason_codes
    assert "scope.not-current" in decision.reason_codes


def test_ambiguous_failure_never_guesses_repair() -> None:
    decision = plan_red_ci_continuation(_evidence(evidence_ambiguous=True))
    assert decision.failure_class is RedCiFailureClass.AMBIGUOUS
    assert decision.next_action is RedCiNextAction.NEEDS_DECISION


def test_unattributed_failure_never_guesses_repair() -> None:
    decision = plan_red_ci_continuation(_evidence(repository_failure_attributable=False))
    assert decision.failure_class is RedCiFailureClass.AMBIGUOUS
    assert decision.next_action is RedCiNextAction.NEEDS_DECISION
