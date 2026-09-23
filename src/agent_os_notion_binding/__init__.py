"""Composition root binding the canonical Workflow Scheduler Notion reader.

#2283's ``scripts/agent_os_notion_read_request`` package is a provider-neutral
bounded read seam: ``execution.py`` takes its Scheduler task executor by
injection, and ``tests/agent_os_notion_read_request/test_architecture_boundaries.py``
keeps the Scheduler an injected caller concern. The repository-wide #752/#912
packaging boundary in ``tests/test_workflow_scheduler_packaging.py``
independently permits exactly two ``scripts/**`` importers of
``workflow_scheduler``, neither of them in that package.

This module is therefore where the ``workflow_scheduler`` binding lives, exactly
as ``agent_os_execution_service.lesson_reader_composition`` already does for the
CKR11 lesson reader. It creates no Notion client, credential path, second
scheduler, cache, retry loop, or read/write policy: ``NOTION_TOKEN`` remains
owned by the existing #936 adapter and the bounded read-action surface remains
owned by #2282.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter
from workflow_scheduler.models import Task

#: Zero-argument factory returning the canonical #936 read-only adapter.
AdapterFactory = Callable[[], NotionReadOnlyAdapter]

#: Fixed Scheduler task type for every dispatch built here. The binding exposes
#: no write type, so no caller can widen the inherited read-only bound.
READ_TASK_TYPE = "read"


class NotionBindingError(RuntimeError):
    """The canonical read-only Notion binding could not be composed.

    Callers translate this into their own bounded error vocabulary rather than
    importing a second error hierarchy.
    """


def new_read_adapter(adapter_factory: AdapterFactory | None = None) -> NotionReadOnlyAdapter:
    """Construct the canonical read-only adapter and prove it is usable.

    Construction is deliberately separate from binding assembly so a caller can
    build its factory without reading a credential. ``adapter_factory`` defaults
    to the canonical #936 adapter; tests inject their own.
    """
    factory: AdapterFactory = adapter_factory or NotionReadOnlyAdapter
    if not callable(factory):
        raise TypeError("adapter_factory must be callable")

    adapter = factory()
    if not isinstance(adapter, NotionReadOnlyAdapter):
        raise TypeError("adapter_factory must return NotionReadOnlyAdapter")
    if not adapter.token:
        raise NotionBindingError("NOTION_TOKEN is unavailable")
    return adapter


def build_read_task(
    *,
    task_id: str,
    workflow_id: str,
    owner: str,
    action: str,
    idempotency_key: str,
    payload: Mapping[str, Any],
) -> Task:
    """Build one canonical read-only Scheduler task.

    The task ``type`` is fixed to :data:`READ_TASK_TYPE`; this helper exists so
    the bounded #2283 seam can dispatch through the Scheduler's own task model
    without taking a ``workflow_scheduler`` dependency of its own.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("Notion task payload must be a mapping")
    return Task(
        id=task_id,
        workflow_id=workflow_id,
        type=READ_TASK_TYPE,
        owner=owner,
        action=action,
        idempotency_key=idempotency_key,
        payload=dict(payload),
    )


__all__ = [
    "READ_TASK_TYPE",
    "AdapterFactory",
    "NotionBindingError",
    "build_read_task",
    "new_read_adapter",
]
