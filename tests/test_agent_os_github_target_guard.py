import pytest

from scripts.agent_os_github_target_guard import (
    GitHubTargetEvidence,
    GitHubTargetKind,
    check_operation_compatibility,
)


def issue():
    return GitHubTargetEvidence("Blummer92/agent-os", 897, GitHubTargetKind.ISSUE, "https://github.com/Blummer92/agent-os/issues/897")


def pr():
    return GitHubTargetEvidence("Blummer92/agent-os", 897, GitHubTargetKind.PULL_REQUEST, "https://github.com/Blummer92/agent-os/pull/897")


def test_issue_operation_rejects_pull_request_target():
    result = check_operation_compatibility(pr(), "update-issue")
    assert result.compatible is False
    assert result.reason == "target-kind-incompatible"
    assert result.authorization_granted is False
    assert result.mutation_performed is False


def test_pr_operation_rejects_issue_target():
    assert check_operation_compatibility(issue(), "review-pull-request").compatible is False
    assert check_operation_compatibility(issue(), "merge-pull-request").compatible is False


def test_matching_read_operations_are_compatible_but_non_authorizing():
    assert check_operation_compatibility(issue(), "read-issue").compatible is True
    result = check_operation_compatibility(pr(), "read-pull-request")
    assert result.compatible is True
    assert result.authorization_granted is False


def test_unknown_operation_fails_closed():
    assert check_operation_compatibility(issue(), "delete-everything").reason == "operation-unknown"


def test_canonical_url_must_match_kind():
    with pytest.raises(ValueError):
        GitHubTargetEvidence("Blummer92/agent-os", 897, GitHubTargetKind.ISSUE, "https://github.com/Blummer92/agent-os/pull/897")
