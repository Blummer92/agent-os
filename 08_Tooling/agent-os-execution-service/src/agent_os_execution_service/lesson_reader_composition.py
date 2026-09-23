"""Production composition for bounded read-only Lessons Learned retrieval (#2141 / #2331).

This module binds the existing Agent Memory CKR11 read-executor seam to the
Workflow Scheduler's canonical ``NotionReadOnlyAdapter``. It creates no Notion
client, credential path, write capability, selector, or persistence layer.
``NOTION_TOKEN`` remains owned by the existing adapter; this composition only
resolves the non-secret canonical data-source identity.

#2331 requires one additional distinction: absence of the source binding on the
*current execution surface* is route evidence, not proof that the canonical
Lessons Learned corpus is unavailable. ``resolve_lesson_read_route`` therefore
returns a small non-authorizing route projection while ``build_lesson_read_executor``
remains the compatibility wrapper used by existing callers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter
from workflow_scheduler.models import Task

LESSONS_LEARNED_DATA_SOURCE_ENV = "AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID"

ReadExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class LessonReadUnavailableError(RuntimeError):
    """The existing read-only Notion surface could not return lesson rows."""


class LessonReadRouteStatus(str, Enum):
    """Finite composition outcomes before CKR6 performs provider retrieval."""

    CONFIGURED_CANONICAL_READER = "configured-canonical-reader"
    CURRENT_SURFACE_UNBOUND = "current-surface-unbound"
    GOVERNED_ROUTE_REQUIRED = "governed-route-required"


@dataclass(frozen=True, slots=True)
class LessonReadRouteResolution:
    """Non-authorizing evidence about the canonical reader on this surface.

    ``CURRENT_SURFACE_UNBOUND`` deliberately does not mean that the canonical
    source is unavailable. It means only that this process cannot construct the
    already-canonical reader because its non-secret source identity is absent.
    """

    status: LessonReadRouteStatus
    execute_read: ReadExecutor | None
    reason_code: str
    canonical_source_unavailable: bool = False
    side_effects_performed: bool = False

    def __post_init__(self) -> None:
        if type(self.status) is not LessonReadRouteStatus:
            raise TypeError("status must be an exact LessonReadRouteStatus")
        if self.execute_read is not None and not callable(self.execute_read):
            raise TypeError("execute_read must be callable or None")
        if type(self.reason_code) is not str or not self.reason_code:
            raise ValueError("reason_code must be non-empty")
        if type(self.canonical_source_unavailable) is not bool:
            raise TypeError("canonical_source_unavailable must be an exact boolean")
        if type(self.side_effects_performed) is not bool:
            raise TypeError("side_effects_performed must be an exact boolean")
        if self.canonical_source_unavailable:
            raise ValueError("composition cannot prove canonical source unavailability")
        if self.side_effects_performed:
            raise ValueError("route resolution must perform no side effects")
        if self.status is LessonReadRouteStatus.CONFIGURED_CANONICAL_READER and self.execute_read is None:
            raise ValueError("configured canonical reader requires execute_read")
        if self.status in {LessonReadRouteStatus.CURRENT_SURFACE_UNBOUND, LessonReadRouteStatus.GOVERNED_ROUTE_REQUIRED} and self.execute_read is not None:
            raise ValueError("unbound route cannot expose execute_read")


def resolve_lesson_read_route(
    *,
    data_source_id: str | None = None,
    adapter: NotionReadOnlyAdapter | None = None,
    governed_route_available: bool = False,
) -> LessonReadRouteResolution:
    """Resolve the canonical reader without conflating local binding and source state."""

    resolved_data_source_id = (
        data_source_id
        if data_source_id is not None
        else os.environ.get(LESSONS_LEARNED_DATA_SOURCE_ENV)
    )
    if not resolved_data_source_id or not resolved_data_source_id.strip():
        if governed_route_available:
            return LessonReadRouteResolution(
                status=LessonReadRouteStatus.GOVERNED_ROUTE_REQUIRED,
                execute_read=None,
                reason_code="governed-github-route-required",
            )
        return LessonReadRouteResolution(
            status=LessonReadRouteStatus.CURRENT_SURFACE_UNBOUND,
            execute_read=None,
            reason_code="connector-surface-unavailable",
        )

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

    return LessonReadRouteResolution(
        status=LessonReadRouteStatus.CONFIGURED_CANONICAL_READER,
        execute_read=execute_read,
        reason_code="configured-canonical-reader",
    )


def build_lesson_read_executor(
    *,
    data_source_id: str | None = None,
    adapter: NotionReadOnlyAdapter | None = None,
) -> ReadExecutor | None:
    """Compatibility wrapper returning only the canonical CKR11 read executor."""

    return resolve_lesson_read_route(
        data_source_id=data_source_id,
        adapter=adapter,
    ).execute_read


__all__ = [
    "LESSONS_LEARNED_DATA_SOURCE_ENV",
    "LessonReadRouteResolution",
    "LessonReadRouteStatus",
    "LessonReadUnavailableError",
    "build_lesson_read_executor",
    "resolve_lesson_read_route",
]
