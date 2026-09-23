"""Regression coverage for #1707."""

import pytest

from workflow_scheduler.adapters.github_readonly_adapter import GitHubReadOnlyAdapter
from workflow_scheduler.models import Task


def task():
    return Task(id="bug-1707", workflow_id="wf", type="read", owner="system", action="get_pr_info", idempotency_key="bug-1707", payload={"action": "get_pr_info", "repository_full_name": "owner/repo", "pr_number": 1})


@pytest.mark.parametrize("user", ["octocat", ["octocat"], 7, True])
def test_malformed_user_payload_becomes_contract_failure(user):
    adapter = GitHubReadOnlyAdapter(http_get=lambda *_: {"number": 1, "user": user})
    result = adapter.execute(task())
    assert result["status"] == "failure"
    assert "user" in result["message"]
