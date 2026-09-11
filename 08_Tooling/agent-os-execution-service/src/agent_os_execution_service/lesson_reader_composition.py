"""Production composition for bounded read-only Agent OS Notion retrieval (#2141/#2282).

This module binds Agent OS read-executor seams to the Workflow Scheduler's
canonical ``NotionReadOnlyAdapter``. It creates no Notion client, credential
path, write capability, selector, cache, mirror, or persistence layer.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter
from workflow_scheduler.models import Task

LESSONS_LEARNED_DATA_SOURCE_ENV = "AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID"
NOTION_CONTENT_SOURCE_ENVS = {
    "curriculum-assets": "AGENT_OS_CURRICULUM_ASSETS_DATA_SOURCE_ID",
    "curriculum-content": "AGENT_OS_CURRICULUM_CONTENT_DATA_SOURCE_ID",
    "lesson-planning": "AGENT_OS_LESSON_PLANNING_DATA_SOURCE_ID",
    "lessons-learned": LESSONS_LEARNED_DATA_SOURCE_ENV,
}

ReadExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]

# Fields the class-specific binding owns. A request may shape the bounded query
# but may never re-point it at another source identity or swap the read action,
# which would let one content class borrow another class's source authority.
GOVERNED_QUERY_FIELDS = frozenset({"action", "data_source_id"})


class LessonReadUnavailableError(RuntimeError):
    """The existing read-only Notion surface could not return bounded rows."""


def build_notion_read_executor(
    *,
    content_class: str,
    data_source_id: str | None = None,
    adapter: NotionReadOnlyAdapter | None = None,
) -> ReadExecutor | None:
    """Bind one approved Agent OS Notion content class to the canonical adapter.

    Source identity is resolved from the caller or the class-specific environment
    binding. Missing identity is represented as unavailable rather than guessed.
    #2283 owns any live credential/source-sharing/runtime activation required to
    populate those bindings.
    """
    if content_class not in NOTION_CONTENT_SOURCE_ENVS:
        raise ValueError(f"unsupported Notion content class: {content_class}")

    resolved_data_source_id = (
        data_source_id
        if data_source_id is not None
        else os.environ.get(NOTION_CONTENT_SOURCE_ENVS[content_class])
    )
    if not resolved_data_source_id or not resolved_data_source_id.strip():
        return None

    notion = adapter or NotionReadOnlyAdapter()
    source_id = resolved_data_source_id.strip()
    slug = content_class.replace("-", "_")

    def execute_read(query: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(query, Mapping):
            raise TypeError("Notion query must be a mapping")
        governed = sorted(GOVERNED_QUERY_FIELDS.intersection(query))
        if governed:
            raise ValueError(
                "Notion query must not override governed read fields: "
                f"{', '.join(governed)}"
            )

        payload = {"action": "query_data_source", "data_source_id": source_id}
        payload.update(dict(query))
        page_size = payload.get("page_size", 5)
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            raise ValueError("Notion query page_size must be a positive integer")
        payload.setdefault("max_pages", 1)
        payload.setdefault("max_results", page_size)

        task = Task(
            id=f"agent-os-{slug}-read",
            workflow_id=f"agent-os-{slug}",
            type="read",
            owner="agent-os-execution-service",
            action="query_data_source",
            idempotency_key=f"agent-os-{slug}-read",
            payload=payload,
        )
        result = notion.execute(task)
        if result.get("status") != "success":
            raise LessonReadUnavailableError(str(result.get("message") or "Notion read unavailable"))
        output = result.get("output")
        if not isinstance(output, Mapping):
            raise LessonReadUnavailableError("Notion read returned malformed output")
        return output

    return execute_read


def build_lesson_read_executor(
    *,
    data_source_id: str | None = None,
    adapter: NotionReadOnlyAdapter | None = None,
) -> ReadExecutor | None:
    """Backward-compatible CKR11 wrapper for the Lessons Learned content class."""
    return build_notion_read_executor(
        content_class="lessons-learned",
        data_source_id=data_source_id,
        adapter=adapter,
    )


__all__ = [
    "GOVERNED_QUERY_FIELDS",
    "LESSONS_LEARNED_DATA_SOURCE_ENV",
    "NOTION_CONTENT_SOURCE_ENVS",
    "LessonReadUnavailableError",
    "build_lesson_read_executor",
    "build_notion_read_executor",
]
