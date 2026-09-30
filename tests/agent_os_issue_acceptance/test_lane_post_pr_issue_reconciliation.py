"""Regression coverage for #2791: lane terminal reconciliation.

Reproduces the 2026-09-22 incident where implementation issue #2770 was left
open+ready after Draft PR #2790 was created, and proves the lane now projects
the issue's expected post-PR disposition and cannot report the PR as fully
reconciled until the terminal readback proves it.
"""
import pytest

from scripts.agent_os_issue_acceptance.lane_post_pr_issue_reconciliation import (
    LanePostPrIssueDisposition,
    LanePostPrIssueEvidence,
    LanePostPrIssueReconciliation,
    evaluate_lane_post_pr_issue_readback,
    project_lane_post_pr_issue_reconciliation,
)

HEAD_2790 = "b" * 40


def evidence(issue=2770, *, open=True, labels=("status:ready",), pr=2790,
             pr_state="draft", readback=True, closure=True, current=True):
    return LanePostPrIssueEvidence(
        issue_number=issue,
        issue_open=open,
        lifecycle_labels=labels,
        linked_pull_request_number=pr,
        pr_state=pr_state,
        pr_head_sha=HEAD_2790,
        pr_readback_current=readback,
        closure_authorized=closure,
        evidence_current=current,
    )


def readback(plan, *, issue=2770, open=True, labels=("status:ready",), current=True):
    return evaluate_lane_post_pr_issue_readback(
        plan,
        issue_number=issue,
        issue_open=open,
        lifecycle_labels=labels,
        evidence_current=current,
    )


def test_2770_2790_incident_projects_ready_removal_and_close():
    plan = project_lane_post_pr_issue_reconciliation(evidence())
    assert plan.disposition is LanePostPrIssueDisposition.RECONCILE_READY_AND_CLOSE
    assert plan.expected_mutations == ("remove-lifecycle-label", "close-issue")
    assert plan.ready_label == "status:ready"
    assert plan.readback_required is True
    assert plan.fully_reconciled is False
    assert "lane-post-pr.close-authorized" in plan.reason_codes


def test_unreconciled_issue_cannot_report_full_reconciliation():
    plan = project_lane_post_pr_issue_reconciliation(evidence())
    proof = readback(plan)
    assert proof.fully_reconciled is False
    assert proof.reason_codes == ("lane-post-pr.issue-still-open",)


def test_authorized_close_read_back_proves_terminal_disposition():
    plan = project_lane_post_pr_issue_reconciliation(evidence())
    proof = readback(plan, open=False, labels=())
    assert proof.fully_reconciled is True
    assert proof.reason_codes == ("lane-post-pr.issue-closed",)


def test_missing_closure_authority_fails_visibly():
    plan = project_lane_post_pr_issue_reconciliation(evidence(closure=False))
    assert plan.disposition is (
        LanePostPrIssueDisposition.RECONCILE_READY_AWAITING_CLOSURE_AUTHORITY
    )
    assert plan.expected_mutations == ("remove-lifecycle-label",)
    assert "lane-post-pr.closure-authority-missing" in plan.reason_codes
    assert plan.fully_reconciled is False


def test_ready_removed_without_closure_authority_stays_unreconciled():
    plan = project_lane_post_pr_issue_reconciliation(evidence(closure=False))
    proof = readback(plan, labels=())
    assert proof.fully_reconciled is False
    assert proof.reason_codes == ("lane-post-pr.closure-authority-still-missing",)


def test_ready_still_present_after_mutation_is_not_reconciled():
    plan = project_lane_post_pr_issue_reconciliation(evidence(closure=False))
    proof = readback(plan, labels=("status:ready",))
    assert proof.fully_reconciled is False
    assert proof.reason_codes == ("lane-post-pr.ready-still-present",)


def test_already_closed_issue_is_already_reconciled():
    plan = project_lane_post_pr_issue_reconciliation(evidence(open=False, labels=()))
    assert plan.disposition is LanePostPrIssueDisposition.ALREADY_RECONCILED
    assert plan.expected_mutations == ()
    assert plan.fully_reconciled is True


def test_no_stale_ready_label_projects_close_only():
    plan = project_lane_post_pr_issue_reconciliation(evidence(labels=()))
    assert plan.disposition is LanePostPrIssueDisposition.RECONCILE_READY_AND_CLOSE
    assert plan.expected_mutations == ("close-issue",)
    assert plan.ready_label is None


def test_stale_evidence_needs_decision():
    plan = project_lane_post_pr_issue_reconciliation(evidence(current=False))
    assert plan.disposition is LanePostPrIssueDisposition.NEEDS_DECISION
    assert plan.fully_reconciled is False


def test_pr_without_canonical_readback_needs_decision():
    plan = project_lane_post_pr_issue_reconciliation(evidence(readback=False))
    assert plan.disposition is LanePostPrIssueDisposition.NEEDS_DECISION
    assert "lane-post-pr.pr-readback-not-current" in plan.reason_codes


def test_merged_pr_delegates_to_lifecycle_reconciliation():
    plan = project_lane_post_pr_issue_reconciliation(evidence(pr_state="merged"))
    assert plan.disposition is LanePostPrIssueDisposition.NEEDS_DECISION
    assert "lane-post-pr.pr-not-draft-ready" in plan.reason_codes


def test_stale_readback_evidence_cannot_prove_reconciliation():
    plan = project_lane_post_pr_issue_reconciliation(evidence())
    proof = readback(plan, open=False, labels=(), current=False)
    assert proof.fully_reconciled is False


def test_readback_identity_mismatch_fails_closed():
    plan = project_lane_post_pr_issue_reconciliation(evidence())
    with pytest.raises(ValueError):
        readback(plan, issue=2771, open=False, labels=())


def test_reconciliation_never_grants_merge_or_ready_authority():
    for closure in (True, False):
        plan = project_lane_post_pr_issue_reconciliation(evidence(closure=closure))
        assert plan.merge_authorized is False
        assert plan.ready_authorized is False
        assert plan.side_effects_performed is False


def test_mutations_use_existing_lifecycle_mutation_vocabulary():
    from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import MUTATIONS

    plan = project_lane_post_pr_issue_reconciliation(evidence())
    assert set(plan.expected_mutations) <= MUTATIONS
