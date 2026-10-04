"""ChatGPT-facing composition seam for the governed GitHub mutation contracts (#3281).

This module is pure-local and non-authorizing. It consumes bounded host
evidence as JSON primitives, builds the frozen dataclass evidence structs
owned by the three issue-acceptance contracts, and returns JSON-safe dicts:

- seam 1 (issue-comment write boundary): ``evaluate_defect_evidence_mutation``
  (#2741, pre-write verify-open guard) and ``evaluate_comment_persistence``
  (#2785, post-write canonical readback);
- seam 2 (Safe Implementation Lane post-PR step):
  ``project_lane_post_pr_issue_reconciliation`` /
  ``evaluate_lane_post_pr_issue_readback`` (#2791).

The module performs no GitHub reads or writes and introduces no second issue
registry, queue, scheduler, or lifecycle authority. Every result carries
``side_effects_performed: False`` and ``github_writes_authorized: False``.
"""
from __future__ import annotations

from dataclasses import asdict

from scripts.agent_os_execution_interface.continuation_driver import (
    completion_continuation_payload,
)
from scripts.agent_os_issue_acceptance.comment_mutation_readback import (
    CommentPersistenceStatus,
    CommentReadback,
    evaluate_comment_persistence,
)
from scripts.agent_os_issue_acceptance.defect_evidence_mutation_guard import (
    DefectEvidenceMutationDecision,
    DefectEvidenceMutationTarget,
    DefectEvidenceRefusalDirective,
    evaluate_defect_evidence_mutation,
)
from scripts.agent_os_issue_acceptance.lane_post_pr_issue_reconciliation import (
    LanePostPrIssueDisposition,
    LanePostPrIssueEvidence,
    LanePostPrIssueReconciliation,
    evaluate_lane_post_pr_issue_readback,
    project_lane_post_pr_issue_reconciliation,
)

_SEAM1_PHASES = frozenset({"pre-write-guard", "post-write-readback"})
_SEAM2_PHASES = frozenset({"plan", "readback-proof"})

_GUARD_NEXT_ACTION = {
    DefectEvidenceMutationDecision.ADMITTED: "proceed-with-write-then-canonical-readback",
    DefectEvidenceRefusalDirective.REACQUIRE_TARGET_STATE: "reacquire-target-state-before-write",
    DefectEvidenceRefusalDirective.ROUTE_TO_OPEN_OWNER: "route-evidence-to-open-owner",
    DefectEvidenceRefusalDirective.CREATE_NEW_BUG: "create-new-bug-for-evidence",
}

_PLAN_NEXT_ACTION = {
    LanePostPrIssueDisposition.RECONCILE_READY_AND_CLOSE: "perform-expected-mutations-then-canonical-readback",
    LanePostPrIssueDisposition.RECONCILE_READY_AWAITING_CLOSURE_AUTHORITY: "perform-expected-mutations-then-canonical-readback",
    LanePostPrIssueDisposition.ALREADY_RECONCILED: "",
    LanePostPrIssueDisposition.NEEDS_DECISION: "manual-decision-required",
}


