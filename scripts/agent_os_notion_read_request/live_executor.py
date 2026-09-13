"""Lazy activation binding for the bounded #2283 Notion read path.

The workflow may select this factory before admission, but the canonical
``NotionReadOnlyAdapter`` is not constructed until
``execute_admitted_notion_read`` has proved ``secret_dispatch_authorized``.
The existing #2282 action bound is applied by ``execution.py`` around the task
callable returned here, so this module creates no second read/write policy.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter
from workflow_scheduler.models import Task

from .models import NotionReadRequestError

AdapterFactory = Callable[[], NotionReadOnlyAdapter]
SchedulerTaskExecutor = Callable[[Mapping[str, object]], object]
SchedulerTaskExecutorFactory = Callable[[], SchedulerTaskExecutor]


def build_live_notion_executor_factory(
    *,
    adapter_factory: AdapterFactory = NotionReadOnlyAdapter,
) -> SchedulerTaskExecutorFactory:
    """Return a lazy factory for the existing #936 read-only adapter.

    Calling this function reads no credential and performs no network I/O.
    ``adapter_factory`` is invoked only when the returned factory is invoked,
    which happens behind the canonical #2283 admission gate.
    """

    if not callable(adapter_factory):
        raise TypeError("adapter_factory must be callable")

    def factory() -> SchedulerTaskExecutor:
        adapter = adapter_factory()
        if not isinstance(adapter, NotionReadOnlyAdapter):
            raise TypeError("adapter_factory must return NotionReadOnlyAdapter")
        if not adapter.token:
            raise NotionReadRequestError("NOTION_TOKEN is unavailable")

        def execute_task(payload: Mapping[str, object]) -> object:
            if not isinstance(payload, Mapping):
                raise TypeError("Notion task payload must be a mapping")
            action = payload.get("action")
            if not isinstance(action, str) or not action:
                raise NotionReadRequestError("Notion task action is required")

            task = Task(
                id=f"agent-os-notion-read-{action}",
                workflow_id="agent-os-notion-read",
                type="read",
                owner="agent-os-notion-read-request",
                action=action,
                idempotency_key=f"agent-os-notion-read-{action}",
                payload=dict(payload),
            )
            result: Any = adapter.execute(task)
            if not isinstance(result, Mapping):
                raise NotionReadRequestError("Notion adapter returned malformed task evidence")
            return dict(result)

        return execute_task

    return factory


__all__ = ["build_live_notion_executor_factory"]
