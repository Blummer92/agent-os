from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import LifecycleMutationAdmissionResult

from .pr_planner import PullRequestLabelEvidence, managed_labels, plan_pull_request_labels


class PullRequestLabelProvider(Protocol):
    def read(self, repository: str, pr_number: int) -> "LivePullRequestSnapshot": ...
    def available_labels(self, repository: str) -> tuple[str, ...]: ...
    def add_label(self, repository: str, pr_number: int, label: str) -> None: ...
    def remove_label(self, repository: str, pr_number: int, label: str) -> None: ...


@dataclass(frozen=True, slots=True)
class LivePullRequestSnapshot:
    repository: str
    pr_number: int
    head_sha: str
    draft: bool
    mergeable: bool
    conflicted: bool
    behind: bool
    validation_state: str
    blocking_review_threads: int
    labels: tuple[str, ...] = ()
    state: str = "open"
    merged: bool = False
    base_ref: str | None = None
    head_ref: str | None = None

    def evidence(self) -> PullRequestLabelEvidence:
        return PullRequestLabelEvidence(repository=self.repository, pr_number=self.pr_number, head_sha=self.head_sha, draft=self.draft, mergeable=self.mergeable, conflicted=self.conflicted, behind=self.behind, validation_state=self.validation_state, blocking_review_threads=self.blocking_review_threads, current_labels=self.labels)


@dataclass(frozen=True, slots=True)
class PullRequestLabelReconciliationResult:
    repository: str
    pr_number: int
    planned_head_sha: str
    verified_head_sha: str | None
    desired_managed_labels: tuple[str, ...]
    labels_to_add: tuple[str, ...]
    labels_to_remove: tuple[str, ...]
    labels_added: tuple[str, ...]
    labels_removed: tuple[str, ...]
    unmanaged_labels_preserved: tuple[str, ...]
    convergence_status: str
    reason_codes: tuple[str, ...]
    dry_run: bool
    mutation_attempted: bool
    side_effects_performed: bool
    lifecycle_admitted: bool
    ready_for_review_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)
    external_system_write_authorized: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class BatchPullRequestLabelReconciliationResult:
    results: tuple[PullRequestLabelReconciliationResult, ...]

    @property
    def untouched_prs(self) -> tuple[int, ...]:
        return tuple(result.pr_number for result in self.results if result.convergence_status == "not-attempted")


def _plan_source_matches(planned: PullRequestLabelEvidence, current: PullRequestLabelEvidence) -> bool:
    return planned == current


def _admission_blocker(admission: LifecycleMutationAdmissionResult | None) -> str | None:
    if admission is None:
        return "lifecycle-admission-required"
    if type(admission) is not LifecycleMutationAdmissionResult:
        return "lifecycle-admission-invalid"
    if admission.requested_mutation != "replace-lifecycle-labels" or not admission.admitted:
        return "lifecycle-admission-refused"
    return None


