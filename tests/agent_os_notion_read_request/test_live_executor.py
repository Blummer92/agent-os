"""Activation-boundary tests for the #2283 live Notion executor factory."""

from __future__ import annotations

import pytest

from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter
from scripts.agent_os_notion_read_request import (
    NotionReadRequestError,
    build_live_notion_executor_factory,
)


class RecordingAdapter(NotionReadOnlyAdapter):
    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.tasks = []

    def execute(self, task):
        self.tasks.append(task)
        return {"status": "success", "output": {"id": "page-1"}}


def test_building_factory_does_not_construct_credential_bearing_adapter() -> None:
    calls = []

    def adapter_factory():
        calls.append("constructed")
        return RecordingAdapter()

    factory = build_live_notion_executor_factory(adapter_factory=adapter_factory)

    assert callable(factory)
    assert calls == []


def test_factory_constructs_existing_adapter_only_when_invoked() -> None:
    adapter = RecordingAdapter()
    factory = build_live_notion_executor_factory(adapter_factory=lambda: adapter)

    execute = factory()
    result = execute({"action": "get_page", "page_id": "page-1"})

    assert result["status"] == "success"
    assert len(adapter.tasks) == 1
    assert adapter.tasks[0].payload == {"action": "get_page", "page_id": "page-1"}


def test_missing_token_fails_closed_before_network_dispatch(monkeypatch) -> None:
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    factory = build_live_notion_executor_factory()

    with pytest.raises(NotionReadRequestError, match="NOTION_TOKEN is unavailable"):
        factory()


def test_factory_rejects_a_different_adapter_type() -> None:
    factory = build_live_notion_executor_factory(adapter_factory=lambda: object())

    with pytest.raises(TypeError, match="must return NotionReadOnlyAdapter"):
        factory()
