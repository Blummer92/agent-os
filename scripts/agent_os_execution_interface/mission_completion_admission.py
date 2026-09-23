from __future__ import annotations

from dataclasses import dataclass, field


LIVE_CONSUMER_OBSERVATION = "live-consumer-observation"


@dataclass(frozen=True, slots=True)
class MissionCompletionAdmission:
    repository: str
    issue_number: int
    branch_exists: bool
    implementation_commit_count: int
    draft_pr_exists: bool
    canonical_pr_readback_verified: bool
    capable_route_available: bool
    subordinate_writes_only: bool
    live_consumer_required: bool
    live_consumer_requirement_source: str | None
    live_consumer_reachability_proven: bool
    live_consumer_identity: str | None
    live_consumer_evidence_source: str | None
    live_consumer_evidence_current: bool
    live_consumer_evidence_kind: str | None
    successor_issue_number: int | None
    successor_current: bool
    successor_owns_residual_live_acceptance: bool
    completion_admissible: bool
    reason_codes: tuple[str, ...]
    next_action: str
    github_writes_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    workflow_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)
    external_system_write_authorized: bool = field(default=False, init=False)


def evaluate_mission_completion_admission(
    *,
    repository: str,
    issue_number: int,
    branch_exists: bool,
    implementation_commit_count: int,
    draft_pr_exists: bool,
    canonical_pr_readback_verified: bool,
    capable_route_available: bool,
    subordinate_writes_only: bool,
    live_consumer_required: bool = False,
    live_consumer_requirement_source: str | None = None,
    live_consumer_reachability_proven: bool = False,
    live_consumer_identity: str | None = None,
    live_consumer_evidence_source: str | None = None,
    live_consumer_evidence_current: bool = False,
    live_consumer_evidence_kind: str | None = None,
    successor_issue_number: int | None = None,
    successor_current: bool = False,
    successor_owns_residual_live_acceptance: bool = False,
) -> MissionCompletionAdmission:
    """Project whether bounded repository delivery may be represented as complete.

    The caller supplies already-reacquired canonical evidence. Repository delivery
    remains sufficient for repository-only issues. When the issue contract itself
    requires a live host/runtime/connector consumer, a completion claim additionally
    needs current source-specific live observation tied to the exact consumer
    identity, unless the issue is only the repository child and current evidence
    proves a successor issue owns the residual live-acceptance obligation.

    Packaging, registration, fixtures, contracts, and unit tests are repository
    evidence only; they are never treated as live-consumer observation here.

    This projection performs no reads or writes and grants no merge, closure,
    workflow, production, external-system, or GitHub-write authority.
    """
    _validate_identity(repository, issue_number)
    for name, value in (
        ("branch_exists", branch_exists),
        ("draft_pr_exists", draft_pr_exists),
        ("canonical_pr_readback_verified", canonical_pr_readback_verified),
        ("capable_route_available", capable_route_available),
        ("subordinate_writes_only", subordinate_writes_only),
        ("live_consumer_required", live_consumer_required),
        ("live_consumer_reachability_proven", live_consumer_reachability_proven),
        ("live_consumer_evidence_current", live_consumer_evidence_current),
        ("successor_current", successor_current),
        (
            "successor_owns_residual_live_acceptance",
            successor_owns_residual_live_acceptance,
        ),
    ):
        if type(value) is not bool:
            raise TypeError(f"{name} must be built-in bool")
    if type(implementation_commit_count) is not int or implementation_commit_count < 0:
        raise ValueError(
            "implementation_commit_count must be a non-negative built-in integer"
        )
    for name, value in (
        ("live_consumer_requirement_source", live_consumer_requirement_source),
        ("live_consumer_identity", live_consumer_identity),
        ("live_consumer_evidence_source", live_consumer_evidence_source),
        ("live_consumer_evidence_kind", live_consumer_evidence_kind),
    ):
        if value is not None and (type(value) is not str or not value.strip()):
            raise ValueError(f"{name} must be None or non-empty exact text")
    if successor_issue_number is not None and (
        type(successor_issue_number) is not int or successor_issue_number < 1
    ):
        raise ValueError(
            "successor_issue_number must be None or a positive built-in integer"
        )

    reasons: list[str] = []
    success_reasons: list[str] = []
    if not branch_exists:
        reasons.append("implementation-branch-not-proven")
    if implementation_commit_count == 0:
        reasons.append("implementation-not-started")
    if not draft_pr_exists:
        reasons.append("draft-pr-not-proven")
    if draft_pr_exists and not canonical_pr_readback_verified:
        reasons.append("canonical-pr-readback-not-proven")
    if subordinate_writes_only:
        reasons.append("subordinate-write-is-not-parent-completion")

    if live_consumer_required:
        if live_consumer_requirement_source is None:
            reasons.append("required-live-consumer-contract-source-not-proven")

        successor_claimed = any(
            (
                successor_issue_number is not None,
                successor_current,
                successor_owns_residual_live_acceptance,
            )
        )
        successor_delegation_proven = (
            successor_issue_number is not None
            and successor_current
            and successor_owns_residual_live_acceptance
        )

        if successor_claimed and not successor_delegation_proven:
            if successor_issue_number is None:
                reasons.append("residual-live-successor-identity-not-proven")
            if not successor_current:
                reasons.append("residual-live-successor-currentness-not-proven")
            if not successor_owns_residual_live_acceptance:
                reasons.append("residual-live-successor-ownership-not-proven")
        elif successor_delegation_proven:
            success_reasons.append(
                "residual-live-acceptance-owned-by-current-successor"
            )
        else:
            if not live_consumer_reachability_proven:
                reasons.append("required-live-consumer-reachability-not-proven")
            else:
                if live_consumer_identity is None:
                    reasons.append("required-live-consumer-identity-not-proven")
                if live_consumer_evidence_source is None:
                    reasons.append(
                        "required-live-consumer-evidence-source-not-proven"
                    )
                if not live_consumer_evidence_current:
                    reasons.append("required-live-consumer-evidence-not-current")
                if live_consumer_evidence_kind != LIVE_CONSUMER_OBSERVATION:
                    reasons.append(
                        "required-live-consumer-evidence-not-live-observation"
                    )
                if not any(
                    reason.startswith("required-live-consumer-")
                    for reason in reasons
                ):
                    success_reasons.append(
                        "required-live-consumer-current-observation-proven"
                    )

    if not reasons:
        completion_admissible = True
        next_action = "report-canonically-verified-draft-pr-delivery"
        reasons.extend(success_reasons)
        reasons.append("canonical-implementation-delivery-proven")
    else:
        completion_admissible = False
        if any(
            reason.startswith("required-live-consumer-")
            or reason.startswith("residual-live-successor-")
            for reason in reasons
        ):
            next_action = "reconcile-live-consumer-or-successor-evidence"
        elif capable_route_available:
            next_action = "continue-same-lineage-on-capable-implementation-route"
        else:
            next_action = (
                "report-exact-patch-capability-blocker-without-completion-claim"
            )

    return MissionCompletionAdmission(
        repository=repository,
        issue_number=issue_number,
        branch_exists=branch_exists,
        implementation_commit_count=implementation_commit_count,
        draft_pr_exists=draft_pr_exists,
        canonical_pr_readback_verified=canonical_pr_readback_verified,
        capable_route_available=capable_route_available,
        subordinate_writes_only=subordinate_writes_only,
        live_consumer_required=live_consumer_required,
        live_consumer_requirement_source=live_consumer_requirement_source,
        live_consumer_reachability_proven=live_consumer_reachability_proven,
        live_consumer_identity=live_consumer_identity,
        live_consumer_evidence_source=live_consumer_evidence_source,
        live_consumer_evidence_current=live_consumer_evidence_current,
        live_consumer_evidence_kind=live_consumer_evidence_kind,
        successor_issue_number=successor_issue_number,
        successor_current=successor_current,
        successor_owns_residual_live_acceptance=(
            successor_owns_residual_live_acceptance
        ),
        completion_admissible=completion_admissible,
        reason_codes=tuple(reasons),
        next_action=next_action,
    )


def _validate_identity(repository: str, issue_number: int) -> None:
    if type(repository) is not str or "/" not in repository or not repository.strip():
        raise ValueError("repository must be non-empty owner/name text")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("issue_number must be a positive built-in integer")
