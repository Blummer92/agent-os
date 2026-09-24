from scripts.agent_os_issue_labels.ready_for_review_admission import (
    evaluate_provisional_ready_reconciliation,
    evaluate_ready_for_review_admission,
)

HEAD = "a" * 40


def admission(**overrides):
    values = {
        "repository": "Blummer92/agent-os",
        "pr_number": 2115,
        "pr_lifecycle_state": "draft",
        "expected_head_sha": HEAD,
        "observed_head_sha": HEAD,
        "validation_head_sha": HEAD,
        "validation_admission_mode": "draft-final-candidate",
        "aggregate_status": "success",
        "focused_status": "success",
        "requested_changes": False,
        "blocking_unresolved": 0,
        "ready_for_review_authority_supplied": True,
    }
    values.update(overrides)
    return evaluate_ready_for_review_admission(**values)


def test_review_feedback_blocks_provisional_ready_trigger():
    result = admission(
        validation_admission_mode="pull-request-draft-focused",
        aggregate_status="skipped",
        blocking_unresolved=1,
    )
    assert result.transition_admissible is False
    assert "blocking-review-conversation-unresolved" in result.reason_codes
    assert result.next_action == "resolve-review-before-ready"


def test_exact_final_candidate_green_and_review_converged_admits_ready_transition():
    result = admission()
    assert result.transition_admissible is True
    assert result.next_action == "perform-ready-for-review-at-exact-head"
    assert result.reason_codes == ("draft-final-candidate-ready-converged",)


def test_changed_head_invalidates_prior_aggregate():
    result = admission(observed_head_sha="b" * 40)
    assert result.transition_admissible is False
    assert "exact-head-drift" in result.reason_codes
    assert "stale-validation-head" in result.reason_codes
    assert result.next_action == "reacquire-current-head-and-validation"


def test_requested_changes_block_even_when_aggregate_is_green():
    result = admission(requested_changes=True)
    assert result.transition_admissible is False
    assert result.next_action == "resolve-review-before-ready"


def test_ready_authority_remains_separate_from_validation():
    result = admission(ready_for_review_authority_supplied=False)
    assert result.transition_admissible is False
    assert "ready-for-review-authority-missing" in result.reason_codes
    assert result.ready_for_review_authorized is False
    assert result.merge_authorized is False
    assert result.workflow_authorized is False


def test_non_draft_pr_cannot_reenter_ready_admission():
    result = admission(pr_lifecycle_state="ready")
    assert result.transition_admissible is False
    assert "pr-not-draft" in result.reason_codes


def test_missing_draft_aggregate_can_use_reversible_ready_trigger():
    result = admission(
        validation_admission_mode="pull-request-draft-focused",
        aggregate_status="skipped",
    )
    assert result.transition_admissible is True
    assert result.provisional_ready is True
    assert result.rollback_to_draft_required is True
    assert result.next_action == "perform-provisional-ready-to-trigger-exact-head-aggregate"
    assert result.merge_authorized is False


def test_failed_aggregate_does_not_admit_provisional_ready():
    result = admission(
        validation_admission_mode="pull-request-draft-focused",
        aggregate_status="failure",
    )
    assert result.transition_admissible is False
    assert result.provisional_ready is False
    assert result.next_action == "run-draft-final-candidate-aggregate"


def test_provisional_ready_success_converges_without_merge_authority():
    result = evaluate_provisional_ready_reconciliation(
        repository="Blummer92/agent-os",
        pr_number=2115,
        pr_lifecycle_state="ready",
        expected_head_sha=HEAD,
        observed_head_sha=HEAD,
        validation_head_sha=HEAD,
        aggregate_status="success",
    )
    assert result.ready_converged is True
    assert result.rollback_to_draft_required is False
    assert result.next_action == "retain-ready-and-reacquire-later-gates"
    assert result.merge_authorized is False


def test_provisional_ready_failure_requires_draft_rollback():
    result = evaluate_provisional_ready_reconciliation(
        repository="Blummer92/agent-os",
        pr_number=2115,
        pr_lifecycle_state="ready",
        expected_head_sha=HEAD,
        observed_head_sha=HEAD,
        validation_head_sha=HEAD,
        aggregate_status="failure",
    )
    assert result.ready_converged is False
    assert result.rollback_to_draft_required is True
    assert result.next_action == "convert-pull-request-back-to-draft"


def test_provisional_ready_head_drift_requires_draft_rollback():
    result = evaluate_provisional_ready_reconciliation(
        repository="Blummer92/agent-os",
        pr_number=2115,
        pr_lifecycle_state="ready",
        expected_head_sha=HEAD,
        observed_head_sha="b" * 40,
        validation_head_sha=HEAD,
        aggregate_status="success",
    )
    assert result.ready_converged is False
    assert result.rollback_to_draft_required is True
    assert "exact-head-drift" in result.reason_codes
    assert result.next_action == "convert-pull-request-back-to-draft"


def test_provisional_ready_requires_focused_green():
    result = admission(
        validation_admission_mode="pull-request-draft-focused",
        aggregate_status="skipped",
        focused_status="failure",
    )
    assert result.transition_admissible is False
    assert result.provisional_ready is False
    assert "focused-validation-not-green" in result.reason_codes
