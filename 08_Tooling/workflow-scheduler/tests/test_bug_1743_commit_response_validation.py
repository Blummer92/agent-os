import pytest

from workflow_scheduler.adapters.github_readonly_adapter import GitHubReadOnlyAdapter
from workflow_scheduler.models import Task


def _task():
    return Task(id="bug-1743", workflow_id="w", type="read", owner="system", action="read:github", idempotency_key="bug-1743", payload={"action": "get_commit", "repository_full_name": "Blummer92/agent-os", "sha": "abc"})


@pytest.mark.parametrize("response", [{"commit": "corrupt"}, {"commit": {"author": ["corrupt"]}}])
def test_commit_read_never_leaks_attribute_error(response):
    adapter = GitHubReadOnlyAdapter(http_get=lambda *_: response)
    result = adapter.execute(_task())
    assert result["status"] == "failure"
