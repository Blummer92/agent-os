"""Finite sequential BM2 coordinator over canonical per-PR owners.

The coordinator owns batch progression only. It never retrieves GitHub state,
refreshes a branch, validates code, grants merge/closure authority, merges a PR,
or mutates an issue. Each transition consumes freshly reacquired evidence and
emits the next bounded operation for an existing canonical owner.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal
from .pr_batch_merge_plan import PrBatchDisposition, PrBatchMergePlan
from .batch_post_merge_reconciliation import PostMergeCandidateProjection, TerminalLifecycleDisposition
from scripts.agent_os_issue_labels.pr_branch_refresh_authorization import (
    SCHEMA_VERSION as REFRESH_AUTHORIZATION_SCHEMA_VERSION,
    RefreshAuthorization,
    RefreshAuthorizationState,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_authorization_source import (
    RefreshAuthorizationSourceResult,
    RefreshAuthorizationSourceStatus,
    serialize_refresh_authorization_comment,
)

class BatchMergeAction(str, Enum):
    REACQUIRE="reacquire-current-state"; REFRESH_AUTHORIZE="materialize-refresh-authorization"
    REFRESH_AUTH_READBACK="read-back-refresh-authorization"; REFRESH_TRIGGER="invoke-governed-refresh"
    REFRESH_RECEIPT="read-back-refresh-receipt"; REFRESH="read-back-refreshed-pr"; VALIDATE="obtain-exact-head-validation"
    AUTHORIZE="obtain-content-bound-merge-authorization"; MERGE="merge-exact-expected-head"; READBACK="read-back-merged-pr-and-main"
    POST_MERGE="reconcile-linked-issue"; LIFECYCLE_MUTATE="perform-admitted-lifecycle-mutations"; LIFECYCLE_READBACK="read-back-linked-issue"
    COMPLETE="complete"; HALT="halt"
class BatchItemDisposition(str, Enum):
    MERGED="merged"; MERGED_ISSUE_CLOSED="merged-issue-closed"; MERGED_ISSUE_INCOMPLETE="merged-issue-incomplete"
    MERGED_AWAITING_CLOSURE="merged-awaiting-closure-authorization"; ALREADY_TERMINAL="already-terminal"
    SKIPPED_ITEM_LOCAL="skipped-item-local"; BLOCKED_SHARED="blocked-shared"; MANUAL_REVIEW="manual-review"
@dataclass(frozen=True, slots=True)
class CurrentPrEvidence:
    pull_request_number:int; main_sha:str; head_sha:str; state:Literal["open","closed","merged"]
    branch_freshness:Literal["current","behind","diverged","unknown"]; semantic_conflict:bool=False; provider_available:bool=True
    def __post_init__(self):
        if type(self.pull_request_number) is not int or self.pull_request_number<1: raise ValueError("pull_request_number must be a positive integer")
        if not self.main_sha or not self.head_sha: raise ValueError("main_sha and head_sha are required fresh identities")
        if self.state not in {"open","closed","merged"}: raise ValueError("state is non-canonical")
        if self.branch_freshness not in {"current","behind","diverged","unknown"}: raise ValueError("branch_freshness is non-canonical")
        if type(self.semantic_conflict) is not bool or type(self.provider_available) is not bool: raise TypeError("current PR boolean evidence must be bool")
@dataclass(frozen=True, slots=True)
class RefreshPreparationEvidence:
    pull_request_number:int; main_sha:str; head_sha:str; changed_paths:tuple[str,...]
    forbidden_paths:tuple[str,...]; required_validation_command_ids:tuple[str,...]
    owner_decision_reference:str; owner_decision_current:bool
    def __post_init__(self):
        if type(self.pull_request_number) is not int or self.pull_request_number<1: raise ValueError("pull_request_number must be a positive integer")
        if not self.main_sha or not self.head_sha: raise ValueError("main_sha and head_sha are required")
        for value,name in ((self.changed_paths,"changed_paths"),(self.forbidden_paths,"forbidden_paths"),(self.required_validation_command_ids,"required_validation_command_ids")):
            if type(value) is not tuple or any(type(item) is not str or not item for item in value): raise TypeError(f"{name} must be an exact tuple of non-empty strings")
        if not self.owner_decision_reference.strip(): raise ValueError("owner_decision_reference is required")
        if type(self.owner_decision_current) is not bool: raise TypeError("owner_decision_current must be bool")

@dataclass(frozen=True, slots=True)
class RefreshTriggerDestinationEvidence:
    issue_number:int; state:Literal["open","closed"]; is_pull_request:bool; provider_available:bool=True
    def __post_init__(self):
        if type(self.issue_number) is not int or self.issue_number<1: raise ValueError("issue_number must be a positive integer")
        if self.state not in {"open","closed"}: raise ValueError("state is non-canonical")
        if type(self.is_pull_request) is not bool or type(self.provider_available) is not bool: raise TypeError("refresh trigger destination booleans must be bool")
@dataclass(frozen=True, slots=True)
class RefreshTriggerProjection:
    target_issue_number:int; body:str
@dataclass(frozen=True, slots=True)
class ItemAdmissionEvidence:
    pull_request_number:int; main_sha:str; head_sha:str; validation_status:Literal["passed","failed","pending","missing","manual-review"]
    authorization_status:Literal["authorized","blocked","stale","missing","manual-review"]
@dataclass(frozen=True, slots=True)
class MergeReadbackEvidence:
    pull_request_number:int; expected_head_sha:str; merged:bool; new_main_sha:str; provider_available:bool=True
    def __post_init__(self):
        if type(self.merged) is not bool or type(self.provider_available) is not bool: raise TypeError("merge readback boolean evidence must be bool")
@dataclass(frozen=True, slots=True)
class BatchItemResult:
    pull_request_number:int; disposition:BatchItemDisposition; starting_head_sha:str|None; final_head_sha:str|None
    starting_main_sha:str|None; final_main_sha:str|None; reason_codes:tuple[str,...]; issue_number:int|None=None
@dataclass(frozen=True, slots=True)
class BatchMergeCursor:
    requested_pull_requests:tuple[int,...]; linked_issues:tuple[tuple[int,int],...]=(); index:int=0; current_main_sha:str|None=None
    current_head_sha:str|None=None; pending_merged_main_sha:str|None=None; results:tuple[BatchItemResult,...]=()
    action:BatchMergeAction=BatchMergeAction.REACQUIRE; halted:bool=False
    pending_lifecycle_snapshot_id:str|None=None; pending_operational_state_id:str|None=None
    pending_refresh_authorization_id:str|None=None
    merge_authorized:Literal[False]=field(default=False,init=False); side_effects_performed:Literal[False]=field(default=False,init=False)
    @property
    def current_pull_request(self): return None if self.index>=len(self.requested_pull_requests) else self.requested_pull_requests[self.index]
    @property
    def current_issue_number(self):
        pr=self.current_pull_request
        return dict(self.linked_issues).get(pr) if pr is not None else None

def start_batch_execution(plan:PrBatchMergePlan, *, linked_issues:dict[int,int]|None=None)->BatchMergeCursor:
    if type(plan) is not PrBatchMergePlan: raise TypeError("plan must be PrBatchMergePlan")
    links=linked_issues or {}
    if any(type(p) is not int or type(i) is not int or p<1 or i<1 for p,i in links.items()): raise ValueError("linked issue identities must be positive integers")
    admitted=[]; results=[]
    for item in plan.items:
        if item.disposition is PrBatchDisposition.CANDIDATE: admitted.append(item.pull_request_number)
        elif item.disposition is PrBatchDisposition.ALREADY_TERMINAL: results.append(_result(item.pull_request_number,BatchItemDisposition.ALREADY_TERMINAL,"bm1-already-terminal"))
        elif item.disposition is PrBatchDisposition.ITEM_LOCAL_BLOCKED: results.append(_result(item.pull_request_number,BatchItemDisposition.SKIPPED_ITEM_LOCAL,"bm1-item-local-blocked"))
        else:
            results.append(_result(item.pull_request_number,BatchItemDisposition.BLOCKED_SHARED,"bm1-shared-blocked"))
            return BatchMergeCursor(tuple(admitted),tuple(sorted(links.items())),results=tuple(results),action=BatchMergeAction.HALT,halted=True)
    return BatchMergeCursor(tuple(admitted),tuple(sorted(links.items())),results=tuple(results),action=BatchMergeAction.REACQUIRE if admitted else BatchMergeAction.COMPLETE)

def apply_current_state(c,e):
    _expect(c,BatchMergeAction.REACQUIRE,e.pull_request_number)
    if not e.provider_available or e.branch_freshness=="unknown": return _halt(c,e,"canonical-state-unavailable")
    if e.state=="merged" and c.current_issue_number is not None:
        return _replace(c,current_main_sha=e.main_sha,current_head_sha=e.head_sha,pending_merged_main_sha=e.main_sha,action=BatchMergeAction.POST_MERGE)
    if e.state in {"closed","merged"}: return _advance(c,_result(e.pull_request_number,BatchItemDisposition.ALREADY_TERMINAL,"pr-already-terminal",e))
    if e.semantic_conflict:return _advance(c,_result(e.pull_request_number,BatchItemDisposition.SKIPPED_ITEM_LOCAL,"semantic-conflict",e))
    return _replace(c,current_main_sha=e.main_sha,current_head_sha=e.head_sha,action=BatchMergeAction.REFRESH_AUTHORIZE if e.branch_freshness in {"behind","diverged"} else BatchMergeAction.VALIDATE)

def expected_refresh_authorization(c,e,*,repository):
    _expect(c,BatchMergeAction.REFRESH_AUTHORIZE,e.pull_request_number)
    if not _same(c,e.main_sha,e.head_sha): raise ValueError("refresh evidence is stale")
    if not e.owner_decision_current: raise ValueError("current owner decision is required")
    if set(e.changed_paths) & set(e.forbidden_paths): raise ValueError("changed paths cross forbidden refresh scope")
    return RefreshAuthorization(
        schema_version=REFRESH_AUTHORIZATION_SCHEMA_VERSION,
        repository=repository,
        pr_number=e.pull_request_number,
        base_branch="main",
        expected_head_sha=e.head_sha,
        expected_main_sha=e.main_sha,
        allowed_changed_paths=e.changed_paths,
        forbidden_paths=e.forbidden_paths,
        required_validation_command_ids=e.required_validation_command_ids,
        branch_refresh_authorized=True,
        label_write_authorized=False,
        owner_decision_reference=e.owner_decision_reference,
        state=RefreshAuthorizationState.AUTHORIZED,
    )

def expected_refresh_authorization_comment(c,e,*,repository):
    return serialize_refresh_authorization_comment(expected_refresh_authorization(c,e,repository=repository))

def record_refresh_authorization_persisted(c,*,pull_request_number,authorization_id,accepted):
    _expect(c,BatchMergeAction.REFRESH_AUTHORIZE,pull_request_number)
    if type(accepted) is not bool: raise TypeError("accepted must be bool")
    if not accepted:
        return _advance(c,_result(pull_request_number,BatchItemDisposition.SKIPPED_ITEM_LOCAL,"refresh-authorization-persistence-failed",cursor=c))
    if type(authorization_id) is not str or not authorization_id.startswith("refresh-authorization:"):
        raise ValueError("authorization_id is malformed")
    return _replace(c,pending_refresh_authorization_id=authorization_id,action=BatchMergeAction.REFRESH_AUTH_READBACK)

def apply_refresh_authorization_readback(c,source):
    _expect(c,BatchMergeAction.REFRESH_AUTH_READBACK,c.current_pull_request)
    if type(source) is not RefreshAuthorizationSourceResult: raise TypeError("source must be RefreshAuthorizationSourceResult")
    if source.status is RefreshAuthorizationSourceStatus.NEEDS_DECISION:
        return _halt(c,None,"refresh-authorization-source-unavailable")
    matching=[record for record in source.records if record.authorization_id==c.pending_refresh_authorization_id]
    if source.status is not RefreshAuthorizationSourceStatus.CURRENT or len(matching)!=1:
        return _advance(c,_result(c.current_pull_request,BatchItemDisposition.SKIPPED_ITEM_LOCAL,"refresh-authorization-readback-not-current",cursor=c))
    return _replace(c,action=BatchMergeAction.REFRESH_TRIGGER)

def expected_refresh_trigger(c,e):
    if c.action is not BatchMergeAction.REFRESH_TRIGGER or c.current_pull_request is None:
        raise ValueError("cursor is not ready to invoke governed refresh")
    if type(e) is not RefreshTriggerDestinationEvidence:
        raise TypeError("refresh trigger destination evidence is required")
    if c.current_issue_number is None:
        raise ValueError("refresh-trigger-destination-missing")
    if not e.provider_available:
        raise ValueError("refresh-trigger-destination-unavailable")
    if e.issue_number!=c.current_issue_number:
        raise ValueError("refresh-trigger-destination-mismatch")
    if e.state!="open":
        raise ValueError("refresh-trigger-destination-closed")
    if e.is_pull_request or e.issue_number==c.current_pull_request:
        raise ValueError("refresh-trigger-destination-pr-not-allowed")
    return RefreshTriggerProjection(e.issue_number,f"/agent-os refresh-pr {c.current_pull_request}")

def record_refresh_trigger(c,*,pull_request_number,accepted):
    _expect(c,BatchMergeAction.REFRESH_TRIGGER,pull_request_number)
    if type(accepted) is not bool: raise TypeError("accepted must be bool")
    if not accepted:
        return _advance(c,_result(pull_request_number,BatchItemDisposition.SKIPPED_ITEM_LOCAL,"refresh-trigger-rejected",cursor=c))
    return _replace(c,action=BatchMergeAction.REFRESH_RECEIPT)

def apply_refresh_receipt(c,source):
    _expect(c,BatchMergeAction.REFRESH_RECEIPT,c.current_pull_request)
    if type(source) is not RefreshAuthorizationSourceResult: raise TypeError("source must be RefreshAuthorizationSourceResult")
    if source.status is RefreshAuthorizationSourceStatus.NEEDS_DECISION:
        return _halt(c,None,"refresh-receipt-source-unavailable")
    matching=[receipt for receipt in source.receipts if receipt.authorization_id==c.pending_refresh_authorization_id]
    if len(matching)!=1:
        return _advance(c,_result(c.current_pull_request,BatchItemDisposition.SKIPPED_ITEM_LOCAL,"refresh-receipt-missing-or-ambiguous",cursor=c))
    receipt=matching[0]
    if not receipt.mutation_attempted or not receipt.mutation_succeeded or receipt.terminal_status!="converged":
        return _advance(c,_result(c.current_pull_request,BatchItemDisposition.SKIPPED_ITEM_LOCAL,"refresh-receipt-not-converged",cursor=c))
    return _replace(c,action=BatchMergeAction.REFRESH)

def apply_refresh_readback(c,e):
    _expect(c,BatchMergeAction.REFRESH,e.pull_request_number)
    if not e.provider_available:return _halt(c,e,"refresh-readback-unavailable")
    if e.semantic_conflict:return _advance(c,_result(e.pull_request_number,BatchItemDisposition.SKIPPED_ITEM_LOCAL,"refresh-semantic-conflict",e))
    if e.state!="open" or e.branch_freshness!="current":return _halt(c,e,"refresh-currentness-unproven")
    return _replace(c,current_main_sha=e.main_sha,current_head_sha=e.head_sha,pending_refresh_authorization_id=None,action=BatchMergeAction.VALIDATE)
def apply_validation(c,e):
    _expect(c,BatchMergeAction.VALIDATE,e.pull_request_number)
    if not _same(c,e.main_sha,e.head_sha):return _restart(c)
    if e.validation_status=="passed":return _replace(c,action=BatchMergeAction.AUTHORIZE)
    d=BatchItemDisposition.MANUAL_REVIEW if e.validation_status=="manual-review" else BatchItemDisposition.SKIPPED_ITEM_LOCAL
    return _advance(c,_result(e.pull_request_number,d,f"validation-{e.validation_status}",cursor=c))
def apply_merge_authorization(c,e):
    _expect(c,BatchMergeAction.AUTHORIZE,e.pull_request_number)
    if not _same(c,e.main_sha,e.head_sha) or e.validation_status!="passed":return _restart(c)
    if e.authorization_status=="authorized":return _replace(c,action=BatchMergeAction.MERGE)
    d=BatchItemDisposition.MANUAL_REVIEW if e.authorization_status=="manual-review" else BatchItemDisposition.SKIPPED_ITEM_LOCAL
    return _advance(c,_result(e.pull_request_number,d,f"authorization-{e.authorization_status}",cursor=c))
def expected_merge(c):
    if c.action is not BatchMergeAction.MERGE or c.current_pull_request is None or c.current_head_sha is None:raise ValueError("cursor is not ready for an exact-head merge")
    return c.current_pull_request,c.current_head_sha
def record_merge_attempt(c,*,pull_request_number,expected_head_sha,accepted):
    _expect(c,BatchMergeAction.MERGE,pull_request_number)
    if type(accepted) is not bool: raise TypeError("accepted must be bool")
    if expected_head_sha!=c.current_head_sha:return _restart(c)
    if not accepted:return _advance(c,_result(pull_request_number,BatchItemDisposition.SKIPPED_ITEM_LOCAL,"expected-head-merge-rejected",cursor=c))
    return _replace(c,action=BatchMergeAction.READBACK)
def apply_merge_readback(c,e):
    _expect(c,BatchMergeAction.READBACK,e.pull_request_number)
    if not e.provider_available:return _halt(c,None,"post-merge-readback-unavailable")
    if e.expected_head_sha!=c.current_head_sha or not e.merged or not e.new_main_sha:return _halt(c,None,"post-merge-terminal-proof-failed")
    if c.current_issue_number is not None:return _replace(c,pending_merged_main_sha=e.new_main_sha,action=BatchMergeAction.POST_MERGE)
    return _advance(c,_result(e.pull_request_number,BatchItemDisposition.MERGED,"merged-no-linked-issue",cursor=c),new_main=e.new_main_sha)
def apply_post_merge_reconciliation(c,p):
    _expect(c,BatchMergeAction.POST_MERGE,p.pull_request_number)
    if type(p) is not PostMergeCandidateProjection or p.issue_number!=c.current_issue_number:raise ValueError("projection does not match current linked issue")
    if p.requires_final_readback:return _replace(c,action=BatchMergeAction.LIFECYCLE_MUTATE,pending_lifecycle_snapshot_id=p.lifecycle_snapshot_id,pending_operational_state_id=p.operational_state_id)
    if p.disposition is TerminalLifecycleDisposition.CLOSED_COMPLETED and p.converged:return _finish_linked(c,BatchItemDisposition.MERGED_ISSUE_CLOSED,p.reason_codes)
    if p.disposition is TerminalLifecycleDisposition.MERGED_AWAITING_CLOSURE_AUTHORIZATION:return _finish_linked(c,BatchItemDisposition.MERGED_AWAITING_CLOSURE,p.reason_codes)
    if p.disposition is TerminalLifecycleDisposition.MERGED_ISSUE_NOT_COMPLETE:return _finish_linked(c,BatchItemDisposition.MERGED_ISSUE_INCOMPLETE,p.reason_codes)
    return _finish_linked(c,BatchItemDisposition.MANUAL_REVIEW,p.reason_codes)
def expected_lifecycle_mutations(c,p):
    _expect(c,BatchMergeAction.LIFECYCLE_MUTATE,p.pull_request_number)
    if p.issue_number!=c.current_issue_number or not p.requires_final_readback or p.lifecycle_snapshot_id!=c.pending_lifecycle_snapshot_id or p.operational_state_id!=c.pending_operational_state_id:raise ValueError("projection is not the current admitted lifecycle plan")
    return p.issue_number,p.remove_status_ready,p.close_issue
def record_lifecycle_mutations(c,*,issue_number,accepted):
    if c.action is not BatchMergeAction.LIFECYCLE_MUTATE or issue_number!=c.current_issue_number:raise ValueError("lifecycle mutation does not match current issue")
    if type(accepted) is not bool: raise TypeError("accepted must be bool")
    if not accepted:return _finish_linked(c,BatchItemDisposition.MANUAL_REVIEW,("admitted-lifecycle-mutation-rejected",))
    return _replace(c,action=BatchMergeAction.LIFECYCLE_READBACK)
def apply_lifecycle_readback(c,p):
    _expect(c,BatchMergeAction.LIFECYCLE_READBACK,p.pull_request_number)
    if p.issue_number!=c.current_issue_number or p.lifecycle_snapshot_id!=c.pending_lifecycle_snapshot_id or p.operational_state_id!=c.pending_operational_state_id or not p.converged or p.disposition is not TerminalLifecycleDisposition.CLOSED_COMPLETED:return _halt(c,None,"linked-issue-terminal-readback-failed")
    return _finish_linked(c,BatchItemDisposition.MERGED_ISSUE_CLOSED,p.reason_codes)
def final_batch_report(c):
    if c.action not in {BatchMergeAction.COMPLETE,BatchMergeAction.HALT}:raise ValueError("batch is not terminal")
    return c.results
def _finish_linked(c,d,reasons):return _advance(c,BatchItemResult(c.current_pull_request,d,c.current_head_sha,c.current_head_sha,c.current_main_sha,c.pending_merged_main_sha,tuple(reasons),c.current_issue_number),new_main=c.pending_merged_main_sha)
def _expect(c,a,pr):
    if type(c) is not BatchMergeCursor or c.action is not a or c.current_pull_request!=pr:raise ValueError("evidence does not match the current batch transition")
def _same(c,main,head):return main==c.current_main_sha and head==c.current_head_sha
def _restart(c):return _replace(c,current_main_sha=None,current_head_sha=None,pending_merged_main_sha=None,pending_lifecycle_snapshot_id=None,pending_operational_state_id=None,pending_refresh_authorization_id=None,action=BatchMergeAction.REACQUIRE)
def _advance(c,r,*,new_main=None):
    idx=c.index+1; action=BatchMergeAction.COMPLETE if idx>=len(c.requested_pull_requests) else BatchMergeAction.REACQUIRE
    return BatchMergeCursor(c.requested_pull_requests,c.linked_issues,idx,new_main,None,None,c.results+(r,),action,False)
def _halt(c,e,reason):
    results=c.results; pr=c.current_pull_request
    if pr is not None:results+=(_result(pr,BatchItemDisposition.BLOCKED_SHARED,reason,e,c),)
    return BatchMergeCursor(c.requested_pull_requests,c.linked_issues,c.index,c.current_main_sha,c.current_head_sha,c.pending_merged_main_sha,results,BatchMergeAction.HALT,True,c.pending_lifecycle_snapshot_id,c.pending_operational_state_id)
def _replace(c,**changes):
    v={"requested_pull_requests":c.requested_pull_requests,"linked_issues":c.linked_issues,"index":c.index,"current_main_sha":c.current_main_sha,"current_head_sha":c.current_head_sha,"pending_merged_main_sha":c.pending_merged_main_sha,"results":c.results,"action":c.action,"halted":c.halted,"pending_lifecycle_snapshot_id":c.pending_lifecycle_snapshot_id,"pending_operational_state_id":c.pending_operational_state_id,"pending_refresh_authorization_id":c.pending_refresh_authorization_id};v.update(changes);return BatchMergeCursor(**v)
def _result(pr,d,reason,e=None,cursor=None):
    head=e.head_sha if e else (cursor.current_head_sha if cursor else None);main=e.main_sha if e else (cursor.current_main_sha if cursor else None)
    return BatchItemResult(pr,d,head,head,main,main,(reason,))
