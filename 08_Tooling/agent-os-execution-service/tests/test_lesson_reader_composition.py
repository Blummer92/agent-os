from __future__ import annotations

from pathlib import Path

import pytest
from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter

from agent_os_execution_service import lesson_reader_composition
from agent_os_execution_service.lesson_reader_composition import (
    GOVERNED_QUERY_FIELDS,
    LESSONS_LEARNED_DATA_SOURCE_ENV,
    NOTION_CONTENT_SOURCE_ENVS,
    LessonReadUnavailableError,
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


def test_every_supported_class_declares_its_own_distinct_source_env():
    env_names = list(NOTION_CONTENT_SOURCE_ENVS.values())
    assert len(set(env_names)) == len(env_names), (
        "two content classes share one source binding; they could borrow each "
        f"other's source authority: {env_names}"
    )


def test_each_content_class_reads_only_its_own_bound_source_identity(monkeypatch):
    # Distinct live-looking identities prove the class -> source mapping is real
    # rather than merely declared, so one class cannot read another's records.
    expected = {}
    for content_class, env_name in NOTION_CONTENT_SOURCE_ENVS.items():
        expected[content_class] = f"source-for-{content_class}"
        monkeypatch.setenv(env_name, expected[content_class])

    observed = {}
    for content_class in NOTION_CONTENT_SOURCE_ENVS:
        adapter = SpyNotionAdapter()
        reader = build_notion_read_executor(content_class=content_class, adapter=adapter)
        assert reader is not None
        reader({"page_size": 2})
        observed[content_class] = adapter.tasks[0].payload["data_source_id"]

    assert observed == expected
    assert len(set(observed.values())) == len(observed)


def test_whitespace_only_source_identity_fails_closed(monkeypatch):
    monkeypatch.setenv(NOTION_CONTENT_SOURCE_ENVS["curriculum-content"], "   ")
    assert build_notion_read_executor(content_class="curriculum-content") is None


@pytest.mark.parametrize("governed_field", sorted(GOVERNED_QUERY_FIELDS))
def test_query_cannot_override_governed_read_fields(governed_field):
    # Regression: the request used to be merged over the binding, so a caller
    # could re-point a typed read at another data source or swap the read action.
    adapter = SpyNotionAdapter()
    reader = build_notion_read_executor(
        content_class="curriculum-assets",
        data_source_id="asset-source",
        adapter=adapter,
    )
    assert reader is not None

    hostile = {"action": "query_database", "data_source_id": "lessons-source"}
    with pytest.raises(ValueError, match="governed read fields"):
        reader({"page_size": 2, governed_field: hostile[governed_field]})

    assert adapter.tasks == [], "a rejected query must never reach the adapter"


def test_bounded_limits_stay_enforced_by_the_existing_adapter(monkeypatch):
    # Bounds are owned by the canonical adapter; this proves the composition does
    # not bypass them and that an out-of-bounds read never reaches the network.
    calls = []

    def never_called(*args, **kwargs):
        calls.append(args)
        raise AssertionError("an out-of-bounds read must not reach Notion")

    adapter = NotionReadOnlyAdapter(
        token="test-token",
        http_post_query_data_source=never_called,
    )
    reader = build_notion_read_executor(
        content_class="lesson-planning",
        data_source_id="planning-source",
        adapter=adapter,
    )
    assert reader is not None

    with pytest.raises(LessonReadUnavailableError):
        reader({"page_size": 500})
    assert calls == []


def test_shared_read_only_adapter_exposes_no_write_action():
    actions = set(NotionReadOnlyAdapter.ACTIONS)
    assert actions, "the canonical adapter must declare its bounded action set"
    assert all(
        action.startswith(("get_", "query_")) for action in actions
    ), f"the shared Notion adapter gained a non-read action: {sorted(actions)}"


def test_adapter_failure_is_converted_to_fail_closed_unavailable():
    adapter = SpyNotionAdapter({"status": "failure", "message": "source not shared"})
    reader = build_lesson_read_executor(data_source_id="lessons-source", adapter=adapter)
    assert reader is not None
    with pytest.raises(LessonReadUnavailableError, match="source not shared"):
        reader({"page_size": 5})


def test_malformed_adapter_output_fails_closed():
    adapter = SpyNotionAdapter({"status": "success", "message": "ok", "output": "rows"})
    reader = build_lesson_read_executor(data_source_id="lessons-source", adapter=adapter)
    assert reader is not None
    with pytest.raises(LessonReadUnavailableError, match="malformed output"):
        reader({"page_size": 5})


def test_lessons_learned_wrapper_still_binds_the_lessons_learned_class(monkeypatch):
    monkeypatch.setenv(LESSONS_LEARNED_DATA_SOURCE_ENV, "lessons-env-source")
    adapter = SpyNotionAdapter()
    reader = build_lesson_read_executor(adapter=adapter)
    assert reader is not None
    reader({"page_size": 5})
    assert adapter.tasks[0].payload["data_source_id"] == "lessons-env-source"


def test_package_binds_exactly_one_notion_client_implementation():
    # #2282 must not introduce a second Notion client, reader, or source of truth.
    package = Path(lesson_reader_composition.__file__).parent
    modules = sorted(package.glob("*.py"))
    assert modules

    binding_modules = []
    for module in modules:
        source = module.read_text(encoding="utf-8")
        if "NotionReadOnlyAdapter" in source:
            binding_modules.append(module.name)
        for forbidden in ("api.notion.com", "NOTION_API_BASE", "notion_client"):
            assert forbidden not in source, (
                f"{module.name} reaches Notion outside the canonical adapter "
                f"via {forbidden!r}"
            )

    assert binding_modules == ["lesson_reader_composition.py"], (
        "exactly one module may bind the canonical #2141 Notion reader; "
        f"found {binding_modules}"
    )


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
