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
        "pr_title": "",
        "pr_body": "",
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


def test_3037_successful_provisional_ready_never_requests_draft_rollback():
    result = evaluate_provisional_ready_reconciliation(
        repository="Blummer92/agent-os",
        pr_number=3037,
        pr_lifecycle_state="ready",
        expected_head_sha=HEAD,
        observed_head_sha=HEAD,
        validation_head_sha=HEAD,
        aggregate_status="success",
    )
    assert result.ready_converged is True
    assert result.rollback_to_draft_required is False
    assert "provisional-ready-aggregate-converged" in result.reason_codes
    assert result.next_action == "retain-ready-and-reacquire-later-gates"


def test_3106_pending_provisional_ready_requires_immediate_draft_projection():
    result = evaluate_provisional_ready_reconciliation(
        repository="Blummer92/agent-os",
        pr_number=3106,
        pr_lifecycle_state="ready",
        expected_head_sha=HEAD,
        observed_head_sha=HEAD,
        validation_head_sha=HEAD,
        aggregate_status="in_progress",
    )
    assert result.ready_converged is False
    assert result.rollback_to_draft_required is True
    assert "provisional-ready-aggregate-pending" in result.reason_codes
    assert result.next_action == "convert-pull-request-back-to-draft-and-await-exact-head-aggregate"


def test_queued_provisional_ready_is_also_non_converged():
    result = evaluate_provisional_ready_reconciliation(
        repository="Blummer92/agent-os",
        pr_number=3106,
        pr_lifecycle_state="ready",
        expected_head_sha=HEAD,
        observed_head_sha=HEAD,
        validation_head_sha=HEAD,
        aggregate_status="queued",
    )
    assert result.rollback_to_draft_required is True
    assert "provisional-ready-aggregate-pending" in result.reason_codes


from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    IssueClosureAdmission,
    LifecycleMutationAuthorization,
    LifecycleStateSnapshot,
    evaluate_lifecycle_mutation,
)


def closure_admission(issue_number=2772, repository="Blummer92/agent-os"):
    """Build canonical close-issue admission evidence for one issue (#3157)."""
    authorization = LifecycleMutationAuthorization(
        schema_version="1.0",
        repository=repository,
        issue_number=issue_number,
        pull_request_number=None,
        authorized_mutations=("close-issue",),
        expected_source_head=None,
        expected_base_head=None,
        expected_pr_state="none",
        expected_merged=False,
        expected_issue_state="open",
        expected_review_state="unknown",
        expected_unresolved_threads=0,
        expected_lifecycle_labels=(),
        observed_at_revision="rev-1",
        state="authorized",
        authorizer_id="test-authorizer",
        decision_id="test-decision",
    )
    snapshot = LifecycleStateSnapshot(
        repository=repository,
        issue_number=issue_number,
        pull_request_number=None,
        source_head=None,
        base_head=None,
        pr_state="none",
        merged=False,
        issue_state="open",
        review_state="unknown",
        unresolved_threads=0,
        lifecycle_labels=(),
        observed_revision="rev-1",
    )
    admission = evaluate_lifecycle_mutation(authorization, snapshot, "close-issue")
    assert admission.admitted
    return IssueClosureAdmission(authorization=authorization, admission=admission)


def test_unauthorized_closing_reference_blocks_ready_transition():
    result = admission(pr_body="Fixes #2772")
    assert result.transition_admissible is False
    assert "unauthorized-closing-reference" in result.reason_codes
    assert result.next_action == "authorize-issue-closure-before-ready"


def test_closing_reference_in_title_blocks_ready_transition():
    result = admission(pr_title="Fixes #2772")
    assert result.transition_admissible is False
    assert "unauthorized-closing-reference" in result.reason_codes


def test_authorized_closing_reference_permits_ready_transition():
    result = admission(
        pr_body="Fixes #2772",
        closure_admissions=(closure_admission(2772),),
    )
    assert result.transition_admissible is True
    assert "unauthorized-closing-reference" not in result.reason_codes


def test_cross_repository_closure_admission_does_not_authorize():
    result = admission(
        pr_body="Fixes #2772",
        closure_admissions=(closure_admission(2772, repository="other/repo"),),
    )
    assert result.transition_admissible is False
    assert "unauthorized-closing-reference" in result.reason_codes


def test_negated_closing_prose_still_blocks_ready_transition():
    result = admission(pr_body="This does not close #2772")
    assert result.transition_admissible is False
    assert "unauthorized-closing-reference" in result.reason_codes


def test_ready_gate_grants_no_closure_authority():
    result = admission(
        pr_body="Fixes #2772",
        closure_admissions=(closure_admission(2772),),
    )
    assert result.transition_admissible is True
    assert result.issue_closure_authorized is False
    assert result.merge_authorized is False


def test_closure_admissions_must_be_exact_tuple():
    try:
        admission(closure_admissions=[closure_admission(2772)])
    except TypeError as exc:
        assert "exact tuple" in str(exc)
    else:
        raise AssertionError("expected TypeError")


def test_pr_title_and_body_are_required():
    for kwargs in ({"pr_title": None}, {"pr_body": None}):
        try:
            admission(**kwargs)
        except TypeError as exc:
            assert "built-in strings" in str(exc)
        else:
            raise AssertionError("expected TypeError")
