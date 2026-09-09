from __future__ import annotations

from dataclasses import dataclass, field

from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import LifecycleMutationAdmissionResult

from .pr_reconciler import LivePullRequestSnapshot, PullRequestLabelProvider, PullRequestLabelReconciliationResult, reconcile_pull_request_labels

_LIFECYCLE_INVOCATION_REASONS = ("draft-pr-created", "head-sha-changed", "validation-terminal", "draft-ready-transition", "review-thread-state-changed", "branch-state-rechecked", "final-state-readback")

@dataclass(frozen=True, slots=True)
class PullRequestCreationExpectation:
    repository: str
    pr_number: int
    base_ref: str
    head_ref: str
    head_sha: str
    draft_requested: bool = True
    merge_authorized: bool = False

@dataclass(frozen=True, slots=True)
class PullRequestCreationVerification:
    status: str
    reason_codes: tuple[str, ...]
    canonical_snapshot: LivePullRequestSnapshot | None
    discoverable: bool
    mutation_allowed: bool
    reportable_state: str
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    protected_setting_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)
    external_system_write_authorized: bool = field(default=False, init=False)

@dataclass(frozen=True, slots=True)
class PullRequestLifecycleReconciliationResult:
    repository: str
    pr_number: int
    invocation_reason: str
    planned_head_sha: str
    verified_head_sha: str | None
    reconciliation_status: str
    reconciliation_required: bool
    recomputed_after_stale_head: bool
    labels_added: tuple[str, ...]
    labels_removed: tuple[str, ...]
    unmanaged_labels_preserved: tuple[str, ...]
    reason_codes: tuple[str, ...]
    reconciliation: PullRequestLabelReconciliationResult
    caller_operation_evidence: str | None
    caller_result_evidence: str | None
    lifecycle_admitted: bool
    side_effects_performed: bool
    creation_verification: PullRequestCreationVerification | None = None
    ready_for_review_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    review_resolution_authorized: bool = field(default=False, init=False)
    protected_setting_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)
    external_system_write_authorized: bool = field(default=False, init=False)

def lifecycle_invocation_reasons() -> tuple[str, ...]: return _LIFECYCLE_INVOCATION_REASONS

def verify_pull_request_creation(provider: PullRequestLabelProvider, expectation: PullRequestCreationExpectation, *, discoverable: bool) -> PullRequestCreationVerification:
    try: snapshot = provider.read(expectation.repository, expectation.pr_number)
    except Exception as exc: return PullRequestCreationVerification("uncertain", (f"canonical-readback-failed:{type(exc).__name__}",), None, False, False, "creation-uncertain")
    reasons=set()
    if snapshot.repository != expectation.repository: reasons.add("repository-mismatch")
    if snapshot.pr_number != expectation.pr_number: reasons.add("pr-number-mismatch")
    if snapshot.head_sha != expectation.head_sha: reasons.add("head-sha-mismatch")
    if snapshot.base_ref is not None and snapshot.base_ref != expectation.base_ref: reasons.add("base-ref-mismatch")
    if snapshot.head_ref is not None and snapshot.head_ref != expectation.head_ref: reasons.add("head-ref-mismatch")
    if snapshot.merged:
        reasons.add("pr-merged")
        if not expectation.merge_authorized: reasons.add("unauthorized-terminal-state")
        return PullRequestCreationVerification("unauthorized-terminal-state" if not expectation.merge_authorized else "terminal", tuple(sorted(reasons)), snapshot, True, False, "merged")
    if snapshot.state != "open": reasons.add("pr-not-open")
    if expectation.draft_requested and not snapshot.draft: reasons.add("draft-ready-state-drift")
    if reasons: return PullRequestCreationVerification("state-drift", tuple(sorted(reasons)), snapshot, True, False, _reportable_state(snapshot))
    codes={"canonical-readback-verified"}
    if not discoverable: codes.add("secondary-discovery-lag-ignored")
    return PullRequestCreationVerification("verified", tuple(sorted(codes)), snapshot, True, True, _reportable_state(snapshot))

