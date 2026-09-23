from __future__ import annotations

from agent_os_execution_service.issue_start_lesson_preflight import activate_issue_start_lesson_preflight


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
            "Applies To": {"type": "multi_select", "multi_select": [{"name": "automation"}]},
            "Learning Type": _select("Mistake"),
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/2065"},
            "Guardrail": _rich("No new repair hypothesis until relevant Lessons Learned have been checked."),
            "What To Do Next Time": _rich("Before the initial implementation or repair hypothesis, retrieve and consume the smallest relevant Lessons Learned set."),
        },
    }


def test_issue_start_preflight_consumes_relevant_lesson_before_hypothesis():
    calls = []
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=2247,
        task_reference="issue:#2247",
        capability_keywords=("automation", "repair", "lessons"),
        canonical_rule_refs=("https://github.com/Blummer92/agent-os/issues/2247",),
        specialized_knowledge_required=True,
        execute_read=lambda query: calls.append(query) or {"results": [_lesson()]},
    )
    assert calls
    assert result["lesson_retrieval_status"] == "sufficient"
    assert result["selected_lesson_ids"] == ["LL-63"]
    assert result["substantial_hypothesis_admissible"] is True
    assert result["handoff_projection"]["known_facts"]
    assert result["source_authority"] == "advisory-only"
    assert result["github_writes_authorized"] is False
    assert result["side_effects_performed"] is False


def test_not_needed_issue_start_performs_zero_notion_reads():
    calls = []
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=2247,
        task_reference="issue:#2247",
        specialized_knowledge_required=False,
        execute_read=lambda query: calls.append(query) or {"results": [_lesson()]},
    )
    assert calls == []
    assert result["lesson_retrieval_status"] == "not-needed"
    assert result["selected_lesson_ids"] == []
    assert result["substantial_hypothesis_admissible"] is True


def test_required_issue_start_lessons_fail_closed_when_reader_unavailable():
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os",
        issue_number=2247,
        task_reference="issue:#2247",
        specialized_knowledge_required=True,
        execute_read=None,
    )
    assert result["lesson_retrieval_status"] == "insufficient"
    assert result["substantial_hypothesis_admissible"] is False
    assert result["handoff_projection"]["stop_conditions"]
