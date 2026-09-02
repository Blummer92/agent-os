import pytest

from workflow_scheduler.adapters.github_readonly_adapter import GitHubReadOnlyAdapter
from workflow_scheduler.models import Task


def _task():
    return Task(id="bug-1742", workflow_id="w", type="read", owner="system", action="read:github", idempotency_key="bug-1742", payload={"action": "list_recent_prs", "repository_full_name": "Blummer92/agent-os"})


def _execute(response):
    return GitHubReadOnlyAdapter(http_get=lambda *_: response).execute(_task())


def test_recent_prs_fail_closed_on_malformed_entries():
    result = _execute([{"number": 1, "title": "ok", "state": "open"}, "corrupt"])
    assert result["status"] == "failure"


@pytest.mark.parametrize("response", [{"number": 1}, "corrupt", None])
def test_recent_prs_fail_closed_on_malformed_root(response):
    assert _execute(response)["status"] == "failure"


@pytest.mark.parametrize("number", [None, 0, -1, True, "1"])
def test_recent_prs_fail_closed_on_invalid_identity(number):
    result = _execute([{"number": number, "title": "bad identity", "state": "open"}])
    assert result["status"] == "failure"


@pytest.mark.parametrize(
    "row",
    [
        {"number": 1, "title": None, "state": "open"},
        {"number": 1, "title": "", "state": "open"},
        {"number": 1, "title": "bad state", "state": None},
        {"number": 1, "title": "bad state", "state": "merged"},
    ],
)
def test_recent_prs_fail_closed_on_malformed_title_or_state(row):
    assert _execute([row])["status"] == "failure"


def test_recent_prs_preserve_valid_list_behavior():
    response = [
        {"number": 2, "title": "open PR", "state": "open", "ignored": "extra"},
        {"number": 1, "title": "closed PR", "state": "closed"},
    ]
    result = _execute(response)
    assert result["status"] == "success"
    assert result["output"] == {
        "pull_requests": [
            {"number": 2, "title": "open PR", "state": "open"},
            {"number": 1, "title": "closed PR", "state": "closed"},
        ]
    }
