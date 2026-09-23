"""Regression coverage for #1687."""

import pytest

from workflow_scheduler.adapters.github_readonly_adapter import GitHubReadOnlyAdapter
from workflow_scheduler.models import Task


@pytest.mark.parametrize("state", ["OPEN", "merged", "", 1])
def test_list_recent_prs_rejects_invalid_state_without_http(state):
    calls = []
    adapter = GitHubReadOnlyAdapter(http_get=lambda *args: calls.append(args) or [])
    task = Task(id="bug-1687", workflow_id="w", type="read", owner="system", action="read:github", idempotency_key="bug-1687", payload={"action": "list_recent_prs", "repository_full_name": "x/y", "state": state})
    result = adapter.execute(task)
    assert result["status"] == "failure"
    assert calls == []


@pytest.mark.parametrize("limit", [True, 0, -1, 101])
def test_list_recent_prs_rejects_invalid_limit_without_http(limit):
    calls = []
    adapter = GitHubReadOnlyAdapter(http_get=lambda *args: calls.append(args) or [])
    task = Task(id="bug-1687", workflow_id="w", type="read", owner="system", action="read:github", idempotency_key="bug-1687-limit", payload={"action": "list_recent_prs", "repository_full_name": "x/y", "limit": limit})
    result = adapter.execute(task)
    assert result["status"] == "failure"
    assert calls == []
