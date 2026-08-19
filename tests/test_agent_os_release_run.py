import importlib.util
import sys
from pathlib import Path

MODULE = Path(__file__).parents[1] / "scripts" / "agent-os-release-run.py"
spec = importlib.util.spec_from_file_location("release_run", MODULE)
release_run = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release_run
spec.loader.exec_module(release_run)

AGGREGATE = "Agent OS Validation Gate / Run aggregate validation"
ACCEPTANCE = "Agent OS Issue Acceptance Report"
HEAD = "a" * 40
MAIN = "b" * 40
OLD = "c" * 40


def lifecycle(head=HEAD, reason="validation-terminal", status="converged"):
    return {
        "reconciliation_status": status,
        "invocation_reason": reason,
        "planned_head_sha": head,
        "verified_head_sha": head,
        "unmanaged_labels_preserved": ["agent-os", "owner:integration-manager"],
    }


def refresh(old=OLD, new=HEAD, status="converged"):
    return {
        "status": status,
        "old_head_sha": old,
        "new_head_sha": new,
        "invalidated_head_evidence": [
            "approval-applicability",
            "branch-freshness",
            "candidate-runtime",
            "focused-validation",
            "lifecycle-reconciliation",
            "merge-authorization",
            "ready-for-review",
            "review-applicability",
            "tested-sha",
        ],
        "validation": {"head_sha": new, "status": "green"},
        "lifecycle_reconciliation": lifecycle(new),
    }


def evidence(**overrides):
    base = {
        "repository": "Blummer92/agent-os",
        "pull_request_number": 123,
        "issue_number": 903,
        "expected_head_sha": HEAD,
        "observed_head_sha": HEAD,
        "current_main_sha": MAIN,
        "validation_head_sha": HEAD,
        "branch_state": "current",
        "pr_state": "open",
        "pr_lifecycle_state": "ready",
        "issue_state": "open",
        "changed_files": ["scripts/agent-os-release-run.py"],
        "allowed_changed_files": ["scripts/agent-os-release-run.py"],
        "required_checks": {AGGREGATE: "success", ACCEPTANCE: "success"},
        "canonical_required_checks": [AGGREGATE, ACCEPTANCE],
        "authoritative_aggregate_check": AGGREGATE,
        "authorized_merge_method": "squash",
        "review_thread_summary": {"blocking_unresolved": 0, "resolved": 1},
        "ready_for_review_authorized": True,
        "merge_authorized": False,
        "issue_closure_authorized": False,
        "lifecycle_reconciliation": lifecycle(),
    }
    base.update(overrides)
    return base


def failure_evidence(**overrides):
    item = {
        "pr_head_sha": HEAD,
        "comparison_main_sha": MAIN,
        "command": "./scripts/validate-all.sh",
        "failed_requirement": AGGREGATE,
        "error_excerpt": "validation failed",
        "exit_code": 1,
        "source_identifiers": ["run:1"],
        "evidence_state": "current",
        "comparable_pr_and_main": False,
        "same_requirement_executed": False,
        "pr_requirement_result": "fail",
        "main_requirement_result": "unavailable",
        "materially_equivalent_failure": False,
        "pr_scope_attribution_supported": False,
        "infrastructure_configuration_failure_proven": False,
    }
    item.update(overrides)
    return item


def failed_checks(status="failure"):
    return {AGGREGATE: status, ACCEPTANCE: "success"}


def test_exact_head_success_reaches_merge_authorization_pause():
    state = release_run.evaluate_release_run(evidence())
    assert state.phase == "merge-authorization-pause"
    assert state.classification == "READY_FOR_MERGE_AUTHORIZATION"


def test_head_drift_fails_closed():
    state = release_run.evaluate_release_run(evidence(observed_head_sha="d" * 40))
    assert "exact-head drift" in state.blockers
    assert state.classification == "BLOCKED"


def test_non_success_required_check_states_remain_distinct():
    for status in (
        "missing", "pending", "skipped_unexpectedly", "cancelled",
        "timed_out", "not_triggered", "unknown", "stale",
    ):
        state = release_run.evaluate_release_run(evidence(required_checks=failed_checks(status)))
        assert f"required check {AGGREGATE} is {status}" in state.blockers
        assert state.classification == "BLOCKED"


def test_prior_head_green_does_not_satisfy_current_head():
    state = release_run.evaluate_release_run(evidence(prior_head_only_green=True))
    assert "prior-head checks cannot satisfy current head" in state.blockers


def test_requested_changes_and_blocking_thread_block():
    assert release_run.evaluate_release_run(evidence(requested_changes=True)).classification == "BLOCKED"
    assert release_run.evaluate_release_run(
        evidence(review_thread_summary={"blocking_unresolved": 1})
    ).classification == "BLOCKED"


def test_ready_for_review_requires_authorization():
    state = release_run.evaluate_release_run(
        evidence(pr_lifecycle_state="draft", ready_for_review_authorized=False)
    )
    assert state.phase == "ready-for-review"
    assert state.next_action == "request-ready-for-review-authorization"


