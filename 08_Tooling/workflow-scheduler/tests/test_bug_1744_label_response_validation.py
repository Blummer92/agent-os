import pytest

from workflow_scheduler.adapters.github_pr_label_adapter import GitHubPRLabelAdapter
from workflow_scheduler.models import Task


def _task():
    return Task(
        id="bug-1744",
        workflow_id="w",
        type="write",
        owner="system",
        action="write:github",
        idempotency_key="bug-1744",
        payload={
            "action": "add_pr_label",
            "repository_full_name": "Blummer92/agent-os",
            "pr_number": 1,
            "label": "type:bug",
        },
    )


def test_label_write_fails_closed_on_non_list_response():
    adapter = GitHubPRLabelAdapter(http_post_label=lambda *_: {"unexpected": True})
    result = adapter.execute(_task())
    assert result["status"] == "failure"


def test_label_write_fails_closed_on_malformed_label_entry():
    adapter = GitHubPRLabelAdapter(http_post_label=lambda *_: [{"name": "type:bug"}, "corrupt"])
    result = adapter.execute(_task())
    assert result["status"] == "failure"


@pytest.mark.parametrize(
    "entry",
    [
        {},
        {"name": None},
        {"name": ""},
        {"name": "   "},
        {"name": 123},
    ],
)
def test_label_write_fails_closed_on_invalid_label_name(entry):
    adapter = GitHubPRLabelAdapter(http_post_label=lambda *_: [entry])
    result = adapter.execute(_task())
    assert result["status"] == "failure"


def test_label_write_preserves_valid_success_receipt():
    response = [{"name": "type:bug"}, {"name": "status:ready"}]
    adapter = GitHubPRLabelAdapter(http_post_label=lambda *_: response)
    result = adapter.execute(_task())
    assert result == {
        "status": "success",
        "message": "Added label 'type:bug' to Blummer92/agent-os#1",
        "output": {"labels": ["type:bug", "status:ready"]},
    }
