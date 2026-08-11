from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

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

    def evidence(self) -> PullRequestLabelEvidence:
        return PullRequestLabelEvidence(
            repository=self.repository,
            pr_number=self.pr_number,
            head_sha=self.head_sha,
            draft=self.draft,
            mergeable=self.mergeable,
            conflicted=self.conflicted,
            behind=self.behind,
            validation_state=self.validation_state,
            blocking_review_threads=self.blocking_review_threads,
            current_labels=self.labels,
        )


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
    label_write_authorized: bool
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


def reconcile_pull_request_labels(
    provider: PullRequestLabelProvider,
    repository: str,
    pr_number: int,
    *,
    dry_run: bool = True,
    label_write_authorized: bool = False,
) -> PullRequestLabelReconciliationResult:
    initial = provider.read(repository, pr_number)
    plan = plan_pull_request_labels(initial.evidence())
    available = frozenset(provider.available_labels(repository))
    missing = tuple(sorted(set(plan.desired_managed_labels) - available))
    if missing:
        return _result(plan, status="blocked", reasons=("managed-label-unavailable",), dry_run=dry_run,
                       authorized=label_write_authorized, verified_head=initial.head_sha)

    if dry_run:
        return _result(plan, status="dry-run", reasons=(), dry_run=True, authorized=label_write_authorized,
                       verified_head=initial.head_sha)
    if not label_write_authorized:
        return _result(plan, status="blocked", reasons=("label-write-authorization-required",), dry_run=False,
                       authorized=False, verified_head=initial.head_sha)

    before_write = provider.read(repository, pr_number)
    if before_write.head_sha != plan.head_sha:
        return _result(plan, status="stale-head", reasons=("head-moved-before-mutation",), dry_run=False,
                       authorized=True, verified_head=before_write.head_sha)

    added: list[str] = []
    removed: list[str] = []
    try:
        for label in plan.labels_to_add:
            provider.add_label(repository, pr_number, label)
            added.append(label)
        for label in plan.labels_to_remove:
            if label not in managed_labels():
                return _result(plan, status="blocked", reasons=("unmanaged-removal-rejected",), dry_run=False,
                               authorized=True, verified_head=before_write.head_sha, added=added, removed=removed)
            provider.remove_label(repository, pr_number, label)
            removed.append(label)
    except Exception as exc:
        return _result(plan, status="partial-failure" if added or removed else "write-failure",
                       reasons=(f"provider-write-failure:{type(exc).__name__}",), dry_run=False, authorized=True,
                       verified_head=before_write.head_sha, added=added, removed=removed)

    after = provider.read(repository, pr_number)
    if after.head_sha != plan.head_sha:
        return _result(plan, status="stale-head", reasons=("head-moved-before-readback",), dry_run=False,
                       authorized=True, verified_head=after.head_sha, added=added, removed=removed)

    actual = set(after.labels)
    desired = set(plan.desired_managed_labels)
    actual_managed = actual & managed_labels()
    unmanaged_after = actual - managed_labels()
    if actual_managed != desired or not set(plan.unmanaged_labels_preserved).issubset(unmanaged_after):
        return _result(plan, status="readback-mismatch", reasons=("convergence-not-proven",), dry_run=False,
                       authorized=True, verified_head=after.head_sha, added=added, removed=removed)

    return _result(plan, status="converged", reasons=(), dry_run=False, authorized=True,
                   verified_head=after.head_sha, added=added, removed=removed)


def reconcile_pull_request_batch(
    provider: PullRequestLabelProvider,
    repository: str,
    pr_numbers: tuple[int, ...],
    *,
    dry_run: bool = True,
    label_write_authorized: bool = False,
) -> BatchPullRequestLabelReconciliationResult:
    results: list[PullRequestLabelReconciliationResult] = []
    for pr_number in pr_numbers:
        try:
            result = reconcile_pull_request_labels(
                provider, repository, pr_number, dry_run=dry_run,
                label_write_authorized=label_write_authorized,
            )
        except Exception as exc:
            result = PullRequestLabelReconciliationResult(
                repository=repository, pr_number=pr_number, planned_head_sha="",
                verified_head_sha=None, desired_managed_labels=(), labels_to_add=(), labels_to_remove=(),
                labels_added=(), labels_removed=(), unmanaged_labels_preserved=(), convergence_status="blocked",
                reason_codes=(f"provider-read-failure:{type(exc).__name__}",), dry_run=dry_run,
                mutation_attempted=False, side_effects_performed=False,
                label_write_authorized=label_write_authorized,
            )
        results.append(result)
    return BatchPullRequestLabelReconciliationResult(results=tuple(results))


def _result(plan, *, status: str, reasons: tuple[str, ...], dry_run: bool, authorized: bool,
            verified_head: str | None, added=(), removed=()) -> PullRequestLabelReconciliationResult:
    added_tuple = tuple(added)
    removed_tuple = tuple(removed)
    return PullRequestLabelReconciliationResult(
        repository=plan.repository,
        pr_number=plan.pr_number,
        planned_head_sha=plan.head_sha,
        verified_head_sha=verified_head,
        desired_managed_labels=plan.desired_managed_labels,
        labels_to_add=plan.labels_to_add,
        labels_to_remove=plan.labels_to_remove,
        labels_added=added_tuple,
        labels_removed=removed_tuple,
        unmanaged_labels_preserved=plan.unmanaged_labels_preserved,
        convergence_status=status,
        reason_codes=reasons,
        dry_run=dry_run,
        mutation_attempted=bool(added_tuple or removed_tuple),
        side_effects_performed=bool(added_tuple or removed_tuple),
        label_write_authorized=authorized,
    )
