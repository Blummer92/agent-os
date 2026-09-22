from __future__ import annotations

from agent_os_execution_service.lesson_reader_composition import (
    LESSONS_LEARNED_DATA_SOURCE_ENV,
    LessonReadRouteStatus,
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
