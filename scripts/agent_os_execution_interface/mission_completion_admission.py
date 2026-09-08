from __future__ import annotations

from dataclasses import dataclass, field


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
) -> MissionCompletionAdmission:
    """Prevent subordinate writes from masquerading as implementation completion.

    This projection does not create branches, commits, PRs, comments, handoffs, or
    execution authority. It consumes canonical state supplied by the caller and
    returns the next required continuation step for an already-authorized finite
    implementation mission.
    """
    _validate_identity(repository, issue_number)
    for name, value in (
        ("branch_exists", branch_exists),
        ("draft_pr_exists", draft_pr_exists),
        ("canonical_pr_readback_verified", canonical_pr_readback_verified),
        ("capable_route_available", capable_route_available),
        ("subordinate_writes_only", subordinate_writes_only),
    ):
        if type(value) is not bool:
            raise TypeError(f"{name} must be built-in bool")
    if type(implementation_commit_count) is not int or implementation_commit_count < 0:
        raise ValueError("implementation_commit_count must be a non-negative built-in integer")

    reasons: list[str] = []
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

    if not reasons:
        completion_admissible = True
        next_action = "report-canonically-verified-draft-pr-delivery"
        reasons.append("canonical-implementation-delivery-proven")
    else:
        completion_admissible = False
        if capable_route_available:
            next_action = "continue-same-lineage-on-capable-implementation-route"
        else:
            next_action = "report-exact-patch-capability-blocker-without-completion-claim"

    return MissionCompletionAdmission(
        repository=repository,
        issue_number=issue_number,
        branch_exists=branch_exists,
        implementation_commit_count=implementation_commit_count,
        draft_pr_exists=draft_pr_exists,
        canonical_pr_readback_verified=canonical_pr_readback_verified,
        capable_route_available=capable_route_available,
        subordinate_writes_only=subordinate_writes_only,
        completion_admissible=completion_admissible,
        reason_codes=tuple(reasons),
        next_action=next_action,
    )


def _validate_identity(repository: str, issue_number: int) -> None:
    if type(repository) is not str or "/" not in repository or not repository.strip():
        raise ValueError("repository must be non-empty owner/name text")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("issue_number must be a positive built-in integer")
