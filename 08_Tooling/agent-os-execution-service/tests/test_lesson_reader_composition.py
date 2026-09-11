from __future__ import annotations

from agent_os_execution_service.lesson_reader_composition import (
    LESSONS_LEARNED_DATA_SOURCE_ENV,
    NOTION_CONTENT_SOURCE_ENVS,
    build_lesson_read_executor,
    build_notion_read_executor,
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


def test_supported_curriculum_classes_use_distinct_runtime_bindings(monkeypatch):
    for content_class, env_name in NOTION_CONTENT_SOURCE_ENVS.items():
        monkeypatch.delenv(env_name, raising=False)
        assert build_notion_read_executor(content_class=content_class) is None


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


def test_curriculum_asset_reader_reuses_same_read_only_adapter_contract():
    adapter = SpyNotionAdapter()
    reader = build_notion_read_executor(
        content_class="curriculum-assets",
        data_source_id="asset-source",
        adapter=adapter,
    )
    assert reader is not None
    reader({"page_size": 4})
    assert adapter.tasks[0].payload["data_source_id"] == "asset-source"
    assert adapter.tasks[0].action == "query_data_source"
    assert adapter.tasks[0].type == "read"


def test_production_reader_uses_read_only_query_action_only():
    adapter = SpyNotionAdapter()
    reader = build_lesson_read_executor(data_source_id="lessons-source", adapter=adapter)
    assert reader is not None
    reader({"page_size": 5, "filter": {"and": []}})

    assert [task.action for task in adapter.tasks] == ["query_data_source"]
    assert [task.type for task in adapter.tasks] == ["read"]
    assert all(task.payload["action"] == "query_data_source" for task in adapter.tasks)
