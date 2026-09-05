from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class BranchSnapshot:
    repository: str
    ref: str
    sha: str


@dataclass(frozen=True, slots=True)
class PullRequestSnapshot:
    repository: str
    pr_number: int
    base_ref: str
    head_ref: str
    head_sha: str
    state: str
    draft: bool
    merged: bool


@dataclass(frozen=True, slots=True)
class IssueSnapshot:
    repository: str
    issue_number: int
    state: str
    state_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CiSnapshot:
    repository: str
    head_sha: str
    attached: bool
    state: str


class GitHubLineageProvider(Protocol):
    def read_branch(self, repository: str, ref: str) -> BranchSnapshot: ...
    def read_pr(self, repository: str, pr_number: int) -> PullRequestSnapshot: ...
    def read_issue(self, repository: str, issue_number: int) -> IssueSnapshot: ...
    def read_ci(self, repository: str, head_sha: str) -> CiSnapshot: ...
    def pr_contains_commit(self, repository: str, pr_number: int, sha: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class GitHubLineageExpectation:
    repository: str
    issue_number: int
    pr_number: int
    base_ref: str
    head_ref: str
    expected_head_sha: str | None = None
    expected_pr_draft: bool | None = None
    require_ci: bool = False
    require_open_pr_for_active_issue: bool = True
    merge_authorized: bool = False
    issue_closure_authorized: bool = False


@dataclass(frozen=True, slots=True)
class GitHubLineageReconciliationResult:
    status: str
    reason_codes: tuple[str, ...]
    issue: IssueSnapshot | None
    branch: BranchSnapshot | None
    pr: PullRequestSnapshot | None
    ci: CiSnapshot | None
    mutation_allowed: bool
    reportable_head_sha: str | None
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    protected_setting_authorized: bool = field(default=False, init=False)
    production_authorized: bool = field(default=False, init=False)
    external_system_write_authorized: bool = field(default=False, init=False)


def reconcile_github_lineage(
    provider: GitHubLineageProvider,
    expectation: GitHubLineageExpectation,
) -> GitHubLineageReconciliationResult:
    """Reacquire and reconcile canonical issue -> branch -> PR -> CI state.

    The function is intentionally read-only. It converts current canonical state
    into a deterministic convergence classification and never grants merge,
    issue-closure, protected-setting, production, or external-write authority.
    """
    reasons: set[str] = set()

    try:
        issue = provider.read_issue(expectation.repository, expectation.issue_number)
        branch = provider.read_branch(expectation.repository, expectation.head_ref)
        pr = provider.read_pr(expectation.repository, expectation.pr_number)
    except Exception as exc:
        return GitHubLineageReconciliationResult(
            status="uncertain",
            reason_codes=(f"canonical-read-failed:{type(exc).__name__}",),
            issue=None,
            branch=None,
            pr=None,
            ci=None,
            mutation_allowed=False,
            reportable_head_sha=None,
        )

    if issue.repository != expectation.repository:
        reasons.add("issue-repository-mismatch")
    if pr.repository != expectation.repository:
        reasons.add("pr-repository-mismatch")
    if branch.repository != expectation.repository:
        reasons.add("branch-repository-mismatch")
    if pr.pr_number != expectation.pr_number:
        reasons.add("pr-number-mismatch")
    if pr.base_ref != expectation.base_ref:
        reasons.add("base-ref-mismatch")
    if pr.head_ref != expectation.head_ref:
        reasons.add("head-ref-mismatch")

    if expectation.expected_head_sha is not None:
        if branch.sha != expectation.expected_head_sha:
            reasons.add("branch-ref-did-not-converge-to-write-sha")
        if pr.head_sha != expectation.expected_head_sha:
            reasons.add("pr-head-did-not-converge-to-write-sha")

    if pr.head_sha != branch.sha:
        reasons.add("branch-pr-head-divergence")

    try:
        if not provider.pr_contains_commit(expectation.repository, expectation.pr_number, branch.sha):
            reasons.add("pr-lineage-missing-branch-head")
    except Exception as exc:
        reasons.add(f"pr-lineage-read-failed:{type(exc).__name__}")

    if pr.merged and not expectation.merge_authorized:
        reasons.add("unauthorized-terminal-state")
        reasons.add("pr-merged-without-authority")

    if expectation.expected_pr_draft is not None and pr.draft != expectation.expected_pr_draft:
        reasons.add("draft-ready-state-drift")

    if issue.state == "closed" and issue.state_reason == "completed" and not pr.merged:
        reasons.add("issue-completed-with-open-or-unmerged-pr")

    if (
        expectation.require_open_pr_for_active_issue
        and issue.state == "open"
        and pr.state != "open"
        and not pr.merged
    ):
        reasons.add("active-issue-with-nonopen-pr")

    ci: CiSnapshot | None = None
    if expectation.require_ci:
        try:
            ci = provider.read_ci(expectation.repository, branch.sha)
        except Exception as exc:
            reasons.add(f"ci-read-failed:{type(exc).__name__}")
        else:
            if ci.head_sha != branch.sha:
                reasons.add("ci-head-mismatch")
            if not ci.attached:
                reasons.add("expected-exact-head-ci-missing")

    status = _classify(reasons)
    return GitHubLineageReconciliationResult(
        status=status,
        reason_codes=tuple(sorted(reasons)) if reasons else ("canonical-lineage-converged",),
        issue=issue,
        branch=branch,
        pr=pr,
        ci=ci,
        mutation_allowed=status == "converged",
        reportable_head_sha=branch.sha,
    )


def _classify(reasons: set[str]) -> str:
    if not reasons:
        return "converged"
    if "unauthorized-terminal-state" in reasons:
        return "unauthorized-terminal-state"
    if any(
        reason.startswith("canonical-read-failed:")
        or reason.startswith("pr-lineage-read-failed:")
        or reason.startswith("ci-read-failed:")
        for reason in reasons
    ):
        return "uncertain"
    if any(
        reason in reasons
        for reason in (
            "issue-repository-mismatch",
            "pr-repository-mismatch",
            "branch-repository-mismatch",
            "pr-number-mismatch",
            "base-ref-mismatch",
            "head-ref-mismatch",
            "draft-ready-state-drift",
            "issue-completed-with-open-or-unmerged-pr",
            "active-issue-with-nonopen-pr",
        )
    ):
        return "conflicting"
    return "stale"
