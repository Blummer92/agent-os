import pytest

from workflow_scheduler.adapters.github_pr_comment_adapter import GitHubPRCommentAdapter
from workflow_scheduler.models import Task


def _task():
    return Task(id="bug-1745", workflow_id="w", type="write", owner="system", action="write:github", idempotency_key="bug-1745", payload={"action": "post_pr_comment", "repository_full_name": "Blummer92/agent-os", "pr_number": 1, "body": "hello"})


@pytest.mark.parametrize("response", [["corrupt"], "corrupt", 7])
def test_comment_write_never_leaks_attribute_error(response):
    adapter = GitHubPRCommentAdapter(http_post_comment=lambda *_: response)
    result = adapter.execute(_task())
    assert result["status"] == "failure"
