"""Regression coverage for #1710."""

from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter
from workflow_scheduler.models import Task


def test_malformed_result_entry_becomes_contract_failure():
    adapter = NotionReadOnlyAdapter(http_get=lambda *_: {"results": [{"id": "ok"}, "corrupt"], "has_more": False})
    task = Task(id="bug-1710", workflow_id="wf", type="read", owner="system", action="get_block_children", idempotency_key="bug-1710", payload={"action": "get_block_children", "block_id": "block-1"})
    result = adapter.execute(task)
    assert result["status"] == "failure"
    assert "results" in result["message"]