def reconcile_pull_request_labels(provider: PullRequestLabelProvider, repository: str, pr_number: int, *, dry_run: bool = True, lifecycle_admission: LifecycleMutationAdmissionResult | None = None) -> PullRequestLabelReconciliationResult:
    initial = provider.read(repository, pr_number)
    planned_evidence = initial.evidence()
    plan = plan_pull_request_labels(planned_evidence)
    missing = tuple(sorted(set(plan.desired_managed_labels) - frozenset(provider.available_labels(repository))))
    admitted = lifecycle_admission is not None and type(lifecycle_admission) is LifecycleMutationAdmissionResult and lifecycle_admission.admitted
    if missing:
        return _result(plan, status="blocked", reasons=("managed-label-unavailable",), dry_run=dry_run, admitted=admitted, verified_head=initial.head_sha)
    if dry_run:
        return _result(plan, status="dry-run", reasons=(), dry_run=True, admitted=admitted, verified_head=initial.head_sha)
    blocker = _admission_blocker(lifecycle_admission)
    if blocker is not None:
        return _result(plan, status="blocked", reasons=(blocker,), dry_run=False, admitted=False, verified_head=initial.head_sha)

    before_write = provider.read(repository, pr_number)
    if before_write.head_sha != plan.head_sha:
        return _result(plan, status="stale-head", reasons=("head-moved-before-mutation",), dry_run=False, admitted=True, verified_head=before_write.head_sha)
    if not _plan_source_matches(planned_evidence, before_write.evidence()):
        return _result(plan, status="stale-plan", reasons=("planner-evidence-changed-before-mutation",), dry_run=False, admitted=True, verified_head=before_write.head_sha)

    added: list[str] = []
    removed: list[str] = []
    try:
        for label in plan.labels_to_add:
            provider.add_label(repository, pr_number, label); added.append(label)
        for label in plan.labels_to_remove:
            if label not in managed_labels():
                return _result(plan, status="blocked", reasons=("unmanaged-removal-rejected",), dry_run=False, admitted=True, verified_head=before_write.head_sha, added=added, removed=removed)
            provider.remove_label(repository, pr_number, label); removed.append(label)
    except Exception as exc:
        return _result(plan, status="partial-failure" if added or removed else "write-failure", reasons=(f"provider-write-failure:{type(exc).__name__}",), dry_run=False, admitted=True, verified_head=before_write.head_sha, added=added, removed=removed)

    after = provider.read(repository, pr_number)
    if after.head_sha != plan.head_sha:
        return _result(plan, status="stale-head", reasons=("head-moved-before-readback",), dry_run=False, admitted=True, verified_head=after.head_sha, added=added, removed=removed)
    actual = set(after.labels); desired = set(plan.desired_managed_labels)
    if actual & managed_labels() != desired or not set(plan.unmanaged_labels_preserved).issubset(actual - managed_labels()):
        return _result(plan, status="readback-mismatch", reasons=("convergence-not-proven",), dry_run=False, admitted=True, verified_head=after.head_sha, added=added, removed=removed)
    return _result(plan, status="converged", reasons=(), dry_run=False, admitted=True, verified_head=after.head_sha, added=added, removed=removed)


def reconcile_pull_request_batch(provider: PullRequestLabelProvider, repository: str, pr_numbers: tuple[int, ...], *, dry_run: bool = True, lifecycle_admission: LifecycleMutationAdmissionResult | None = None) -> BatchPullRequestLabelReconciliationResult:
    results = []
    for pr_number in pr_numbers:
        try:
            results.append(reconcile_pull_request_labels(provider, repository, pr_number, dry_run=dry_run, lifecycle_admission=lifecycle_admission))
        except Exception as exc:
            results.append(PullRequestLabelReconciliationResult(repository, pr_number, "", None, (), (), (), (), (), (), "blocked", (f"provider-read-failure:{type(exc).__name__}",), dry_run, False, False, False))
    return BatchPullRequestLabelReconciliationResult(results=tuple(results))


def _result(plan, *, status: str, reasons: tuple[str, ...], dry_run: bool, admitted: bool, verified_head: str | None, added=(), removed=()) -> PullRequestLabelReconciliationResult:
    added_tuple = tuple(added); removed_tuple = tuple(removed)
    return PullRequestLabelReconciliationResult(repository=plan.repository, pr_number=plan.pr_number, planned_head_sha=plan.head_sha, verified_head_sha=verified_head, desired_managed_labels=plan.desired_managed_labels, labels_to_add=plan.labels_to_add, labels_to_remove=plan.labels_to_remove, labels_added=added_tuple, labels_removed=removed_tuple, unmanaged_labels_preserved=plan.unmanaged_labels_preserved, convergence_status=status, reason_codes=reasons, dry_run=dry_run, mutation_attempted=bool(added_tuple or removed_tuple), side_effects_performed=bool(added_tuple or removed_tuple), lifecycle_admitted=admitted)
