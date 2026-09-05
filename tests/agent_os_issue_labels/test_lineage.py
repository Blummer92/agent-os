from dataclasses import replace

from scripts.agent_os_issue_labels.lineage import (
    BranchSnapshot,
    CiSnapshot,
    GitHubLineageExpectation,
    IssueSnapshot,
    PullRequestSnapshot,
    reconcile_github_lineage,
)


REPO = "Blummer92/agent-os"
SHA = "abc123"


class Provider:
    def __init__(self):
        self.issue = IssueSnapshot(REPO, 1879, "open")
        self.branch = BranchSnapshot(REPO, "agent/1879", SHA)
        self.pr = PullRequestSnapshot(REPO, 2000, "main", "agent/1879", SHA, "open", True, False)
        self.ci = CiSnapshot(REPO, SHA, True, "queued")
        self.contains = True
        self.fail_ci = False

    def read_issue(self, repository, issue_number):
        return self.issue

    def read_branch(self, repository, ref):
        return self.branch

    def read_pr(self, repository, pr_number):
        return self.pr

    def read_ci(self, repository, head_sha):
        if self.fail_ci:
            raise RuntimeError("ci unavailable")
        return self.ci

    def pr_contains_commit(self, repository, pr_number, sha):
        return self.contains


def expectation(**changes):
    base = GitHubLineageExpectation(
        repository=REPO,
        issue_number=1879,
        pr_number=2000,
        base_ref="main",
        head_ref="agent/1879",
        expected_head_sha=SHA,
        expected_pr_draft=True,
        require_ci=True,
    )
    return replace(base, **changes)


def test_converged_lineage_uses_current_canonical_state():
    result = reconcile_github_lineage(Provider(), expectation())

    assert result.status == "converged"
    assert result.reason_codes == ("canonical-lineage-converged",)
    assert result.reportable_head_sha == SHA
    assert result.mutation_allowed is True


def test_branch_write_must_converge_to_branch_and_pr_head():
    provider = Provider()
    provider.pr = replace(provider.pr, head_sha="old")

    result = reconcile_github_lineage(provider, expectation())

    assert result.status == "stale"
    assert "branch-pr-head-divergence" in result.reason_codes
    assert "pr-head-did-not-converge-to-write-sha" in result.reason_codes
    assert result.mutation_allowed is False


def test_missing_exact_head_ci_is_explicit_stale_evidence():
    provider = Provider()
    provider.ci = replace(provider.ci, attached=False)

    result = reconcile_github_lineage(provider, expectation())

    assert result.status == "stale"
    assert "expected-exact-head-ci-missing" in result.reason_codes


def test_ci_read_failure_is_uncertain_and_fail_closed():
    provider = Provider()
    provider.fail_ci = True

    result = reconcile_github_lineage(provider, expectation())

    assert result.status == "uncertain"
    assert "ci-read-failed:RuntimeError" in result.reason_codes
    assert result.mutation_allowed is False


def test_draft_to_ready_drift_is_conflicting():
    provider = Provider()
    provider.pr = replace(provider.pr, draft=False)

    result = reconcile_github_lineage(provider, expectation())

    assert result.status == "conflicting"
    assert "draft-ready-state-drift" in result.reason_codes


def test_merged_without_authority_is_unauthorized_terminal_state():
    provider = Provider()
    provider.pr = replace(provider.pr, state="closed", draft=False, merged=True)

    result = reconcile_github_lineage(provider, expectation(expected_pr_draft=None))

    assert result.status == "unauthorized-terminal-state"
    assert "unauthorized-terminal-state" in result.reason_codes
    assert result.mutation_allowed is False
    assert result.merge_authorized is False


def test_completed_issue_with_unmerged_pr_is_conflicting():
    provider = Provider()
    provider.issue = replace(provider.issue, state="closed", state_reason="completed")

    result = reconcile_github_lineage(provider, expectation())

    assert result.status == "conflicting"
    assert "issue-completed-with-open-or-unmerged-pr" in result.reason_codes


def test_missing_branch_head_from_pr_lineage_is_stale():
    provider = Provider()
    provider.contains = False

    result = reconcile_github_lineage(provider, expectation())

    assert result.status == "stale"
    assert "pr-lineage-missing-branch-head" in result.reason_codes


def test_secondary_visibility_is_not_part_of_identity_contract():
    result = reconcile_github_lineage(Provider(), expectation())

    assert result.status == "converged"
    assert not any("visibility" in reason for reason in result.reason_codes)
