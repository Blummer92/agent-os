from workflow_scheduler.adapters.github_readonly_adapter import GitHubReadOnlyAdapter
from workflow_scheduler.models import Task


def _task():
    return Task(id="bug-1742", workflow_id="w", type="read", owner="system", action="read:github", idempotency_key="bug-1742", payload={"action": "list_recent_prs", "repository_full_name": "Blummer92/agent-os"})


def test_recent_prs_fail_closed_on_malformed_entries():
    adapter = GitHubReadOnlyAdapter(http_get=lambda *_: [{"number": 1, "title": "ok", "state": "open"}, "corrupt"])
    result = adapter.execute(_task())
    assert result["status"] == "failure"


def test_recent_prs_fail_closed_on_missing_identity():
    adapter = GitHubReadOnlyAdapter(http_get=lambda *_: [{"title": "missing number", "state": "open"}])
    result = adapter.execute(_task())
    assert result["status"] == "failure"
