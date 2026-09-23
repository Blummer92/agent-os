"""Regression coverage for #1709."""

import pytest

from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter
from workflow_scheduler.models import Task


class FakeGet:
    def __init__(self): self.calls = []
    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        return {"results": [], "has_more": False}


def task(cursor):
    return Task(id="bug-1709", workflow_id="wf", type="read", owner="system", action="get_block_children", idempotency_key="bug-1709", payload={"action": "get_block_children", "block_id": "block-1", "start_cursor": cursor})


@pytest.mark.parametrize("cursor", [True, 123, [], {}, ""])
def test_invalid_start_cursor_fails_before_http(cursor):
    http = FakeGet()
    result = NotionReadOnlyAdapter(http_get=http).execute(task(cursor))
    assert result["status"] == "failure"
    assert "start_cursor" in result["message"]
    assert http.calls == []