def test_governed_ready_transition_is_separate_phase_boundary():
    state = release_run.evaluate_release_run(evidence(pr_lifecycle_state="draft"))
    assert state.phase == "ready-for-review"
    assert state.next_action == "perform-ready-for-review-at-exact-head"
    assert state.classification == "BLOCKED"


def test_merge_requires_separate_authorization():
    state = release_run.evaluate_release_run(evidence(merge_authorized=False))
    assert state.phase == "merge-authorization-pause"
    assert state.next_action == "request-merge-authorization"


def test_merge_action_is_exact_head_and_method_bounded():
    state = release_run.evaluate_release_run(evidence(merge_authorized=True))
    assert state.phase == "merge"
    assert state.next_action == "merge-at-expected-head-with-squash"


def test_post_merge_verification_fails_closed_for_governed_merge():
    state = release_run.evaluate_release_run(
        evidence(
            pr_state="merged", pr_lifecycle_state="merged",
            checkpoint_pr_lifecycle_state="merged", side_effects_performed=["merge"],
            merge_commit_verified=False, main_verified=True,
        )
    )
    assert state.phase == "post-merge-verification"
    assert state.classification == "BLOCKED"


def test_issue_closure_requires_separate_authorization():
    state = release_run.evaluate_release_run(
        evidence(
            pr_state="merged", pr_lifecycle_state="merged",
            checkpoint_pr_lifecycle_state="merged", side_effects_performed=["merge"],
            merge_commit_verified=True, main_verified=True,
        )
    )
    assert state.phase == "issue-closure-authorization-pause"


def test_completion_comment_precedes_closure():
    state = release_run.evaluate_release_run(
        evidence(
            pr_state="merged", pr_lifecycle_state="merged",
            checkpoint_pr_lifecycle_state="merged", side_effects_performed=["merge"],
            merge_commit_verified=True, main_verified=True, issue_closure_authorized=True,
        )
    )
    assert state.next_action == "post-completion-comment-before-closure"


def test_side_effects_are_explicit_and_deterministic():
    item = evidence(side_effects_performed=["ready-for-review"])
    first = release_run.evaluate_release_run(item)
    second = release_run.evaluate_release_run(item)
    assert first == second
    assert first.side_effects_performed == ["ready-for-review"]


def test_scope_drift_blocks():
    state = release_run.evaluate_release_run(evidence(changed_files=[".github/workflows/nope.yml"]))
    assert "changed-file scope drift" in state.blockers


def test_infrastructure_failure_uses_988_and_blocks_not_needs_fix():
    failure = failure_evidence(
        infrastructure_configuration_failure_proven=True,
        error_excerpt="setup-python download returned HTTP 503",
    )
    state = release_run.evaluate_release_run(
        evidence(required_checks=failed_checks(), validation_failure_evidence=failure)
    )
    assert state.validation_failure_classification == "ci_infrastructure_configuration_failure"
    assert state.classification == "BLOCKED"


def test_red_check_when_validation_did_not_run_is_not_needs_fix():
    state = release_run.evaluate_release_run(
        evidence(required_checks=failed_checks(), validation_failure_evidence=failure_evidence())
    )
    assert state.classification == "BLOCKED"


def test_pr_regression_is_only_validation_failure_class_that_needs_fix():
    failure = failure_evidence(
        comparable_pr_and_main=True,
        same_requirement_executed=True,
        main_requirement_result="pass",
        pr_scope_attribution_supported=True,
    )
    state = release_run.evaluate_release_run(
        evidence(required_checks=failed_checks(), validation_failure_evidence=failure)
    )
    assert state.validation_failure_classification == "pr_regression"
    assert state.classification == "NEEDS_FIX"


def test_inherited_main_failure_blocks_without_scope_contamination():
    failure = failure_evidence(
        comparable_pr_and_main=True,
        same_requirement_executed=True,
        main_requirement_result="fail",
        materially_equivalent_failure=True,
    )
    state = release_run.evaluate_release_run(
        evidence(required_checks=failed_checks(), validation_failure_evidence=failure)
    )
    assert state.validation_failure_classification == "inherited_main_failure"
    assert state.classification == "BLOCKED"


def test_caller_cannot_omit_authoritative_aggregate_check():
    state = release_run.evaluate_release_run(evidence(required_checks={ACCEPTANCE: "success"}))
    assert f"required check {AGGREGATE} is missing" in state.blockers


def test_unrelated_green_checks_cannot_substitute_for_aggregate():
    state = release_run.evaluate_release_run(
        evidence(required_checks={"AccessLint": "success", ACCEPTANCE: "success"})
    )
    assert f"required check {AGGREGATE} is missing" in state.blockers


def test_canonical_validation_set_must_be_proven():
    state = release_run.evaluate_release_run(evidence(canonical_required_checks=[]))
    assert "canonical required validation set is unavailable" in state.blockers


