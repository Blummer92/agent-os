from workflow_scheduler.adapters.github_readonly_adapter import GitHubReadOnlyAdapter
from workflow_scheduler.models import Task


def _task():
    return Task(id="bug-1741", workflow_id="w", type="read", owner="system", action="read:github", idempotency_key="bug-1741", payload={"action": "list_pr_changed_filenames", "repository_full_name": "Blummer92/agent-os", "pr_number": 1})


def test_changed_files_fail_closed_on_malformed_entries():
    adapter = GitHubReadOnlyAdapter(http_get=lambda *_: [{"filename": "ok.py"}, "corrupt"])
    result = adapter.execute(_task())
    assert result["status"] == "failure"


def test_changed_files_fail_closed_on_missing_filename():
    adapter = GitHubReadOnlyAdapter(http_get=lambda *_: [{"filename": "ok.py"}, {}])
    result = adapter.execute(_task())
    assert result["status"] == "failure"
