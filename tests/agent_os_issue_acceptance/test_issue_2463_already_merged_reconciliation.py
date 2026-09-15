from scripts.agent_os_issue_acceptance.batch_merge_execution import BatchItemDisposition, BatchMergeAction, CurrentPrEvidence, apply_current_state, apply_post_merge_reconciliation, start_batch_execution
from scripts.agent_os_issue_acceptance.batch_post_merge_reconciliation import PostMergeCandidateProjection, TerminalLifecycleDisposition
from scripts.agent_os_issue_acceptance.pr_batch_merge_plan import PrBatchItemEvidence, build_pr_batch_merge_plan


def _plan(*prs):
    return build_pr_batch_merge_plan(repository="Blummer92/agent-os", base_revision="a" * 40, requested_pull_requests=prs, evidence=[PrBatchItemEvidence(pr, f"h{pr}", "main", "open", "applicable") for pr in prs])


def _projection(pr, issue):
    return PostMergeCandidateProjection(pr, issue, TerminalLifecycleDisposition.CLOSED_COMPLETED, ("already-converged",), False, False, False, False, True, "snap", "ops")


def test_already_merged_linked_issue_reconciles_before_next_pr():
    cursor = start_batch_execution(_plan(11, 12), linked_issues={11: 101})
    cursor = apply_current_state(cursor, CurrentPrEvidence(11, "m2", "h11", "merged", "current"))
    assert cursor.action is BatchMergeAction.POST_MERGE
    assert cursor.current_pull_request == 11
    cursor = apply_post_merge_reconciliation(cursor, _projection(11, 101))
    assert cursor.current_pull_request == 12
    assert cursor.results[-1].disposition is BatchItemDisposition.MERGED_ISSUE_CLOSED


def test_already_merged_unlinked_pr_remains_terminal():
    cursor = start_batch_execution(_plan(11, 12))
    cursor = apply_current_state(cursor, CurrentPrEvidence(11, "m2", "h11", "merged", "current"))
    assert cursor.current_pull_request == 12
    assert cursor.results[-1].disposition is BatchItemDisposition.ALREADY_TERMINAL


def test_closed_unmerged_linked_pr_does_not_reconcile():
    cursor = start_batch_execution(_plan(11, 12), linked_issues={11: 101})
    cursor = apply_current_state(cursor, CurrentPrEvidence(11, "m1", "h11", "closed", "current"))
    assert cursor.current_pull_request == 12
    assert cursor.results[-1].disposition is BatchItemDisposition.ALREADY_TERMINAL
