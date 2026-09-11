from __future__ import annotations

from agent_os_execution_service.lesson_execution_surface_router import (
    activate_routed_issue_start_lesson_preflight,
    execute_routed_notion_read,
)


def _title(text):
    return {"type": "title", "title": [{"plain_text": text}]}


def _rich(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _lesson():
    return {
        "object": "page",
        "url": "https://www.notion.so/lesson-63",
        "last_edited_time": "2026-09-09T20:09:14Z",
        "properties": {
            "Lesson ID": _rich("LL-63"),
            "Lesson Learned": _title("Lessons Learned preflight is mandatory before each new repair hypothesis, not optional context"),
            "Status": _select("Applied"),
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": _select("Automation"),
            "Applies To": {"type": "multi_select", "multi_select": [{"name": "Notion"}, {"name": "Automation"}]},
            "Learning Type": _select("Mistake"),
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/2065"},
            "Guardrail": _rich("Check relevant Lessons Learned before a new repair hypothesis."),
            "What To Do Next Time": _rich("Retrieve and consume the smallest relevant Lessons Learned set."),
        },
    }


def _required(**overrides):
    args = dict(
        repository="Blummer92/agent-os",
        issue_number=2282,
        task_reference="issue:#2282",
        capability_keywords=("automation", "repair", "lessons"),
        canonical_rule_refs=("https://github.com/Blummer92/agent-os/issues/2282",),
        specialized_knowledge_required=True,
    )
    args.update(overrides)
    return activate_routed_issue_start_lesson_preflight(**args)


def test_native_connector_available_does_not_force_fallback():
    native_calls = []
    fallback_calls = []
    result = _required(
        native_notion_connector_available=True,
        native_execute_read=lambda query: native_calls.append(query) or {"results": [_lesson()]},
        fallback_factory=lambda: fallback_calls.append("built") or None,
    )
    assert native_calls
    assert fallback_calls == []
    assert result["lesson_read_route"] == "native-notion-connector"
    assert result["content_class"] == "lessons-learned"
    assert result["lesson_retrieval_status"] == "sufficient"


def test_native_connector_unavailable_selects_existing_fallback_factory():
    fallback_calls = []
    read_calls = []

    def factory():
        fallback_calls.append("built")
        return lambda query: read_calls.append(query) or {"results": [_lesson()]}

    result = _required(native_notion_connector_available=False, fallback_factory=factory)
    assert fallback_calls == ["built"]
    assert read_calls
    assert result["lesson_read_route"] == "agent-os-notion-reader"
    assert result["fallback_reader_state"] == "available"


def test_not_needed_performs_zero_native_and_fallback_reads():
    native_calls = []
    fallback_calls = []
    result = activate_routed_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=2282,
        task_reference="issue:#2282",
        native_notion_connector_available=False,
        native_execute_read=lambda query: native_calls.append(query) or {"results": [_lesson()]},
        fallback_factory=lambda: fallback_calls.append("built") or None,
        specialized_knowledge_required=False,
    )
    assert native_calls == []
    assert fallback_calls == []
    assert result["lesson_read_route"] == "not-needed"


def test_fallback_unavailable_preserves_ckr6_capability_disposition():
    result = _required(native_notion_connector_available=False, fallback_factory=lambda: None)
    assert result["fallback_reader_state"] == "unavailable"
    assert result["lesson_retrieval_status"] == "insufficient"
    assert result["substantial_hypothesis_admissible"] is False


def test_curriculum_asset_read_preserves_typed_source_class():
    row = {"id": "asset-1", "name": "rule-of-thirds-example"}
    result = execute_routed_notion_read(
        content_class="curriculum-assets",
        query={"page_size": 3},
        native_notion_connector_available=False,
        fallback_factory=lambda: (lambda _query: {"results": [row]}),
    )
    assert result["content_class"] == "curriculum-assets"
    assert result["read_route"] == "agent-os-notion-reader"
    assert result["retrieval_status"] == "sufficient"
    assert result["results"] == [row]
    assert result["source_authority"] == "preserve-source-contract"
    assert result["github_writes_authorized"] is False
    assert result["side_effects_performed"] is False


def test_curriculum_content_native_and_fallback_routes_are_semantically_equivalent():
    row = {"id": "content-1", "title": "Photography Foundations"}
    reader = lambda _query: {"results": [row]}
    native = execute_routed_notion_read(
        content_class="curriculum-content",
        query={"page_size": 5},
        native_notion_connector_available=True,
        native_execute_read=reader,
    )
    fallback = execute_routed_notion_read(
        content_class="curriculum-content",
        query={"page_size": 5},
        native_notion_connector_available=False,
        fallback_factory=lambda: reader,
    )
    for key in ("content_class", "retrieval_status", "results", "source_authority"):
        assert native[key] == fallback[key]


def test_lesson_planning_unbound_fallback_fails_closed_without_guessing_source():
    result = execute_routed_notion_read(
        content_class="lesson-planning",
        query={"page_size": 5},
        native_notion_connector_available=False,
        fallback_factory=lambda: None,
    )
    assert result["retrieval_status"] == "unavailable"
    assert result["results"] == []


def test_unsupported_content_class_is_rejected():
    try:
        execute_routed_notion_read(
            content_class="everything-in-notion",
            query={},
            native_notion_connector_available=False,
            fallback_factory=lambda: None,
        )
    except ValueError as exc:
        assert "unsupported Notion content class" in str(exc)
    else:
        raise AssertionError("unsupported content class must fail closed")
