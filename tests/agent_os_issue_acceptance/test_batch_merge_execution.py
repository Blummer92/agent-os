from scripts.agent_os_issue_acceptance.batch_merge_execution import (
    BatchItemDisposition, BatchMergeAction, CurrentPrEvidence, RefreshPreparationEvidence, RefreshTriggerDestinationEvidence, ItemAdmissionEvidence, MergeReadbackEvidence,
    apply_current_state, apply_merge_authorization, apply_merge_readback, apply_post_merge_reconciliation,
    apply_lifecycle_readback, apply_refresh_authorization_readback, apply_refresh_receipt, apply_refresh_readback, apply_validation,
    expected_lifecycle_mutations, expected_merge, expected_refresh_authorization, expected_refresh_authorization_comment,
    expected_refresh_trigger, final_batch_report, record_lifecycle_mutations, record_merge_attempt,
    record_refresh_authorization_persisted, record_refresh_trigger, start_batch_execution,
)
from scripts.agent_os_issue_acceptance.batch_post_merge_reconciliation import (
    PostMergeCandidateProjection, TerminalLifecycleDisposition,
)
from scripts.agent_os_issue_acceptance.pr_batch_merge_plan import PrBatchItemEvidence, build_pr_batch_merge_plan
from scripts.agent_os_issue_labels.pr_branch_refresh_authorization_source import (
    RefreshAuthorizationReceipt, RefreshAuthorizationSourceResult, RefreshAuthorizationSourceStatus,
)

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


def test_2668_behind_candidate_materializes_existing_refresh_authorization_and_trigger():
    main="a"*40; head="b"*40; new_head="c"*40
    c=start_batch_execution(plan(11,12),linked_issues={11:101})
    c=apply_current_state(c,current(11,main,head,"behind"))
    assert c.action is BatchMergeAction.REFRESH_AUTHORIZE
    prep=RefreshPreparationEvidence(
        11,main,head,("scripts/a.py","tests/test_a.py"),(".github/workflows/blocked.yml",),
        ("pytest:batch-merge",),"chatgpt-user:batch-merge-rest",True,
    )
    auth=expected_refresh_authorization(c,prep,repository="Blummer92/agent-os")
    assert auth.expected_head_sha==head and auth.expected_main_sha==main
    assert auth.branch_refresh_authorized is True and auth.label_write_authorized is False
    assert expected_refresh_authorization_comment(c,prep,repository="Blummer92/agent-os").startswith("agent-os-pr-refresh-authorization/v1\n")
    c=record_refresh_authorization_persisted(c,pull_request_number=11,authorization_id=auth.authorization_id,accepted=True)
    source=RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.CURRENT,("current",),(auth,),(),(101,))
    c=apply_refresh_authorization_readback(c,source)
    assert c.action is BatchMergeAction.REFRESH_TRIGGER
    trigger=expected_refresh_trigger(c,RefreshTriggerDestinationEvidence(101,"open",False))
    assert trigger.target_issue_number==101
    assert trigger.body=="/agent-os refresh-pr 11"
    c=record_refresh_trigger(c,pull_request_number=11,accepted=True)
    receipt=RefreshAuthorizationReceipt(
        schema_version="1.0",repository="Blummer92/agent-os",pr_number=11,
        authorization_id=auth.authorization_id,admitted_head_sha=head,admitted_main_sha=main,
        mutation_attempted=True,mutation_succeeded=True,terminal_status="converged",reason_codes=("refreshed",),
    )
    consumed=RefreshAuthorizationSourceResult(
        RefreshAuthorizationSourceStatus.STALE,("authorization.consumed-or-not-current",),(),(receipt,),(101,102),
    )
    c=apply_refresh_receipt(c,consumed)
    assert c.action is BatchMergeAction.REFRESH
    c=apply_refresh_readback(c,current(11,main,new_head,"current"))
    assert c.action is BatchMergeAction.VALIDATE and c.current_head_sha==new_head
    assert c.pending_refresh_authorization_id is None


