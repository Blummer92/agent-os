"""Production composition for bounded read-only Lessons Learned retrieval (#2141).

This module binds the existing Agent Memory CKR11 read-executor seam to the
Workflow Scheduler's canonical ``NotionReadOnlyAdapter``.  It creates no Notion
client, credential path, write capability, selector, or persistence layer.
``NOTION_TOKEN`` remains owned by the existing adapter; this composition only
resolves the non-secret canonical data-source identity.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter
from workflow_scheduler.models import Task

LESSONS_LEARNED_DATA_SOURCE_ENV = "AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID"

ReadExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class LessonReadUnavailableError(RuntimeError):
    """The existing read-only Notion surface could not return lesson rows."""


def build_lesson_read_executor(
    *,
    data_source_id: str | None = None,
    adapter: NotionReadOnlyAdapter | None = None,
) -> ReadExecutor | None:
    """Bind CKR11's read seam to the canonical Scheduler Notion adapter.

    A missing data-source identity is an unavailable read surface, represented by
    ``None`` so the existing CKR6 safe-fallback path remains authoritative.
    Tests may inject an adapter; production reuses the adapter's existing
    ``NOTION_TOKEN`` environment configuration.
    """

    resolved_data_source_id = (
        data_source_id
        if data_source_id is not None
        else os.environ.get(LESSONS_LEARNED_DATA_SOURCE_ENV)
    )
    if not resolved_data_source_id or not resolved_data_source_id.strip():
        return None

    notion = adapter or NotionReadOnlyAdapter()
    source_id = resolved_data_source_id.strip()

    def execute_read(query: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(query, Mapping):
            raise TypeError("lesson query must be a mapping")

        payload = {"action": "query_data_source", "data_source_id": source_id}
        payload.update(dict(query))
        page_size = payload.get("page_size", 5)
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            raise ValueError("lesson query page_size must be a positive integer")
        payload.setdefault("max_pages", 1)
        payload.setdefault("max_results", page_size)

        task = Task(
            id="agent-os-lessons-learned-read",
            workflow_id="agent-os-lessons-learned",
            type="read",
            owner="agent-os-execution-service",
            action="query_data_source",
            idempotency_key="agent-os-lessons-learned-read",
            payload=payload,
        )
        result = notion.execute(task)
        if result.get("status") != "success":
            raise LessonReadUnavailableError(str(result.get("message") or "Notion lesson read unavailable"))
        output = result.get("output")
        if not isinstance(output, Mapping):
            raise LessonReadUnavailableError("Notion lesson read returned malformed output")
        return output

    return execute_read
