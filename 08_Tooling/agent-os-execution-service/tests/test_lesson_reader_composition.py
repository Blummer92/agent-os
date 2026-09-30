from __future__ import annotations

import pytest

from agent_os_execution_service.lesson_reader_composition import (
    LESSONS_LEARNED_DATA_SOURCE_ENV,
    LessonReadRouteStatus,
    LessonReadUnavailableError,
    build_lesson_read_executor,
    resolve_lesson_read_route,
)


class SpyNotionAdapter:
    def __init__(self, result=None):
        self.tasks = []
        self.result = result or {
            "status": "success",
            "message": "ok",
            "output": {"results": [{"id": "lesson-1"}], "has_more": False},
        }

    def execute(self, task):
        self.tasks.append(task)
        return self.result


class RaisingNotionAdapter:
    """Adapter whose execute() raises instead of returning a result dict."""

    def __init__(self, exc):
        self.exc = exc
        self.tasks = []

    def execute(self, task):
        self.tasks.append(task)
        raise self.exc


def test_missing_data_source_identity_preserves_unavailable_fallback(monkeypatch):
    monkeypatch.delenv(LESSONS_LEARNED_DATA_SOURCE_ENV, raising=False)
    assert build_lesson_read_executor() is None


def test_missing_current_surface_binding_is_not_canonical_source_unavailability(monkeypatch):
    monkeypatch.delenv(LESSONS_LEARNED_DATA_SOURCE_ENV, raising=False)

    route = resolve_lesson_read_route()

    assert route.status is LessonReadRouteStatus.CURRENT_SURFACE_UNBOUND
    assert route.reason_code == "connector-surface-unavailable"
    assert route.execute_read is None
    assert route.canonical_source_unavailable is False
    assert route.side_effects_performed is False


def test_configured_canonical_reader_wins_without_native_plugin_state():
    adapter = SpyNotionAdapter()

    route = resolve_lesson_read_route(data_source_id="lessons-source", adapter=adapter)

    assert route.status is LessonReadRouteStatus.CONFIGURED_CANONICAL_READER
    assert route.reason_code == "configured-canonical-reader"
    assert route.execute_read is not None
    assert route.canonical_source_unavailable is False
    assert route.side_effects_performed is False


def test_production_reader_preserves_bounded_query_for_existing_adapter():
    adapter = SpyNotionAdapter()
    reader = build_lesson_read_executor(data_source_id="lessons-source", adapter=adapter)
    assert reader is not None

    query = {
        "page_size": 25,
        "filter_properties": ["Lesson ID", "Status"],
        "filter": {"and": [{"property": "Surface Before Work?", "checkbox": {"equals": True}}]},
    }
    result = reader(query)

    assert result["results"] == [{"id": "lesson-1"}]
    assert len(adapter.tasks) == 1
    payload = adapter.tasks[0].payload
    assert payload["action"] == "query_data_source"
    assert payload["data_source_id"] == "lessons-source"
    assert payload["page_size"] == 25
    assert payload["max_results"] == 25
    assert payload["max_pages"] == 1
    assert payload["filter_properties"] == ["Lesson ID", "Status"]
    assert payload["filter"] == query["filter"]


def test_production_reader_uses_read_only_query_action_only():
    adapter = SpyNotionAdapter()
    reader = build_lesson_read_executor(data_source_id="lessons-source", adapter=adapter)
    assert reader is not None
    reader({"page_size": 5, "filter": {"and": []}})

    assert [task.action for task in adapter.tasks] == ["query_data_source"]
    assert [task.type for task in adapter.tasks] == ["read"]
    assert all(task.payload["action"] == "query_data_source" for task in adapter.tasks)


def test_missing_local_binding_resolves_governed_github_route_before_fallback(monkeypatch):
    monkeypatch.delenv(LESSONS_LEARNED_DATA_SOURCE_ENV, raising=False)

    route = resolve_lesson_read_route(governed_route_available=True)

    assert route.status is LessonReadRouteStatus.GOVERNED_ROUTE_REQUIRED
    assert route.reason_code == "governed-github-route-required"
    assert route.execute_read is None
    assert route.canonical_source_unavailable is False
    assert route.side_effects_performed is False


def test_provider_http_failure_is_projected_as_finite_sanitized_reason():
    adapter = SpyNotionAdapter(
        result={
            "status": "failure",
            "message": "Notion API returned HTTP 400: Bad Request secret=must-not-leak",
        }
    )
    reader = build_lesson_read_executor(data_source_id="lessons-source", adapter=adapter)
    assert reader is not None

    with pytest.raises(LessonReadUnavailableError) as exc_info:
        reader({"page_size": 5, "filter": {"and": []}})

    assert str(exc_info.value) == "notion-http-400"
    assert "secret" not in str(exc_info.value)


def test_malformed_success_output_uses_bounded_failure_reason():
    adapter = SpyNotionAdapter(result={"status": "success", "message": "ok", "output": []})
    reader = build_lesson_read_executor(data_source_id="lessons-source", adapter=adapter)
    assert reader is not None

    with pytest.raises(LessonReadUnavailableError, match="^notion-malformed-output$"):
        reader({"page_size": 5, "filter": {"and": []}})


def test_raised_provider_http_failure_is_projected_as_finite_sanitized_reason():
    # #3032: a provider failure raised by the adapter (rather than returned as a
    # non-success result) must still project the exact provider cause instead of
    # collapsing to a generic runtime error downstream.
    adapter = RaisingNotionAdapter(
        RuntimeError("Notion API returned HTTP 403: Forbidden")
    )
    reader = build_lesson_read_executor(data_source_id="lessons-source", adapter=adapter)
    assert reader is not None

    with pytest.raises(LessonReadUnavailableError) as exc_info:
        reader({"page_size": 5, "filter": {"and": []}})

    assert str(exc_info.value) == "notion-http-403"
    assert len(adapter.tasks) == 1


def test_raised_provider_connection_failure_is_projected_as_finite_reason():
    adapter = RaisingNotionAdapter(
        RuntimeError("Notion API connection error: dial tcp: connection refused")
    )
    reader = build_lesson_read_executor(data_source_id="lessons-source", adapter=adapter)
    assert reader is not None

    with pytest.raises(LessonReadUnavailableError, match="^notion-connection-error$"):
        reader({"page_size": 5})


def test_raised_timeout_propagates_unchanged_for_orchestrator_mapping():
    # TimeoutError keeps its class so the orchestrator can project the
    # dedicated lesson-read-timeout reason; the composition must not swallow it.
    adapter = RaisingNotionAdapter(TimeoutError("request timed out"))
    reader = build_lesson_read_executor(data_source_id="lessons-source", adapter=adapter)
    assert reader is not None

    with pytest.raises(TimeoutError, match="^request timed out$"):
        reader({"page_size": 5})


def test_raised_non_provider_error_propagates_unchanged():
    # Failures with no provider signature keep their existing handling; the
    # composition must neither sanitize them nor invent a provider cause.
    adapter = RaisingNotionAdapter(RuntimeError("unexpected-adapter-bug"))
    reader = build_lesson_read_executor(data_source_id="lessons-source", adapter=adapter)
    assert reader is not None

    with pytest.raises(RuntimeError) as exc_info:
        reader({"page_size": 5})

    assert str(exc_info.value) == "unexpected-adapter-bug"
    assert not isinstance(exc_info.value, LessonReadUnavailableError)
