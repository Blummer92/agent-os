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
    #: Digest binding the ``canonical_pr_readback_verified`` claim to the
    #: canonical readback observation the caller already reacquired. Carried
    #: for provenance; a True claim without a binding fails closed.
    canonical_pr_readback_binding: str | None
    #: Digest binding the ``live_consumer_reachability_proven`` claim to the
    #: live observation the caller already reacquired. Carried for provenance;
    #: a True claim without a binding fails closed.
    live_consumer_observation_binding: str | None
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
    implementation_pr_required: bool = False,
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
    canonical_pr_readback_binding: str | None = None,
    live_consumer_observation_binding: str | None = None,
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

    Narration is not evidence: a bare asserted boolean claims nothing. When
    ``canonical_pr_readback_verified`` is True the caller must also supply
    ``canonical_pr_readback_binding`` -- a digest string binding the claim to the
    canonical readback observation already reacquired -- and when
    ``live_consumer_reachability_proven`` is True the caller must also supply
    ``live_consumer_observation_binding``. A True claim without its binding fails
    closed as unproven. Bindings are verified for non-emptiness and shape only;
    this pure seam performs no reads and cannot re-verify the readback itself.

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
        ("implementation_pr_required", implementation_pr_required),
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
        ("canonical_pr_readback_binding", canonical_pr_readback_binding),
        ("live_consumer_observation_binding", live_consumer_observation_binding),
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
    if canonical_pr_readback_verified and canonical_pr_readback_binding is None:
        # Narration is not evidence: a bare asserted True with no digest binding
        # the claim to a reacquired canonical readback observation fails closed.
        reasons.append("canonical-pr-readback-not-proven")
    if subordinate_writes_only:
        reasons.append("subordinate-write-is-not-parent-completion")
    if implementation_pr_required and not draft_pr_exists:
        reasons.append("required-implementation-pr-not-proven")

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
                if live_consumer_observation_binding is None:
                    # Narration is not evidence: a bare asserted True with no
                    # digest binding the claim to a reacquired live observation
                    # fails closed, even when the supplied fields look complete.
                    reasons.append(
                        "required-live-consumer-reachability-not-proven"
                    )
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
        canonical_pr_readback_binding=canonical_pr_readback_binding,
        live_consumer_observation_binding=live_consumer_observation_binding,
    )


@dataclass(frozen=True, slots=True)
class ParallelMissionCompletionAdmission:
    lane_count: int
    terminal_lane_count: int
    completion_admissible: bool
    reason_codes: tuple[str, ...]
    next_actions: tuple[str, ...]
    github_writes_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)


def evaluate_parallel_mission_completion_admission(
    lanes: tuple[MissionCompletionAdmission, ...],
) -> ParallelMissionCompletionAdmission:
    """Require every finite lane to reach its own terminal disposition.

    This is a completion projection, not a parallel executor. A lane is terminal
    only when canonical delivery is proven or when its own current evidence says
    no capable implementation route exists. One blocked lane never converts an
    independently actionable sibling into completion.
    """
    if type(lanes) is not tuple or not lanes:
        raise ValueError("lanes must be a non-empty tuple")
    if any(type(lane) is not MissionCompletionAdmission for lane in lanes):
        raise TypeError("every lane must be an exact MissionCompletionAdmission")

    reasons: list[str] = []
    next_actions: list[str] = []
    terminal_count = 0
    for lane in lanes:
        if lane.completion_admissible:
            terminal_count += 1
            continue
        if not lane.capable_route_available:
            terminal_count += 1
            reasons.append(f"lane-{lane.issue_number}-terminal-capability-blocker")
            continue
        reasons.append(f"lane-{lane.issue_number}-nonterminal")
        next_actions.append(lane.next_action)

    complete = terminal_count == len(lanes)
    if complete:
        reasons.append("all-parallel-lanes-terminal")
    else:
        reasons.append("parallel-mission-has-actionable-lanes")

    return ParallelMissionCompletionAdmission(
        lane_count=len(lanes),
        terminal_lane_count=terminal_count,
        completion_admissible=complete,
        reason_codes=tuple(reasons),
        next_actions=tuple(next_actions),
    )


def _validate_identity(repository: str, issue_number: int) -> None:
    if type(repository) is not str or "/" not in repository or not repository.strip():
        raise ValueError("repository must be non-empty owner/name text")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("issue_number must be a positive built-in integer")
