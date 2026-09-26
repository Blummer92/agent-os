"""BR5 pure-local post-merge reconciliation projection; performs no writes."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

class TerminalLifecycleDisposition(str, Enum):
    CLOSED_COMPLETED="closed-completed"
    MERGED_AWAITING_CLOSURE_AUTHORIZATION="merged-awaiting-closure-authorization"
    MERGED_ISSUE_NOT_COMPLETE="merged-issue-not-complete"
    CLOSED_READY_CLEANUP_REQUIRED="closed-ready-cleanup-required"
    MANUAL_REVIEW="manual-review"
class AdmissionState(str, Enum):
    ADMITTED="admitted"; BLOCKED="blocked"; STALE="stale"; INVALID="invalid"; MISSING="missing"
@dataclass(frozen=True, slots=True)
class LifecycleAdmissionEvidence:
    mutation: Literal["close-issue","remove-lifecycle-label"]; state: AdmissionState; result_id: str|None; snapshot_id: str|None
    def __post_init__(self):
        if self.mutation not in {"close-issue","remove-lifecycle-label"}: raise ValueError("unsupported lifecycle mutation")
        if type(self.state) is not AdmissionState: raise TypeError("state must be AdmissionState")
        if self.state is AdmissionState.MISSING:
            if self.result_id is not None or self.snapshot_id is not None: raise ValueError("missing admission cannot carry result/snapshot identity")
        elif not self.result_id or not self.snapshot_id: raise ValueError("non-missing admission requires result_id and snapshot_id")
    @property
    def admitted(self): return self.state is AdmissionState.ADMITTED
@dataclass(frozen=True, slots=True)
class PostMergeCandidateEvidence:
    repository:str; pull_request_number:int; issue_number:int; pr_merged:bool; merge_commit_sha:str|None; current_main_sha:str
    issue_state:Literal["open","closed"]; issue_complete:bool; issue_kind:Literal["implementation","parent","tracking","investigation"]
    remaining_scope:bool; status_ready_present:bool; lifecycle_snapshot_id:str; operational_state_id:str
    closure_authorization_state:Literal["authorized","not-authorized","stale","needs-decision","not-applicable"]
    close_admission:LifecycleAdmissionEvidence; ready_cleanup_admission:LifecycleAdmissionEvidence
    final_disposition_already_published:bool=False; final_readback_pr_merged:bool|None=None
    final_readback_issue_state:Literal["open","closed"]|None=None; final_readback_status_ready_present:bool|None=None; evidence_conflicting:bool=False
    def __post_init__(self):
        if "/" not in self.repository: raise ValueError("repository must be owner/name")
        if type(self.pull_request_number) is not int or self.pull_request_number<1 or type(self.issue_number) is not int or self.issue_number<1: raise ValueError("numbers must be positive integers")
        if self.pr_merged: _sha40(self.merge_commit_sha,"merge_commit_sha")
        elif self.merge_commit_sha is not None: raise ValueError("unmerged PR cannot carry merge_commit_sha")
        _sha40(self.current_main_sha,"current_main_sha")
        if not self.lifecycle_snapshot_id or not self.operational_state_id: raise ValueError("evidence identities must be non-empty")
        if self.close_admission.mutation!="close-issue" or self.ready_cleanup_admission.mutation!="remove-lifecycle-label": raise ValueError("admission mutation mismatch")
        for item in (self.close_admission,self.ready_cleanup_admission):
            if item.snapshot_id is not None and item.snapshot_id!=self.lifecycle_snapshot_id: raise ValueError("lifecycle admission must bind the current lifecycle snapshot")
@dataclass(frozen=True, slots=True)
class PostMergeCandidateProjection:
    pull_request_number:int; issue_number:int; disposition:TerminalLifecycleDisposition; reason_codes:tuple[str,...]
    publish_final_disposition:bool; remove_status_ready:bool; close_issue:bool; requires_final_readback:bool; converged:bool
    lifecycle_snapshot_id:str; operational_state_id:str; side_effects_performed:Literal[False]=field(default=False,init=False)
@dataclass(frozen=True, slots=True)
class BulkPostMergeReconciliationProjection:
    candidates:tuple[PostMergeCandidateProjection,...]; closed_completed_issue_numbers:tuple[int,...]; awaiting_closure_issue_numbers:tuple[int,...]
    incomplete_issue_numbers:tuple[int,...]; ready_cleanup_issue_numbers:tuple[int,...]; manual_review_issue_numbers:tuple[int,...]; next_action:str
    mutation_authorized:Literal[False]=field(default=False,init=False); closure_authorized:Literal[False]=field(default=False,init=False); side_effects_performed:Literal[False]=field(default=False,init=False)
def evaluate_post_merge_candidate(e):
    if type(e) is not PostMergeCandidateEvidence: raise TypeError("evidence must be PostMergeCandidateEvidence")
    if e.evidence_conflicting or not e.pr_merged: return _p(e,TerminalLifecycleDisposition.MANUAL_REVIEW,("merged-state-unproven-or-conflicting",))
    if not (e.issue_complete and not e.remaining_scope): return _p(e,TerminalLifecycleDisposition.MERGED_ISSUE_NOT_COMPLETE,("issue-definition-of-done-not-satisfied",))
    if e.issue_state=="closed":
        if e.status_ready_present:
            ok=e.ready_cleanup_admission.admitted
            return _p(e,TerminalLifecycleDisposition.CLOSED_READY_CLEANUP_REQUIRED,("closed-issue-retains-status-ready",),publish=not e.final_disposition_already_published,remove=ok,readback=ok)
        return _p(e,TerminalLifecycleDisposition.CLOSED_COMPLETED,("already-converged",),converged=True)
    if e.closure_authorization_state!="authorized" or not e.close_admission.admitted: return _p(e,TerminalLifecycleDisposition.MERGED_AWAITING_CLOSURE_AUTHORIZATION,("close-issue-not-currently-admitted",))
    if e.status_ready_present and not e.ready_cleanup_admission.admitted: return _p(e,TerminalLifecycleDisposition.MANUAL_REVIEW,("ready-label-cleanup-not-currently-admitted",))
    converged=_converged(e)
    return _p(e,TerminalLifecycleDisposition.CLOSED_COMPLETED,("terminal-mutations-admitted",),publish=not e.final_disposition_already_published,remove=e.status_ready_present and not converged,close=not converged,readback=not converged,converged=converged)
def evaluate_bulk_post_merge_reconciliation(items):
    if type(items) is not tuple or not items: raise ValueError("evidence must be a non-empty tuple")
    if len({x.issue_number for x in items})!=len(items): raise ValueError("each issue may appear at most once per projection")
    c=tuple(evaluate_post_merge_candidate(x) for x in items); by=lambda d:tuple(x.issue_number for x in c if x.disposition is d)
    manual=by(TerminalLifecycleDisposition.MANUAL_REVIEW); cleanup=by(TerminalLifecycleDisposition.CLOSED_READY_CLEANUP_REQUIRED); awaiting=by(TerminalLifecycleDisposition.MERGED_AWAITING_CLOSURE_AUTHORIZATION)
    if any(x.requires_final_readback for x in c): nxt="perform-admitted-lifecycle-mutations-then-reacquire"
    elif manual:nxt="manual-review-item-local-candidates"
    elif cleanup:nxt="await-ready-label-cleanup-admission"
    elif awaiting:nxt="await-closure-authorization"
    elif all(x.converged for x in c):nxt="report-converged-batch"
    else:nxt="report-nonterminal-item-local-dispositions"
    return BulkPostMergeReconciliationProjection(c,by(TerminalLifecycleDisposition.CLOSED_COMPLETED),awaiting,by(TerminalLifecycleDisposition.MERGED_ISSUE_NOT_COMPLETE),cleanup,manual,nxt)
def _p(e,d,reasons,*,publish=False,remove=False,close=False,readback=False,converged=False):
    return PostMergeCandidateProjection(e.pull_request_number,e.issue_number,d,reasons,publish,remove,close,readback,converged,e.lifecycle_snapshot_id,e.operational_state_id)
def _converged(e): return e.final_readback_pr_merged is True and e.final_readback_issue_state=="closed" and e.final_readback_status_ready_present is False
def _sha40(value,name):
    if type(value) is not str or len(value)!=40 or any(ch not in "0123456789abcdef" for ch in value): raise ValueError(f"{name} must be a lowercase 40-character SHA")