def test_2746_refresh_trigger_requires_open_non_pr_linked_issue():
    main="a"*40; head="b"*40
    c=start_batch_execution(plan(11),linked_issues={11:101})
    c=apply_current_state(c,current(11,main,head,"behind"))
    prep=RefreshPreparationEvidence(11,main,head,("scripts/a.py",),(),(),"owner-decision",True)
    auth=expected_refresh_authorization(c,prep,repository="Blummer92/agent-os")
    c=record_refresh_authorization_persisted(c,pull_request_number=11,authorization_id=auth.authorization_id,accepted=True)
    c=apply_refresh_authorization_readback(c,RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.CURRENT,("current",),(auth,),(),(1,)))
    trigger=expected_refresh_trigger(c,RefreshTriggerDestinationEvidence(101,"open",False))
    assert trigger.target_issue_number==101 and trigger.body=="/agent-os refresh-pr 11"
    for evidence,reason in (
        (RefreshTriggerDestinationEvidence(101,"open",True),"pr-not-allowed"),
        (RefreshTriggerDestinationEvidence(101,"closed",False),"closed"),
        (RefreshTriggerDestinationEvidence(102,"open",False),"mismatch"),
        (RefreshTriggerDestinationEvidence(101,"open",False,False),"unavailable"),
    ):
        try:
            expected_refresh_trigger(c,evidence)
            assert False, "invalid refresh trigger destination must fail closed"
        except ValueError as exc:
            assert reason in str(exc)


def test_2746_refresh_trigger_requires_linked_issue():
    main="a"*40; head="b"*40
    c=start_batch_execution(plan(11))
    c=apply_current_state(c,current(11,main,head,"behind"))
    prep=RefreshPreparationEvidence(11,main,head,("scripts/a.py",),(),(),"owner-decision",True)
    auth=expected_refresh_authorization(c,prep,repository="Blummer92/agent-os")
    c=record_refresh_authorization_persisted(c,pull_request_number=11,authorization_id=auth.authorization_id,accepted=True)
    c=apply_refresh_authorization_readback(c,RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.CURRENT,("current",),(auth,),(),(1,)))
    try:
        expected_refresh_trigger(c,RefreshTriggerDestinationEvidence(101,"open",False))
        assert False, "missing linked issue must fail closed"
    except ValueError as exc:
        assert "destination-missing" in str(exc)


def test_2668_refresh_authorization_fails_closed_on_stale_owner_or_identity():
    main="a"*40; head="b"*40
    c=start_batch_execution(plan(11))
    c=apply_current_state(c,current(11,main,head,"behind"))
    stale=RefreshPreparationEvidence(11,main,head,("scripts/a.py",),(),(),"owner-decision",False)
    try:
        expected_refresh_authorization(c,stale,repository="Blummer92/agent-os")
        assert False, "stale owner decision must fail closed"
    except ValueError as exc:
        assert "current owner decision" in str(exc)
    moved=RefreshPreparationEvidence(11,"d"*40,head,("scripts/a.py",),(),(),"owner-decision",True)
    try:
        expected_refresh_authorization(c,moved,repository="Blummer92/agent-os")
        assert False, "moved main must fail closed"
    except ValueError as exc:
        assert "stale" in str(exc)


def test_2668_missing_receipt_is_item_local_and_batch_continues():
    main="a"*40; head="b"*40
    c=start_batch_execution(plan(11,12))
    c=apply_current_state(c,current(11,main,head,"behind"))
    prep=RefreshPreparationEvidence(11,main,head,("scripts/a.py",),(),(),"owner-decision",True)
    auth=expected_refresh_authorization(c,prep,repository="Blummer92/agent-os")
    c=record_refresh_authorization_persisted(c,pull_request_number=11,authorization_id=auth.authorization_id,accepted=True)
    c=apply_refresh_authorization_readback(c,RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.CURRENT,("current",),(auth,),(),(1,)))
    c=record_refresh_trigger(c,pull_request_number=11,accepted=True)
    c=apply_refresh_receipt(c,RefreshAuthorizationSourceResult(RefreshAuthorizationSourceStatus.STALE,("authorization.consumed-or-not-current",),(),(),(1,)))
    assert c.current_pull_request==12
    assert c.results[-1].disposition is BatchItemDisposition.SKIPPED_ITEM_LOCAL
    assert c.results[-1].reason_codes==("refresh-receipt-missing-or-ambiguous",)
