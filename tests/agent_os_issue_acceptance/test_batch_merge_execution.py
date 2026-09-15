from scripts.agent_os_issue_acceptance.batch_merge_execution import (
    BatchItemDisposition, BatchMergeAction, CurrentPrEvidence, ItemAdmissionEvidence, MergeReadbackEvidence,
    apply_current_state, apply_merge_authorization, apply_merge_readback, apply_post_merge_reconciliation,
    apply_lifecycle_readback, apply_refresh_readback, apply_validation, expected_lifecycle_mutations,
    expected_merge, final_batch_report, record_lifecycle_mutations, record_merge_attempt, start_batch_execution,
)
from scripts.agent_os_issue_acceptance.batch_post_merge_reconciliation import (
    PostMergeCandidateProjection, TerminalLifecycleDisposition,
)
from scripts.agent_os_issue_acceptance.pr_batch_merge_plan import PrBatchItemEvidence, build_pr_batch_merge_plan

def plan(*prs):
    return build_pr_batch_merge_plan(repository="Blummer92/agent-os",base_revision="a"*40,requested_pull_requests=prs,evidence=[PrBatchItemEvidence(p,f"h{p}","main","open","applicable") for p in prs])
def current(pr,main,head,freshness="current",**kw):return CurrentPrEvidence(pr,main,head,"open",freshness,**kw)
def admit(pr,main,head,validation="passed",authorization="authorized"):return ItemAdmissionEvidence(pr,main,head,validation,authorization)
def drive(c,pr,main,head):
    c=apply_current_state(c,current(pr,main,head));c=apply_validation(c,admit(pr,main,head));c=apply_merge_authorization(c,admit(pr,main,head));assert expected_merge(c)==(pr,head);return c
def merged(c,pr,head,new_main):
    c=record_merge_attempt(c,pull_request_number=pr,expected_head_sha=head,accepted=True);return apply_merge_readback(c,MergeReadbackEvidence(pr,head,True,new_main))
def projection(pr,issue,disposition,*,close=False,remove=False,readback=False,converged=False,reasons=("test",)):
    return PostMergeCandidateProjection(pr,issue,disposition,reasons,False,remove,close,readback,converged,"snap","ops")

def test_unlinked_pr_preserves_existing_merge_progression():
    c=merged(drive(start_batch_execution(plan(11,12)),11,"m1","h11"),11,"h11","m2")
    assert c.action is BatchMergeAction.REACQUIRE and c.current_pull_request==12
    assert c.results[-1].disposition is BatchItemDisposition.MERGED

def test_linked_issue_merge_readback_is_intermediate():
    c=merged(drive(start_batch_execution(plan(11,12),linked_issues={11:101}),11,"m1","h11"),11,"h11","m2")
    assert c.action is BatchMergeAction.POST_MERGE and c.current_pull_request==11 and not c.results

def test_admitted_close_requires_mutation_and_final_readback_before_advancing():
    c=merged(drive(start_batch_execution(plan(11,12),linked_issues={11:101}),11,"m1","h11"),11,"h11","m2")
    p=projection(11,101,TerminalLifecycleDisposition.CLOSED_COMPLETED,close=True,remove=True,readback=True)
    c=apply_post_merge_reconciliation(c,p);assert c.action is BatchMergeAction.LIFECYCLE_MUTATE
    assert expected_lifecycle_mutations(c,p)==(101,True,True)
    c=record_lifecycle_mutations(c,issue_number=101,accepted=True);assert c.action is BatchMergeAction.LIFECYCLE_READBACK
    c=apply_lifecycle_readback(c,projection(11,101,TerminalLifecycleDisposition.CLOSED_COMPLETED,converged=True,reasons=("already-converged",)))
    assert c.current_pull_request==12 and c.results[-1].disposition is BatchItemDisposition.MERGED_ISSUE_CLOSED

def test_already_closed_clean_issue_is_idempotent():
    c=merged(drive(start_batch_execution(plan(11),linked_issues={11:101}),11,"m1","h11"),11,"h11","m2")
    c=apply_post_merge_reconciliation(c,projection(11,101,TerminalLifecycleDisposition.CLOSED_COMPLETED,converged=True,reasons=("already-converged",)))
    assert final_batch_report(c)[0].disposition is BatchItemDisposition.MERGED_ISSUE_CLOSED

def test_remaining_scope_is_item_local_and_continues():
    c=merged(drive(start_batch_execution(plan(11,12),linked_issues={11:101}),11,"m1","h11"),11,"h11","m2")
    c=apply_post_merge_reconciliation(c,projection(11,101,TerminalLifecycleDisposition.MERGED_ISSUE_NOT_COMPLETE,reasons=("issue-definition-of-done-not-satisfied",)))
    assert c.current_pull_request==12 and c.results[-1].disposition is BatchItemDisposition.MERGED_ISSUE_INCOMPLETE

def test_missing_closure_authority_is_item_local_and_continues():
    c=merged(drive(start_batch_execution(plan(11,12),linked_issues={11:101}),11,"m1","h11"),11,"h11","m2")
    c=apply_post_merge_reconciliation(c,projection(11,101,TerminalLifecycleDisposition.MERGED_AWAITING_CLOSURE_AUTHORIZATION,reasons=("close-issue-not-currently-admitted",)))
    assert c.current_pull_request==12 and c.results[-1].disposition is BatchItemDisposition.MERGED_AWAITING_CLOSURE

def test_parent_tracking_manual_review_never_requests_close():
    c=merged(drive(start_batch_execution(plan(11,12),linked_issues={11:101}),11,"m1","h11"),11,"h11","m2")
    c=apply_post_merge_reconciliation(c,projection(11,101,TerminalLifecycleDisposition.MANUAL_REVIEW,reasons=("issue-kind-not-implementation",)))
    assert c.current_pull_request==12 and c.results[-1].disposition is BatchItemDisposition.MANUAL_REVIEW

def test_lifecycle_readback_mismatch_halts_shared_currentness():
    c=merged(drive(start_batch_execution(plan(11,12),linked_issues={11:101}),11,"m1","h11"),11,"h11","m2")
    p=projection(11,101,TerminalLifecycleDisposition.CLOSED_COMPLETED,close=True,readback=True)
    c=apply_post_merge_reconciliation(c,p);c=record_lifecycle_mutations(c,issue_number=101,accepted=True)
    c=apply_lifecycle_readback(c,projection(11,101,TerminalLifecycleDisposition.CLOSED_COMPLETED,converged=False))
    assert c.action is BatchMergeAction.HALT

def test_provider_failure_still_halts_batch():
    c=drive(start_batch_execution(plan(11,12),linked_issues={11:101}),11,"m1","h11");c=record_merge_attempt(c,pull_request_number=11,expected_head_sha="h11",accepted=True)
    c=apply_merge_readback(c,MergeReadbackEvidence(11,"h11",True,"m2",provider_available=False));assert c.action is BatchMergeAction.HALT

def test_no_background_or_auto_merge_actions_exist():
    assert {a.value for a in BatchMergeAction}.isdisjoint({"auto-merge","poll","retry","queue"})
