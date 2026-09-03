"""Regression coverage for #1702."""

import pytest

from workflow_scheduler.adapters.github_pr_comment_adapter import GitHubPRCommentAdapter
from workflow_scheduler.models import Task


class FakePost:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body, timeout))
        return {"id": 1}


def task(repository_full_name):
    return Task(
        id="bug-1702",
        workflow_id="workflow-1",
        type="write",
        owner="system",
        action="comment_on_pr",
        idempotency_key="bug-1702",
        payload={
            "action": "post_pr_comment",
            "repository_full_name": repository_full_name,
            "pr_number": 1,
            "body": "hi",
        },
    )


@pytest.mark.parametrize("repository_full_name", [123, "owner", "/repo", "owner/", "owner/repo/extra"])
def test_invalid_repository_full_name_fails_without_http(repository_full_name):
    http = FakePost()
    result = GitHubPRCommentAdapter(http_post_comment=http).execute(task(repository_full_name))
    assert result["status"] == "failure"
    assert "repository_full_name" in result["message"]
    assert http.calls == []


def test_valid_repository_full_name_preserves_write_target():
    http = FakePost()
    result = GitHubPRCommentAdapter(http_post_comment=http).execute(task("owner/repo"))
    assert result["status"] == "success"
    assert http.calls[0][0] == "https://api.github.com/repos/owner/repo/issues/1/comments"
