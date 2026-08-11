from __future__ import annotations

from dataclasses import dataclass, field

from .pr_reconciler import (
    PullRequestLabelProvider,
    PullRequestLabelReconciliationResult,
    reconcile_pull_request_labels,
)


_LIFECYCLE_INVOCATION_REASONS = (
    "draft-pr-created",
    "head-sha-changed",
    "validation-terminal",
    "draft-ready-transition",
    "review-thread-state-changed",
    "branch-state-rechecked",
    "final-state-readback",
)


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
    label_write_authorized: bool
    side_effects_performed: bool
    ready_for_review_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    review_resolution_authorized: bool = field(default=False, init=False)
    protected_setting_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)
    external_system_write_authorized: bool = field(default=False, init=False)


def lifecycle_invocation_reasons() -> tuple[str, ...]:
    return _LIFECYCLE_INVOCATION_REASONS


def reconcile_pull_request_lifecycle(
    provider: PullRequestLabelProvider,
    repository: str,
    pr_number: int,
    *,
    invocation_reason: str,
    caller_operation_evidence: str | None = None,
    caller_result_evidence: str | None = None,
    dry_run: bool = True,
    label_write_authorized: bool = False,
) -> PullRequestLifecycleReconciliationResult:
    if invocation_reason not in _LIFECYCLE_INVOCATION_REASONS:
        raise ValueError("invocation_reason must be a supported PR lifecycle event")

    normalized_operation_evidence = _normalize_optional_evidence(caller_operation_evidence)
    normalized_result_evidence = _normalize_optional_evidence(caller_result_evidence)

    reconciliation = reconcile_pull_request_labels(
        provider,
        repository,
        pr_number,
        dry_run=dry_run,
        label_write_authorized=label_write_authorized,
    )
    recomputed = False
    if reconciliation.convergence_status == "stale-head" and not reconciliation.side_effects_performed:
        reconciliation = reconcile_pull_request_labels(
            provider,
            repository,
            pr_number,
            dry_run=dry_run,
            label_write_authorized=label_write_authorized,
        )
        recomputed = True

    reason_codes = set(reconciliation.reason_codes)
    reason_codes.add(f"invocation.{invocation_reason}")
    if recomputed:
        reason_codes.add("head-recomputed-before-mutation")
    if reconciliation.convergence_status == "converged" and not (
        reconciliation.labels_to_add or reconciliation.labels_to_remove
    ):
        reason_codes.add("managed-labels-unchanged")

    return PullRequestLifecycleReconciliationResult(
        repository=reconciliation.repository,
        pr_number=reconciliation.pr_number,
        invocation_reason=invocation_reason,
        planned_head_sha=reconciliation.planned_head_sha,
        verified_head_sha=reconciliation.verified_head_sha,
        reconciliation_status=_integration_status(reconciliation.convergence_status),
        reconciliation_required=bool(reconciliation.labels_to_add or reconciliation.labels_to_remove),
        recomputed_after_stale_head=recomputed,
        labels_added=reconciliation.labels_added,
        labels_removed=reconciliation.labels_removed,
        unmanaged_labels_preserved=reconciliation.unmanaged_labels_preserved,
        reason_codes=tuple(sorted(reason_codes)),
        reconciliation=reconciliation,
        caller_operation_evidence=normalized_operation_evidence,
        caller_result_evidence=normalized_result_evidence,
        label_write_authorized=reconciliation.label_write_authorized,
        side_effects_performed=reconciliation.side_effects_performed,
    )


def _integration_status(convergence_status: str) -> str:
    if convergence_status == "converged":
        return "converged"
    if convergence_status == "dry-run":
        return "skipped"
    if convergence_status == "blocked":
        return "blocked"
    if convergence_status == "stale-head":
        return "stale"
    return "failed"


def _normalize_optional_evidence(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("caller evidence identifiers must be non-empty when supplied")
    return normalized
