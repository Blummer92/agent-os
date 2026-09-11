"""Execution-surface routing for bounded Agent OS Notion reads (#2282).

The router preserves the existing CKR Lessons Learned path while also exposing a
typed read seam for curriculum assets, curriculum content/working knowledge, and
lesson-planning context. It reuses the canonical #2141 Scheduler-backed reader
and creates no second Notion client, selector, cache, mirror, or authority model.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .issue_start_lesson_preflight import activate_issue_start_lesson_preflight
from .lesson_reader_composition import (
    LessonReadUnavailableError,
    build_lesson_read_executor,
    build_notion_read_executor,
)

ReadExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]
FallbackFactory = Callable[[], ReadExecutor | None]
SUPPORTED_NOTION_CONTENT_CLASSES = frozenset(
    {"curriculum-assets", "curriculum-content", "lesson-planning", "lessons-learned"}
)


def execute_routed_notion_read(
    *,
    content_class: str,
    query: Mapping[str, Any],
    native_notion_connector_available: bool,
    native_execute_read: ReadExecutor | None = None,
    fallback_factory: FallbackFactory | None = None,
) -> dict[str, object]:
    """Execute one bounded typed Notion read through native or existing fallback.

    This function does not decide source authority. It preserves the requested
    content class in the result so downstream callers can apply the existing
    source-specific provenance/safe-use contract instead of treating every
    Notion record as interchangeable.
    """
    if content_class not in SUPPORTED_NOTION_CONTENT_CLASSES:
        raise ValueError(f"unsupported Notion content class: {content_class}")
    if type(native_notion_connector_available) is not bool:
        raise TypeError("native_notion_connector_available must be a built-in bool")
    if not isinstance(query, Mapping):
        raise TypeError("query must be a mapping")

    if native_notion_connector_available:
        if native_execute_read is None:
            return {
                "content_class": content_class,
                "read_route": "native-notion-connector",
                "retrieval_status": "unavailable",
                "results": [],
                "source_authority": "preserve-source-contract",
                "github_writes_authorized": False,
                "side_effects_performed": False,
            }
        executor = native_execute_read
        route = "native-notion-connector"
    else:
        factory = fallback_factory or (
            lambda: build_notion_read_executor(content_class=content_class)
        )
        executor = factory()
        route = "agent-os-notion-reader"
        if executor is None:
            return {
                "content_class": content_class,
                "read_route": route,
                "retrieval_status": "unavailable",
                "results": [],
                "source_authority": "preserve-source-contract",
                "github_writes_authorized": False,
                "side_effects_performed": False,
            }

    try:
        output = executor(query)
    except (ConnectionError, TimeoutError, RuntimeError):
        return {
            "content_class": content_class,
            "read_route": route,
            "retrieval_status": "unavailable",
            "results": [],
            "source_authority": "preserve-source-contract",
            "github_writes_authorized": False,
            "side_effects_performed": False,
        }

    results = output.get("results", []) if isinstance(output, Mapping) else []
    return {
        "content_class": content_class,
        "read_route": route,
        "retrieval_status": "sufficient" if results else "no-results",
        "results": results,
        "source_authority": "preserve-source-contract",
        "github_writes_authorized": False,
        "side_effects_performed": False,
    }


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
    """Resolve CKR6 Lessons Learned using native Notion or the #2141 fallback."""
    if type(native_notion_connector_available) is not bool:
        raise TypeError("native_notion_connector_available must be a built-in bool")

    fallback_state = "not-considered"
    fallback_invoked = False

    if native_notion_connector_available:
        selected_route = "native-notion-connector"
        execute_read = native_execute_read
    else:
        selected_route = "agent-os-notion-reader"
        cached_executor: ReadExecutor | None | object = _UNSET

        def execute_read(query: Mapping[str, Any]) -> Mapping[str, Any]:
            nonlocal cached_executor, fallback_state, fallback_invoked
            fallback_invoked = True
            if cached_executor is _UNSET:
                cached_executor = fallback_factory()
            if cached_executor is None:
                fallback_state = "unavailable"
                raise LessonReadUnavailableError("Agent OS Lessons Learned fallback reader unavailable")
            try:
                output = cached_executor(query)
            except (ConnectionError, TimeoutError, RuntimeError):
                fallback_state = "unavailable"
                raise
            fallback_state = "available"
            return output

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
        "content_class": "lessons-learned",
        "native_notion_connector_available": native_notion_connector_available,
        "lesson_read_route": selected_route,
        "fallback_reader_state": fallback_state,
        "fallback_reader_invoked": fallback_invoked,
    }


_UNSET = object()

__all__ = [
    "SUPPORTED_NOTION_CONTENT_CLASSES",
    "activate_routed_issue_start_lesson_preflight",
    "execute_routed_notion_read",
]