def test_aggregate_must_belong_to_canonical_validation_set():
    state = release_run.evaluate_release_run(
        evidence(canonical_required_checks=[ACCEPTANCE], required_checks={ACCEPTANCE: "success", AGGREGATE: "success"})
    )
    assert "authoritative aggregate check is not in canonical required validation set" in state.blockers


def test_green_validation_never_creates_merge_authority():
    state = release_run.evaluate_release_run(evidence(merge_authorized=False))
    assert state.merge_authorized is False
    assert state.phase == "merge-authorization-pause"


def test_branch_behind_routes_exclusively_to_1187_even_when_green():
    state = release_run.evaluate_release_run(
        evidence(branch_state="behind", managed_labels=["pr:merge-ready", "validation:green"])
    )
    assert "branch is behind current main" in state.blockers
    assert state.next_action == "route-through-gh-life3-1187"
    assert state.classification == "BLOCKED"


def test_validation_must_be_bound_to_exact_refreshed_head():
    state = release_run.evaluate_release_run(
        evidence(
            expected_head_sha=HEAD, observed_head_sha=HEAD,
            validation_head_sha=OLD, checkpoint_head_sha=OLD,
            branch_refresh_result=refresh(),
        )
    )
    assert "authoritative validation is bound to a stale head" in state.blockers


def test_1187_refresh_proves_head_advance_and_new_validation():
    state = release_run.evaluate_release_run(
        evidence(checkpoint_head_sha=OLD, branch_refresh_result=refresh())
    )
    assert state.external_transition is None
    assert state.phase == "merge-authorization-pause"


def test_1187_refresh_requires_head_evidence_invalidation():
    receipt = refresh()
    receipt["invalidated_head_evidence"] = ["tested-sha"]
    state = release_run.evaluate_release_run(
        evidence(checkpoint_head_sha=OLD, branch_refresh_result=receipt)
    )
    assert "#1187 refresh did not prove required head-evidence invalidation" in state.blockers


def test_terminal_validation_requires_current_1038_reconciliation():
    state = release_run.evaluate_release_run(evidence(lifecycle_reconciliation=None))
    assert "managed-label reconciliation receipt is missing" in state.blockers
    assert state.next_action == "reconcile-managed-labels-via-gh-life2-1038"


def test_stale_1038_receipt_blocks_regardless_of_managed_labels():
    state = release_run.evaluate_release_run(
        evidence(
            lifecycle_reconciliation=lifecycle(OLD),
            managed_labels=["pr:merge-ready", "validation:green", "branch:current"],
        )
    )
    assert "managed-label reconciliation is bound to a stale head" in state.blockers
    assert state.classification == "BLOCKED"


def test_draft_to_ready_outside_governed_operation_is_detected():
    state = release_run.evaluate_release_run(
        evidence(
            pr_lifecycle_state="ready",
            checkpoint_pr_lifecycle_state="draft",
            checkpoint_head_sha=HEAD,
            side_effects_performed=[],
        )
    )
    assert state.phase == "external-transition"
    assert state.external_transition == "draft-to-ready"
    assert state.next_action == "reacquire-and-reclassify-current-ready-state"


def test_governed_draft_to_ready_transition_can_continue_after_reacquisition():
    state = release_run.evaluate_release_run(
        evidence(
            pr_lifecycle_state="ready",
            checkpoint_pr_lifecycle_state="draft",
            checkpoint_head_sha=HEAD,
            side_effects_performed=["ready-for-review"],
            lifecycle_reconciliation=lifecycle(reason="draft-ready-transition"),
        )
    )
    assert state.phase == "merge-authorization-pause"


def test_unexpected_head_movement_is_external_transition_without_1187_receipt():
    state = release_run.evaluate_release_run(evidence(checkpoint_head_sha=OLD))
    assert state.phase == "external-transition"
    assert state.external_transition == "unexpected-head-movement"


def test_externally_merged_pr_cannot_continue_stale_merge_pause():
    state = release_run.evaluate_release_run(
        evidence(
            pr_state="merged", pr_lifecycle_state="merged",
            checkpoint_pr_lifecycle_state="ready", checkpoint_phase="merge-authorization-pause",
            checkpoint_head_sha=HEAD, side_effects_performed=[],
            merge_commit_verified=True, main_verified=True,
        )
    )
    assert state.phase == "external-transition"
    assert state.external_transition == "merged"
    assert state.next_action == "terminal-external-transition-merged"


def test_unmanaged_labels_are_not_mutated_by_release_evaluator():
    state = release_run.evaluate_release_run(
        evidence(
            unmanaged_labels=["agent-os", "owner:integration-manager", "security:human"],
            managed_labels=["pr:draft", "branch:behind"],
        )
    )
    assert state.side_effects_performed == []


def test_no_implicit_dangerous_actions_exist():
    state = release_run.evaluate_release_run(evidence())
    for action in (
        "branch-delete", "workflow-rerun", "review-dismissal", "auto-merge",
        "bypass", "ruleset-change", "required-check-change", "merge-queue",
    ):
        assert action not in state.side_effects_performed
        assert action not in state.next_action
