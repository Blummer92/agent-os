"""Execution-surface routing for issue-start Lessons Learned retrieval (#2282).

This module selects between a host-supplied native ChatGPT Notion read executor
and the existing Agent OS production Lessons Learned reader from #2141. It does
not create a Notion client, selector, context packet, authority model, or write
capability.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .issue_start_lesson_preflight import activate_issue_start_lesson_preflight
from .lesson_reader_composition import LessonReadUnavailableError, build_lesson_read_executor

ReadExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]
FallbackFactory = Callable[[], ReadExecutor | None]


def activate_routed_issue_start_lesson_preflight(
    *,
    repository: str,
    issue_number: int,
    task_reference: str,
    native_notion_connector_available: bool,
    native_execute_read: ReadExecutor | None = None,
    fallback_factory: FallbackFactory = build_lesson_read_executor,
    ecosystem_hints: tuple[str, ...] = (),
    language_hints: tuple[str, ...] = (),
    library_hints: tuple[str, ...] = (),
    capability_keywords: tuple[str, ...] = (),
    target_path_hints: tuple[str, ...] = (),
    canonical_rule_refs: tuple[str, ...] = (),
    known_knowledge_refs: tuple[str, ...] = (),
    specialized_knowledge_required: bool | None = None,
) -> dict[str, object]:
    """Resolve CKR6 using native Notion when available, otherwise #2141.

    Fallback composition is lazy: when CKR6 resolves ``not-needed`` the
    fallback factory is never called. Native availability is explicit execution-
    surface capability evidence only and never grants repository or Notion write
    authority.
    """
    if type(native_notion_connector_available) is not bool:
        raise TypeError("native_notion_connector_available must be a built-in bool")

    fallback_state = "not-considered"
    fallback_invoked = False

    if native_notion_connector_available:
        selected_route = "native-notion-connector"
        execute_read = native_execute_read
    else:
        selected_route = "agent-os-lessons-reader"
        cached_executor: ReadExecutor | None | object = _UNSET

        def execute_read(query: Mapping[str, Any]) -> Mapping[str, Any]:
            nonlocal cached_executor, fallback_state, fallback_invoked
            fallback_invoked = True
            if cached_executor is _UNSET:
                cached_executor = fallback_factory()
            if cached_executor is None:
                fallback_state = "unavailable"
                raise LessonReadUnavailableError("Agent OS Lessons Learned fallback reader unavailable")
            fallback_state = "available"
            return cached_executor(query)

    result = activate_issue_start_lesson_preflight(
        repository=repository,
        issue_number=issue_number,
        task_reference=task_reference,
        ecosystem_hints=ecosystem_hints,
        language_hints=language_hints,
        library_hints=library_hints,
        capability_keywords=capability_keywords,
        target_path_hints=target_path_hints,
        canonical_rule_refs=canonical_rule_refs,
        known_knowledge_refs=known_knowledge_refs,
        specialized_knowledge_required=specialized_knowledge_required,
        execute_read=execute_read,
    )

    if result["lesson_retrieval_status"] == "not-needed":
        selected_route = "not-needed"
        fallback_state = "not-considered"
    elif native_notion_connector_available:
        fallback_state = "not-considered"

    return {
        **result,
        "native_notion_connector_available": native_notion_connector_available,
        "lesson_read_route": selected_route,
        "fallback_reader_state": fallback_state,
        "fallback_reader_invoked": fallback_invoked,
    }


_UNSET = object()

__all__ = ["activate_routed_issue_start_lesson_preflight"]
