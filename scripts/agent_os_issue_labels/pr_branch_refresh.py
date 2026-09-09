from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import LifecycleMutationAdmissionResult

from .pr_lifecycle import PullRequestLifecycleReconciliationResult, reconcile_pull_request_lifecycle
from .pr_reconciler import PullRequestLabelProvider

_INVALIDATED_HEAD_EVIDENCE = (
    "approval-applicability", "branch-freshness", "candidate-runtime", "focused-validation",
    "lifecycle-reconciliation", "merge-authorization", "ready-for-review", "review-applicability", "tested-sha",
)

@dataclass(frozen=True, slots=True)
class PullRequestBranchSnapshot:
    repository: str; pr_number: int; base_branch: str; base_sha: str; head_branch: str; head_sha: str
    current_main_sha: str; branch_state: str; mergeability: str; changed_paths: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class BranchRefreshMutationResult:
    status: str; old_head_sha: str; new_head_sha: str | None = None; reason_code: str | None = None

@dataclass(frozen=True, slots=True)
class BranchRefreshValidationResult:
    head_sha: str; status: str; command_ids: tuple[str, ...]

class PullRequestBranchRefreshProvider(PullRequestLabelProvider, Protocol):
    def read_branch(self, repository: str, pr_number: int) -> PullRequestBranchSnapshot: ...
    def rebase_onto_main(self, repository: str, pr_number: int, *, expected_head_sha: str, expected_base_sha: str, current_main_sha: str) -> BranchRefreshMutationResult: ...
    def run_required_validation(self, repository: str, pr_number: int, *, head_sha: str, command_ids: tuple[str, ...]) -> BranchRefreshValidationResult: ...

@dataclass(frozen=True, slots=True)
class PullRequestBranchRefreshRequest:
    repository: str; pr_number: int; base_branch: str; expected_base_sha: str; expected_head_sha: str; current_main_sha: str
    authorization_id: str; authorization_current: bool; allowed_changed_paths: tuple[str, ...]; forbidden_paths: tuple[str, ...]
    required_validation_command_ids: tuple[str, ...]; branch_refresh_authorized: bool
    lifecycle_admission: LifecycleMutationAdmissionResult | None = None

@dataclass(frozen=True, slots=True)
class PullRequestBranchRefreshResult:
    repository: str; pr_number: int; status: str; old_head_sha: str; new_head_sha: str | None
    invalidated_head_evidence: tuple[str, ...]; validation: BranchRefreshValidationResult | None
    lifecycle_reconciliation: PullRequestLifecycleReconciliationResult | None; reason_codes: tuple[str, ...]
    branch_refresh_authorized: bool; side_effects_performed: bool; mutation_attempted: bool = False
    automatic_retry_authorized: bool = field(default=False, init=False); merge_authorized: bool = field(default=False, init=False)
    ready_for_review_authorized: bool = field(default=False, init=False); issue_closure_authorized: bool = field(default=False, init=False)
    repository_setting_authorized: bool = field(default=False, init=False); workflow_authorized: bool = field(default=False, init=False)
    def __post_init__(self):
        if self.side_effects_performed and not self.mutation_attempted: object.__setattr__(self, "mutation_attempted", True)

