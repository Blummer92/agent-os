"""B3 regression: the typed GitHub target-identity guard is wired at the MCP boundary.

Every MCP tool path taking issue_number/pr_number must construct
GitHubTargetEvidence before any other logic and fail closed on kind mismatch.
A dead guard that looks like a boundary is worse than none; these tests pin
the wiring: kind mismatch fails closed for both issue and PR paths, and
well-formed calls pass through unchanged.
"""

import pytest

from scripts.agent_os_github_target_guard import (
    GitHubTargetEvidence,
    GitHubTargetKind,
    _OPERATION_KINDS,
)
from agent_os_execution_service import mcp_server
from agent_os_execution_service.mcp_server import (
    GitHubTargetRefused,
    _GITHUB_TARGET_OPERATION_KINDS,
    _github_target_entry_guard,
)

REPOSITORY = "Blummer92/agent-os"


# ---------------------------------------------------------------------------
# entry-guard unit behavior
# ---------------------------------------------------------------------------


def test_entry_guard_builds_issue_evidence_for_well_formed_call():
    target = _github_target_entry_guard(
        repository=REPOSITORY, issue_number=1985, operation="read-issue"
    )
    assert isinstance(target, GitHubTargetEvidence)
    assert target.kind is GitHubTargetKind.ISSUE
    assert target.number == 1985
    assert target.canonical_url == f"https://github.com/{REPOSITORY}/issues/1985"


def test_entry_guard_builds_pr_evidence_for_well_formed_call():
    target = _github_target_entry_guard(
        repository=REPOSITORY, pr_number=3323, operation="review-pull-request"
    )
    assert isinstance(target, GitHubTargetEvidence)
    assert target.kind is GitHubTargetKind.PULL_REQUEST
    assert target.canonical_url == f"https://github.com/{REPOSITORY}/pull/3323"


def test_entry_guard_refuses_pr_target_for_issue_operation():
    """Kind mismatch, PR path: a pull-request number routed into an issue
    operation fails closed instead of being coerced."""
    with pytest.raises(GitHubTargetRefused) as excinfo:
        _github_target_entry_guard(
            repository=REPOSITORY, pr_number=3323, operation="read-issue"
        )
    assert excinfo.value.reason_code == "github-target-kind-incompatible"


def test_entry_guard_refuses_issue_target_for_pr_operation():
    """Kind mismatch, issue path: an issue number routed into a pull-request
    operation fails closed instead of being coerced."""
    with pytest.raises(GitHubTargetRefused) as excinfo:
        _github_target_entry_guard(
            repository=REPOSITORY, issue_number=1985, operation="review-pull-request"
        )
    assert excinfo.value.reason_code == "github-target-kind-incompatible"


def test_entry_guard_refuses_ambiguous_target():
    with pytest.raises(GitHubTargetRefused) as excinfo:
        _github_target_entry_guard(
            repository=REPOSITORY,
            issue_number=1985,
            pr_number=3323,
            operation="read-issue",
        )
    assert excinfo.value.reason_code == "github-target-ambiguous-or-missing"


def test_entry_guard_refuses_missing_target():
    with pytest.raises(GitHubTargetRefused) as excinfo:
        _github_target_entry_guard(repository=REPOSITORY, operation="read-issue")
    assert excinfo.value.reason_code == "github-target-ambiguous-or-missing"


@pytest.mark.parametrize("bad_number", [0, -3, "1985", 1985.0, True, None])
def test_entry_guard_refuses_non_positive_integer_number(bad_number):
    with pytest.raises(GitHubTargetRefused) as excinfo:
        _github_target_entry_guard(
            repository=REPOSITORY, issue_number=bad_number, operation="read-issue"
        )
    assert excinfo.value.reason_code in (
        "github-target-ambiguous-or-missing",
        "github-target-number-invalid",
    )


def test_entry_guard_refuses_malformed_repository():
    with pytest.raises(GitHubTargetRefused) as excinfo:
        _github_target_entry_guard(
            repository="not-a-repository", issue_number=1985, operation="read-issue"
        )
    assert excinfo.value.reason_code == "github-target-identity-invalid"


def test_entry_guard_repository_agnostic_path_still_checks_kind():
    """Tools without a repository parameter still get kind/number/operation
    checks; compatible calls return None (no evidence to bind)."""
    assert (
        _github_target_entry_guard(
            repository=None, issue_number=1985, operation="update-issue"
        )
        is None
    )
    with pytest.raises(GitHubTargetRefused) as excinfo:
        _github_target_entry_guard(
            repository=None, pr_number=3323, operation="update-issue"
        )
    assert excinfo.value.reason_code == "github-target-kind-incompatible"


def test_entry_guard_refused_carries_stable_reason_code():
    refused = GitHubTargetRefused("github-target-kind-incompatible", "detail")
    assert isinstance(refused, ValueError)
    assert refused.reason_code == "github-target-kind-incompatible"
    assert "github-target-kind-incompatible" in str(refused)


def test_local_operation_kind_map_parities_guard_module():
    """The repository-agnostic allowlist must mirror the canonical guard
    module; drift between the two would silently change the boundary."""
    for operation, kinds in _GITHUB_TARGET_OPERATION_KINDS.items():
        assert frozenset(kinds) == _OPERATION_KINDS[operation]
    assert set(_GITHUB_TARGET_OPERATION_KINDS) == set(_OPERATION_KINDS)


# ---------------------------------------------------------------------------
# tool-level wiring: guard runs before any other logic
# ---------------------------------------------------------------------------


def test_issue_tool_fails_closed_before_logic_on_bad_number():
    with pytest.raises(GitHubTargetRefused):
        mcp_server.plan_agent_os_continuation_tool(
            repository=REPOSITORY, issue_number=0
        )


def test_pr_tool_fails_closed_before_logic_on_bad_number():
    with pytest.raises(GitHubTargetRefused):
        mcp_server.admit_agent_os_ready_for_review_tool(
            repository=REPOSITORY,
            pr_number=-1,
            pr_lifecycle_state="draft",
            expected_head_sha="a" * 40,
            observed_head_sha="a" * 40,
            validation_head_sha="a" * 40,
            validation_admission_mode="exact-head",
            aggregate_status="success",
            focused_status="success",
            requested_changes=False,
            blocking_unresolved=0,
            ready_for_review_authority_supplied=True,
            pr_title="title",
            pr_body="body",
        )


def test_continuation_tool_fails_closed_on_bad_pull_request():
    with pytest.raises(GitHubTargetRefused):
        mcp_server.classify_agent_os_continuation_tool(
            repository=REPOSITORY,
            issue_number=1985,
            operation_id="op",
            surface_outcome="outcome",
            pull_request=0,
        )


def test_batch_pr_tool_fails_closed_on_bad_item_number():
    with pytest.raises(GitHubTargetRefused):
        mcp_server.admit_agent_os_batch_pr_packaging_tool(
            [{"issue_number": 0, "pr_number": 1}],
            evidence_current=True,
        )


def test_well_formed_issue_tool_passes_through_unchanged():
    """A well-formed call returns exactly what the underlying facade
    projection returns: the guard adds no behavior for good targets."""
    from agent_os_execution_service.mcp_facade import plan_agent_os_continuation

    expected = dict(
        plan_agent_os_continuation(repository=REPOSITORY, issue_number=1985)
    )
    result = mcp_server.plan_agent_os_continuation_tool(
        repository=REPOSITORY, issue_number=1985
    )
    assert result == expected
