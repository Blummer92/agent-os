from __future__ import annotations

from agent_os_execution_service.lesson_execution_surface_router import (
    activate_routed_issue_start_lesson_preflight,
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
            "Applies To": {"type": "multi_select", "multi_select": [{"name": "Notion"}]},
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
    assert result["lesson_retrieval_status"] == "sufficient"
    assert result["selected_lesson_ids"] == ["LL-63"]


def test_native_connector_unavailable_selects_existing_fallback_factory():
    fallback_calls = []
    read_calls = []

    def factory():
        fallback_calls.append("built")
        return lambda query: read_calls.append(query) or {"results": [_lesson()]}

    result = _required(
        native_notion_connector_available=False,
        fallback_factory=factory,
    )
    assert fallback_calls == ["built"]
    assert read_calls
    assert result["lesson_read_route"] == "agent-os-lessons-reader"
    assert result["fallback_reader_state"] == "available"
    assert result["lesson_retrieval_status"] == "sufficient"


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
    assert result["lesson_retrieval_status"] == "not-needed"


def test_fallback_unavailable_preserves_ckr6_capability_disposition():
    result = _required(
        native_notion_connector_available=False,
        fallback_factory=lambda: None,
    )
    assert result["fallback_reader_state"] == "unavailable"
    assert result["lesson_retrieval_status"] == "insufficient"
    assert result["substantial_hypothesis_admissible"] is False
    assert result["handoff_projection"]["stop_conditions"]


def test_fallback_runtime_failure_reports_reader_unavailable():
    def failing_reader(_query):
        raise TimeoutError("Notion read timed out")

    result = _required(
        native_notion_connector_available=False,
        fallback_factory=lambda: failing_reader,
    )
    assert result["fallback_reader_invoked"] is True
    assert result["fallback_reader_state"] == "unavailable"
    assert result["lesson_retrieval_status"] == "insufficient"
    assert result["substantial_hypothesis_admissible"] is False


def test_native_and_fallback_routes_return_equivalent_ckr6_evidence():
    reader = lambda _query: {"results": [_lesson()]}
    native = _required(
        native_notion_connector_available=True,
        native_execute_read=reader,
    )
    fallback = _required(
        native_notion_connector_available=False,
        fallback_factory=lambda: reader,
    )
    for key in (
        "lesson_retrieval_status",
        "selected_lesson_ids",
        "selection_reason_codes",
        "canonical_github_refs",
        "knowledge_refs",
        "handoff_projection",
        "substantial_hypothesis_admissible",
        "source_authority",
    ):
        assert native[key] == fallback[key]
    assert native["github_writes_authorized"] is False
    assert fallback["github_writes_authorized"] is False
    assert native["side_effects_performed"] is False
    assert fallback["side_effects_performed"] is False
