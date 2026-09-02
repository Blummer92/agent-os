"""Regression coverage for #1706."""

import pytest

from workflow_scheduler.adapters.github_readonly_adapter import GitHubReadOnlyAdapter
from workflow_scheduler.models import Task


class FakeGet:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        return {"full_name": "owner/repo"}


def task(repository_full_name):
    return Task(id="bug-1706", workflow_id="wf", type="read", owner="system", action="get_repo", idempotency_key="bug-1706", payload={"action": "get_repo", "repository_full_name": repository_full_name})


@pytest.mark.parametrize("value", [123, "owner", "/repo", "owner/", "owner/repo/extra"])
def test_invalid_repository_identity_fails_before_http(value):
    http = FakeGet()
    result = GitHubReadOnlyAdapter(http_get=http).execute(task(value))
    assert result["status"] == "failure"
    assert "repository_full_name" in result["message"]
    assert http.calls == []