def evaluate_issue_comment_mutation_boundary_for_host(
    *,
    phase: str,
    issue_number: int,
    evidence_kind: str = "defect",
    target_open: bool = False,
    state_current: bool = False,
    open_owner_issue_number: int | None = None,
    historical_lineage_issue_number: int | None = None,
    intended_body: str | None = None,
    provider_reported_success: bool | None = None,
    readback_complete: bool = False,
    comments: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    """Run one phase of the issue-comment write boundary and return a JSON-safe dict."""
    if phase not in _SEAM1_PHASES:
        raise ValueError(f"phase must be one of {sorted(_SEAM1_PHASES)}")
    if phase == "pre-write-guard":
        return _evaluate_defect_evidence_guard_for_host(
            issue_number=issue_number,
            evidence_kind=evidence_kind,
            target_open=target_open,
            state_current=state_current,
            open_owner_issue_number=open_owner_issue_number,
            historical_lineage_issue_number=historical_lineage_issue_number,
        )
    return _evaluate_comment_persistence_for_host(
        issue_number=issue_number,
        intended_body=intended_body,
        provider_reported_success=provider_reported_success,
        readback_complete=readback_complete,
        comments=comments,
    )


def _evaluate_defect_evidence_guard_for_host(
    *,
    issue_number: int,
    evidence_kind: str,
    target_open: bool,
    state_current: bool,
    open_owner_issue_number: int | None,
    historical_lineage_issue_number: int | None,
) -> dict[str, object]:
    target = DefectEvidenceMutationTarget(
        issue_number=issue_number,
        evidence_kind=evidence_kind,
        target_open=target_open,
        state_current=state_current,
        open_owner_issue_number=open_owner_issue_number,
        historical_lineage_issue_number=historical_lineage_issue_number,
    )
    result = evaluate_defect_evidence_mutation(target)
    if result.decision is DefectEvidenceMutationDecision.ADMITTED:
        next_action = _GUARD_NEXT_ACTION[DefectEvidenceMutationDecision.ADMITTED]
    else:
        next_action = _GUARD_NEXT_ACTION[result.directive]
    payload = asdict(result)
    payload["decision"] = result.decision.value
    payload["directive"] = result.directive.value if result.directive is not None else None
    payload["reason_codes"] = list(result.reason_codes)
    payload["agent_os_continuation"] = completion_continuation_payload(
        terminal=False,
        blocked=False,
        next_action=next_action,
        reason_codes=result.reason_codes,
    )
    payload["github_writes_authorized"] = False
    return payload


def _evaluate_comment_persistence_for_host(
    *,
    issue_number: int,
    intended_body: str | None,
    provider_reported_success: bool | None,
    readback_complete: bool,
    comments: tuple[dict[str, object], ...],
) -> dict[str, object]:
    if intended_body is None:
        raise ValueError("intended_body is required for the post-write-readback phase")
    readbacks = tuple(
        CommentReadback(
            comment_id=item["comment_id"],
            issue_number=item["issue_number"],
            body=item["body"],
        )
        for item in comments
    )
    result = evaluate_comment_persistence(
        issue_number=issue_number,
        intended_body=intended_body,
        provider_reported_success=provider_reported_success,
        readback_complete=readback_complete,
        comments=readbacks,
    )
    if result.status is CommentPersistenceStatus.PERSISTED:
        terminal, blocked, next_action = True, False, ""
    elif result.status is CommentPersistenceStatus.NOT_PERSISTED and result.retry_safe:
        terminal, blocked, next_action = False, False, "retry-write-once"
    elif result.status is CommentPersistenceStatus.NOT_PERSISTED:
        terminal, blocked, next_action = False, True, "reconcile-manually-no-automatic-retry"
    else:
        terminal, blocked, next_action = False, False, "reconcile-manually-no-automatic-retry"
    payload = asdict(result)
    payload["status"] = result.status.value
    payload["reason_codes"] = list(result.reason_codes)
    payload["agent_os_continuation"] = completion_continuation_payload(
        terminal=terminal,
        blocked=blocked,
        next_action=next_action,
        reason_codes=result.reason_codes,
    )
    payload["github_writes_authorized"] = False
    return payload


def project_lane_post_pr_issue_reconciliation_for_host(
    *,
    phase: str,
    issue_number: int,
    issue_open: bool = False,
    lifecycle_labels: tuple[str, ...] = (),
    linked_pull_request_number: int = 0,
    pr_state: str = "draft",
    pr_head_sha: str = "",
    pr_readback_current: bool = False,
    closure_authorized: bool = False,
    evidence_current: bool = False,
    plan: dict[str, object] | None = None,
) -> dict[str, object]:
    """Run one phase of the lane post-PR reconciliation and return a JSON-safe dict."""
    if phase not in _SEAM2_PHASES:
        raise ValueError(f"phase must be one of {sorted(_SEAM2_PHASES)}")
    if phase == "plan":
        return _project_lane_post_pr_plan_for_host(
            issue_number=issue_number,
            issue_open=issue_open,
            lifecycle_labels=lifecycle_labels,
            linked_pull_request_number=linked_pull_request_number,
            pr_state=pr_state,
            pr_head_sha=pr_head_sha,
            pr_readback_current=pr_readback_current,
            closure_authorized=closure_authorized,
            evidence_current=evidence_current,
        )
    return _evaluate_lane_post_pr_readback_for_host(
        issue_number=issue_number,
        issue_open=issue_open,
        lifecycle_labels=lifecycle_labels,
        evidence_current=evidence_current,
        plan=plan,
    )


def _project_lane_post_pr_plan_for_host(
    *,
    issue_number: int,
    issue_open: bool,
    lifecycle_labels: tuple[str, ...],
    linked_pull_request_number: int,
    pr_state: str,
    pr_head_sha: str,
    pr_readback_current: bool,
    closure_authorized: bool,
    evidence_current: bool,
) -> dict[str, object]:
    evidence = LanePostPrIssueEvidence(
        issue_number=issue_number,
        issue_open=issue_open,
        lifecycle_labels=lifecycle_labels,
        linked_pull_request_number=linked_pull_request_number,
        pr_state=pr_state,
        pr_head_sha=pr_head_sha,
        pr_readback_current=pr_readback_current,
        closure_authorized=closure_authorized,
        evidence_current=evidence_current,
    )
    result = project_lane_post_pr_issue_reconciliation(evidence)
    disposition = result.disposition
    payload = asdict(result)
    payload["disposition"] = disposition.value
    payload["expected_mutations"] = list(result.expected_mutations)
    payload["reason_codes"] = list(result.reason_codes)
    payload["agent_os_continuation"] = completion_continuation_payload(
        terminal=disposition is LanePostPrIssueDisposition.ALREADY_RECONCILED,
        blocked=disposition is LanePostPrIssueDisposition.NEEDS_DECISION,
        next_action=_PLAN_NEXT_ACTION[disposition],
        reason_codes=result.reason_codes,
    )
    payload["github_writes_authorized"] = False
    return payload


def _reconstruct_reconciliation_plan(plan: dict[str, object]) -> LanePostPrIssueReconciliation:
    """Rebuild a frozen plan from its JSON round-trip; the contract revalidates."""
    if type(plan) is not dict:
        raise ValueError("plan must be the JSON dict returned by the plan phase")
    return LanePostPrIssueReconciliation(
        disposition=LanePostPrIssueDisposition(plan["disposition"]),
        issue_number=plan["issue_number"],
        linked_pull_request_number=plan["linked_pull_request_number"],
        expected_mutations=tuple(plan["expected_mutations"]),
        ready_label=plan.get("ready_label"),
        reason_codes=tuple(plan["reason_codes"]),
        readback_required=plan["readback_required"],
        fully_reconciled=plan["fully_reconciled"],
    )


def _evaluate_lane_post_pr_readback_for_host(
    *,
    issue_number: int,
    issue_open: bool,
    lifecycle_labels: tuple[str, ...],
    evidence_current: bool,
    plan: dict[str, object] | None,
) -> dict[str, object]:
    if plan is None:
        raise ValueError("plan is required for the readback-proof phase")
    reconciliation = _reconstruct_reconciliation_plan(plan)
    proof = evaluate_lane_post_pr_issue_readback(
        reconciliation,
        issue_number=issue_number,
        issue_open=issue_open,
        lifecycle_labels=lifecycle_labels,
        evidence_current=evidence_current,
    )
    payload = asdict(proof)
    payload["disposition"] = proof.disposition.value
    payload["reason_codes"] = list(proof.reason_codes)
    payload["agent_os_continuation"] = completion_continuation_payload(
        terminal=proof.fully_reconciled,
        blocked=False,
        next_action=(
            "" if proof.fully_reconciled else "complete-expected-mutations-then-rereadback"
        ),
        reason_codes=proof.reason_codes,
    )
    payload["github_writes_authorized"] = False
    return payload
