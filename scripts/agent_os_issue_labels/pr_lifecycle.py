from __future__ import annotations

from dataclasses import dataclass, field

from .pr_reconciler import (
    LivePullRequestSnapshot,
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
    label_write_authorized: bool
    side_effects_performed: bool
    creation_verification: PullRequestCreationVerification | None = None
    ready_for_review_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    review_resolution_authorized: bool = field(default=False, init=False)
    protected_setting_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)
    external_system_write_authorized: bool = field(default=False, init=False)


def lifecycle_invocation_reasons() -> tuple[str, ...]:
    return _LIFECYCLE_INVOCATION_REASONS


def verify_pull_request_creation(
    provider: PullRequestLabelProvider,
    expectation: PullRequestCreationExpectation,
    *,
    discoverable: bool,
) -> PullRequestCreationVerification:
    """Reacquire canonical PR state before creation success or follow-up mutation.

    `discoverable` is caller-supplied evidence from the canonical lookup/search
    surface. A missing secondary list/search result must not override a successful
    exact PR readback; callers should set this true once exact canonical lookup
    proves the PR identity.
    """
    try:
        snapshot = provider.read(expectation.repository, expectation.pr_number)
    except Exception as exc:
        return PullRequestCreationVerification(
            status="uncertain",
            reason_codes=(f"canonical-readback-failed:{type(exc).__name__}",),
            canonical_snapshot=None,
            discoverable=False,
            mutation_allowed=False,
            reportable_state="creation-uncertain",
        )

    reasons: set[str] = set()
    if snapshot.repository != expectation.repository:
        reasons.add("repository-mismatch")
    if snapshot.pr_number != expectation.pr_number:
        reasons.add("pr-number-mismatch")
    if snapshot.head_sha != expectation.head_sha:
        reasons.add("head-sha-mismatch")
    if snapshot.base_ref is not None and snapshot.base_ref != expectation.base_ref:
        reasons.add("base-ref-mismatch")
    if snapshot.head_ref is not None and snapshot.head_ref != expectation.head_ref:
        reasons.add("head-ref-mismatch")
    if not discoverable:
        reasons.add("canonical-discoverability-unproven")

    if snapshot.merged:
        reasons.add("pr-merged")
        if not expectation.merge_authorized:
            reasons.add("unauthorized-terminal-state")
        return PullRequestCreationVerification(
            status="unauthorized-terminal-state" if not expectation.merge_authorized else "terminal",
            reason_codes=tuple(sorted(reasons)),
            canonical_snapshot=snapshot,
            discoverable=discoverable,
            mutation_allowed=False,
            reportable_state="merged",
        )

    if snapshot.state != "open":
        reasons.add("pr-not-open")
    if expectation.draft_requested and not snapshot.draft:
        reasons.add("draft-ready-state-drift")

    if reasons:
        return PullRequestCreationVerification(
            status="state-drift",
            reason_codes=tuple(sorted(reasons)),
            canonical_snapshot=snapshot,
            discoverable=discoverable,
            mutation_allowed=False,
            reportable_state=_reportable_state(snapshot),
        )

    return PullRequestCreationVerification(
        status="verified",
        reason_codes=("canonical-readback-verified",),
        canonical_snapshot=snapshot,
        discoverable=True,
        mutation_allowed=True,
        reportable_state=_reportable_state(snapshot),
    )


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
    creation_expectation: PullRequestCreationExpectation | None = None,
    creation_discoverable: bool | None = None,
) -> PullRequestLifecycleReconciliationResult:
    if invocation_reason not in _LIFECYCLE_INVOCATION_REASONS:
        raise ValueError("invocation_reason must be a supported PR lifecycle event")

    normalized_operation_evidence = _normalize_optional_evidence(caller_operation_evidence)
    normalized_result_evidence = _normalize_optional_evidence(caller_result_evidence)

    creation_verification = None
    if invocation_reason == "draft-pr-created" and creation_expectation is not None:
        if creation_discoverable is None:
            raise ValueError("draft PR creation verification requires canonical discoverability evidence")
        creation_verification = verify_pull_request_creation(
            provider,
            creation_expectation,
            discoverable=creation_discoverable,
        )
        if not creation_verification.mutation_allowed:
            return _blocked_creation_result(
                repository,
                pr_number,
                invocation_reason,
                normalized_operation_evidence,
                normalized_result_evidence,
                label_write_authorized,
                creation_verification,
            )

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
    if creation_verification is not None:
        reason_codes.update(creation_verification.reason_codes)
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
        creation_verification=creation_verification,
    )


def _blocked_creation_result(
    repository: str,
    pr_number: int,
    invocation_reason: str,
    operation_evidence: str | None,
    result_evidence: str | None,
    label_write_authorized: bool,
    verification: PullRequestCreationVerification,
) -> PullRequestLifecycleReconciliationResult:
    snapshot = verification.canonical_snapshot
    head_sha = snapshot.head_sha if snapshot is not None else ""
    empty = PullRequestLabelReconciliationResult(
        repository=repository,
        pr_number=pr_number,
        planned_head_sha=head_sha,
        verified_head_sha=head_sha or None,
        desired_managed_labels=(),
        labels_to_add=(),
        labels_to_remove=(),
        labels_added=(),
        labels_removed=(),
        unmanaged_labels_preserved=(),
        convergence_status="blocked",
        reason_codes=verification.reason_codes,
        dry_run=False,
        mutation_attempted=False,
        side_effects_performed=False,
        label_write_authorized=label_write_authorized,
    )
    return PullRequestLifecycleReconciliationResult(
        repository=repository,
        pr_number=pr_number,
        invocation_reason=invocation_reason,
        planned_head_sha=head_sha,
        verified_head_sha=head_sha or None,
        reconciliation_status="blocked",
        reconciliation_required=False,
        recomputed_after_stale_head=False,
        labels_added=(),
        labels_removed=(),
        unmanaged_labels_preserved=(),
        reason_codes=tuple(sorted(set(verification.reason_codes) | {f"invocation.{invocation_reason}"})),
        reconciliation=empty,
        caller_operation_evidence=operation_evidence,
        caller_result_evidence=result_evidence,
        label_write_authorized=label_write_authorized,
        side_effects_performed=False,
        creation_verification=verification,
    )


def _reportable_state(snapshot: LivePullRequestSnapshot) -> str:
    if snapshot.merged:
        return "merged"
    if snapshot.state != "open":
        return "closed"
    return "draft" if snapshot.draft else "ready-for-review"


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
