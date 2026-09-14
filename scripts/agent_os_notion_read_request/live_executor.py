"""Lazy activation binding for the bounded #2283 Notion read path.

The workflow may select this factory before admission, but the canonical
read-only adapter is not constructed until ``execute_admitted_notion_read`` has
proved ``secret_dispatch_authorized``. The existing #2282 action bound is
applied by ``execution.py`` around the task callable returned here, so this
module creates no second read/write policy.

The Scheduler itself stays an injected caller concern: ``agent_os_notion_binding``
owns the ``workflow_scheduler`` composition, so this package keeps the
provider-neutral boundary that ``test_architecture_boundaries.py`` and the
#752/#912 packaging allowlist both require.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from agent_os_notion_binding import (
    AdapterFactory,
    NotionBindingError,
    build_read_task,
    new_read_adapter,
)

from .models import NotionReadRequestError

SchedulerTaskExecutor = Callable[[Mapping[str, object]], object]
SchedulerTaskExecutorFactory = Callable[[], SchedulerTaskExecutor]


def build_live_notion_executor_factory(
    *,
    adapter_factory: AdapterFactory | None = None,
) -> SchedulerTaskExecutorFactory:
    """Return a lazy factory for the existing #936 read-only adapter.

    Calling this function reads no credential and performs no network I/O.
    ``adapter_factory`` is invoked only when the returned factory is invoked,
    which happens behind the canonical #2283 admission gate.
    """

    if adapter_factory is not None and not callable(adapter_factory):
        raise TypeError("adapter_factory must be callable")

    def factory() -> SchedulerTaskExecutor:
        try:
            adapter = new_read_adapter(adapter_factory)
        except NotionBindingError as exc:
            # Keep this package's single bounded error vocabulary.
            raise NotionReadRequestError(str(exc)) from exc

        def execute_task(payload: Mapping[str, object]) -> object:
            if not isinstance(payload, Mapping):
                raise TypeError("Notion task payload must be a mapping")
            action = payload.get("action")
            if not isinstance(action, str) or not action:
                raise NotionReadRequestError("Notion task action is required")

            task = build_read_task(
                task_id=f"agent-os-notion-read-{action}",
                workflow_id="agent-os-notion-read",
                owner="agent-os-notion-read-request",
                action=action,
                idempotency_key=f"agent-os-notion-read-{action}",
                payload=payload,
            )
            result: Any = adapter.execute(task)
            if not isinstance(result, Mapping):
                raise NotionReadRequestError("Notion adapter returned malformed task evidence")
            return dict(result)

        return execute_task

    return factory


__all__ = ["build_live_notion_executor_factory"]