def reconcile_pull_request_lifecycle(provider: PullRequestLabelProvider, repository: str, pr_number: int, *, invocation_reason: str, caller_operation_evidence: str | None=None, caller_result_evidence: str | None=None, dry_run: bool=True, lifecycle_admission: LifecycleMutationAdmissionResult | None=None, creation_expectation: PullRequestCreationExpectation | None=None, creation_discoverable: bool | None=None) -> PullRequestLifecycleReconciliationResult:
    if invocation_reason not in _LIFECYCLE_INVOCATION_REASONS: raise ValueError("invocation_reason must be a supported PR lifecycle event")
    op=_normalize_optional_evidence(caller_operation_evidence); res=_normalize_optional_evidence(caller_result_evidence); verification=None
    if invocation_reason=="draft-pr-created" and creation_expectation is not None:
        if creation_discoverable is None: raise ValueError("draft PR creation verification requires canonical discoverability evidence")
        if creation_expectation.repository != repository or creation_expectation.pr_number != pr_number: raise ValueError("draft PR creation expectation must match lifecycle repository and PR number")
        verification=verify_pull_request_creation(provider, creation_expectation, discoverable=creation_discoverable)
        if not verification.mutation_allowed: return _blocked_creation_result(repository, pr_number, invocation_reason, op, res, verification)
    reconciliation=reconcile_pull_request_labels(provider, repository, pr_number, dry_run=dry_run, lifecycle_admission=lifecycle_admission); recomputed=False
    if reconciliation.convergence_status=="stale-head" and not reconciliation.side_effects_performed:
        reconciliation=reconcile_pull_request_labels(provider, repository, pr_number, dry_run=dry_run, lifecycle_admission=lifecycle_admission); recomputed=True
    reasons=set(reconciliation.reason_codes); reasons.add(f"invocation.{invocation_reason}")
    if verification: reasons.update(verification.reason_codes)
    if recomputed: reasons.add("head-recomputed-before-mutation")
    if reconciliation.convergence_status=="converged" and not (reconciliation.labels_to_add or reconciliation.labels_to_remove): reasons.add("managed-labels-unchanged")
    return PullRequestLifecycleReconciliationResult(reconciliation.repository,reconciliation.pr_number,invocation_reason,reconciliation.planned_head_sha,reconciliation.verified_head_sha,_integration_status(reconciliation.convergence_status),bool(reconciliation.labels_to_add or reconciliation.labels_to_remove),recomputed,reconciliation.labels_added,reconciliation.labels_removed,reconciliation.unmanaged_labels_preserved,tuple(sorted(reasons)),reconciliation,op,res,reconciliation.lifecycle_admitted,reconciliation.side_effects_performed,verification)

def _blocked_creation_result(repository, pr_number, invocation_reason, operation_evidence, result_evidence, verification):
    snapshot=verification.canonical_snapshot; head=snapshot.head_sha if snapshot else ""
    empty=PullRequestLabelReconciliationResult(repository,pr_number,head,head or None,(),(),(),(),(),(),"blocked",verification.reason_codes,False,False,False,False)
    return PullRequestLifecycleReconciliationResult(repository,pr_number,invocation_reason,head,head or None,"blocked",False,False,(),(),(),tuple(sorted(set(verification.reason_codes)|{f"invocation.{invocation_reason}"})),empty,operation_evidence,result_evidence,False,False,verification)

def _reportable_state(snapshot):
    if snapshot.merged: return "merged"
    if snapshot.state != "open": return "closed"
    return "draft" if snapshot.draft else "ready-for-review"

def _integration_status(status):
    return {"converged":"converged","dry-run":"skipped","blocked":"blocked","stale-head":"stale","stale-plan":"stale"}.get(status,"failed")

def _normalize_optional_evidence(value):
    if value is None: return None
    normalized=value.strip()
    if not normalized: raise ValueError("caller evidence identifiers must be non-empty when supplied")
    return normalized
