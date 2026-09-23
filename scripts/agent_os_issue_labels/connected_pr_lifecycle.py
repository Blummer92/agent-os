from __future__ import annotations

from dataclasses import dataclass

from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import LifecycleMutationAdmissionResult

from .pr_lifecycle import PullRequestCreationExpectation, PullRequestLifecycleReconciliationResult, reconcile_pull_request_lifecycle
from .pr_reconciler import PullRequestLabelProvider


@dataclass(frozen=True, slots=True)
class ConnectedPullRequestLifecycleResult:
    reconciliation: PullRequestLifecycleReconciliationResult
    terminal_success: bool
    reason_codes: tuple[str, ...]


def converge_connected_pull_request_lifecycle(
    provider: PullRequestLabelProvider,
    repository: str,
    pr_number: int,
    *,
    invocation_reason: str,
    lifecycle_admission: LifecycleMutationAdmissionResult | None,
    caller_operation_evidence: str | None = None,
    caller_result_evidence: str | None = None,
    creation_expectation: PullRequestCreationExpectation | None = None,
    creation_discoverable: bool | None = None,
) -> ConnectedPullRequestLifecycleResult:
    result = reconcile_pull_request_lifecycle(
        provider,
        repository,
        pr_number,
        invocation_reason=invocation_reason,
        caller_operation_evidence=caller_operation_evidence,
        caller_result_evidence=caller_result_evidence,
        dry_run=False,
        lifecycle_admission=lifecycle_admission,
        creation_expectation=creation_expectation,
        creation_discoverable=creation_discoverable,
    )
    terminal = result.reconciliation_status == "converged"
    reasons = set(result.reason_codes)
    reasons.add("connected-pr-label-convergence-proven" if terminal else "connected-pr-label-convergence-not-proven")
    return ConnectedPullRequestLifecycleResult(result, terminal, tuple(sorted(reasons)))