def refresh_pull_request_branch(provider: PullRequestBranchRefreshProvider, request: PullRequestBranchRefreshRequest) -> PullRequestBranchRefreshResult:
    _validate_request(request); before=provider.read_branch(request.repository, request.pr_number); blocker=_admission_blocker(before, request)
    if blocker: return _result(request,"blocked",request.expected_head_sha,reasons=(blocker,))
    mutation=provider.rebase_onto_main(request.repository,request.pr_number,expected_head_sha=request.expected_head_sha,expected_base_sha=request.expected_base_sha,current_main_sha=request.current_main_sha)
    if mutation.status != "updated" or mutation.new_head_sha is None:
        return _result(request,"manual-review" if mutation.status=="ambiguous" else "blocked",mutation.old_head_sha,reasons=(mutation.reason_code or f"refresh.{mutation.status}",),mutation_attempted=True)
    after=provider.read_branch(request.repository,request.pr_number); post=_post_refresh_blocker(before,after,mutation,request)
    if post: return _result(request,"blocked",before.head_sha,new_head=mutation.new_head_sha,reasons=(post,),side_effects=True,mutation_attempted=True)
    validation=provider.run_required_validation(request.repository,request.pr_number,head_sha=mutation.new_head_sha,command_ids=request.required_validation_command_ids)
    if validation.head_sha != mutation.new_head_sha: return _result(request,"blocked",before.head_sha,new_head=mutation.new_head_sha,validation=validation,reasons=("validation.head-mismatch",),side_effects=True,mutation_attempted=True)
    lifecycle=reconcile_pull_request_lifecycle(provider,request.repository,request.pr_number,invocation_reason="validation-terminal",caller_operation_evidence=f"branch-refresh:{request.authorization_id}",caller_result_evidence=f"validation:{validation.status}:{validation.head_sha}",dry_run=False,lifecycle_admission=request.lifecycle_admission)
    if lifecycle.reconciliation_status != "converged": return _result(request,"blocked",before.head_sha,new_head=mutation.new_head_sha,validation=validation,lifecycle=lifecycle,reasons=("labels.convergence-not-proven",),side_effects=True,mutation_attempted=True)
    final=provider.read_branch(request.repository,request.pr_number)
    if final.current_main_sha != request.current_main_sha: return _result(request,"stale",before.head_sha,new_head=mutation.new_head_sha,validation=validation,lifecycle=lifecycle,reasons=("main.moved-before-final-proof",),side_effects=True,mutation_attempted=True)
    if final.head_sha != mutation.new_head_sha or final.branch_state != "current" or final.mergeability == "conflicted": return _result(request,"blocked",before.head_sha,new_head=mutation.new_head_sha,validation=validation,lifecycle=lifecycle,reasons=("branch.current-not-proven",),side_effects=True,mutation_attempted=True)
    return _result(request,"converged" if validation.status=="green" else "validation-failing",before.head_sha,new_head=mutation.new_head_sha,validation=validation,lifecycle=lifecycle,reasons=("refresh.rebased","head-evidence.invalidated","branch.current-proven"),side_effects=True,mutation_attempted=True)

def _validate_request(request):
    for value,name in ((request.expected_base_sha,"expected_base_sha"),(request.expected_head_sha,"expected_head_sha"),(request.current_main_sha,"current_main_sha")):
        if len(value)!=40 or any(c not in "0123456789abcdef" for c in value.lower()): raise ValueError(f"{name} must be a full 40-character hexadecimal commit identity")
    if request.pr_number<1 or request.repository.count("/")!=1: raise ValueError("repository and pr_number must be exact")
    if not request.authorization_id.strip(): raise ValueError("authorization_id is required")
    if not request.required_validation_command_ids: raise ValueError("required validation commands are required")
    if len(set(request.allowed_changed_paths))!=len(request.allowed_changed_paths) or len(set(request.forbidden_paths))!=len(request.forbidden_paths): raise ValueError("path evidence must be unique")

def _admission_blocker(snapshot,request):
    if not request.branch_refresh_authorized or not request.authorization_current: return "authorization.refresh-required"
    if snapshot.repository!=request.repository or snapshot.pr_number!=request.pr_number or snapshot.base_branch!=request.base_branch: return "identity.mismatch"
    if snapshot.base_sha!=request.expected_base_sha or snapshot.current_main_sha!=request.current_main_sha: return "base.moved-before-refresh"
    if snapshot.head_sha!=request.expected_head_sha: return "head.moved-before-refresh"
    if snapshot.branch_state=="current": return "branch.refresh-not-required"
    if snapshot.branch_state!="behind" or snapshot.mergeability=="unknown": return "branch.refresh-not-eligible"
    return _path_blocker(snapshot.changed_paths,request)

def _post_refresh_blocker(before,after,mutation,request):
    if mutation.old_head_sha!=before.head_sha or mutation.new_head_sha==before.head_sha: return "refresh.head-identity-invalid"
    if after.head_sha!=mutation.new_head_sha: return "refresh.remote-head-mismatch"
    if after.current_main_sha!=request.current_main_sha: return "main.moved-after-refresh"
    if after.branch_state!="current" or after.mergeability=="conflicted": return "refresh.current-state-not-proven"
    return _path_blocker(after.changed_paths,request)

def _path_blocker(paths,request):
    s=set(paths)
    if s & set(request.forbidden_paths): return "scope.forbidden-path"
    if not s.issubset(set(request.allowed_changed_paths)): return "scope.expanded-after-refresh"
    return None

def _result(request,status,old_head,*,new_head=None,validation=None,lifecycle=None,reasons=(),side_effects=False,mutation_attempted=False):
    return PullRequestBranchRefreshResult(request.repository,request.pr_number,status,old_head,new_head,_INVALIDATED_HEAD_EVIDENCE if side_effects else (),validation,lifecycle,tuple(sorted(set(reasons))),request.branch_refresh_authorized,side_effects,mutation_attempted)
