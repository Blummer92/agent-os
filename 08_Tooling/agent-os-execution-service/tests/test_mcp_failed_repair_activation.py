from __future__ import annotations

from agent_os_execution_service.mcp_facade import activate_agent_os_failed_repair


def _title(text):
    return {"type": "title", "title": [{"plain_text": text}]}


def _rich(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _lesson():
    return {
        "object": "page",
        "url": "https://www.notion.so/lesson-51",
        "last_edited_time": "2026-09-06T22:00:00Z",
        "properties": {
            "Lesson ID": _rich("LL-51"),
            "Lesson Learned": _title("Failed repairs must re-enter CKR6"),
            "Status": _select("Applied"),
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": _select("Testing"),
            "Applies To": {"type": "multi_select", "multi_select": [{"name": "Notion"}]},
            "Learning Type": _select("Testing lesson"),
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/1362"},
            "Guardrail": _rich("Do not mutate before retry-specific CKR6 re-entry."),
            "What To Do Next Time": _rich("Preserve the failed attempt and consume CKR6 before continuing."),
        },
    }


def _call(**overrides):
    data = dict(
        repository="Blummer92/agent-os",
        issue_number=1986,
        attempt_id="pr-1987-head-79c77bf-validation-34053652613",
        failed_hypothesis="current PR head should pass aggregate validation",
        result_summary="Validation Gate remained red and the first diagnostic surface was insufficient",
        task_reference="pr:#1987",
        ecosystem_hints=("python",),
        capability_keywords=("testing", "repair", "ci"),
        canonical_rule_refs=("https://github.com/Blummer92/agent-os/issues/1988",),
    )
    data.update(overrides)
    return activate_agent_os_failed_repair(**data)


def test_chatgpt_facade_executes_ckr6_and_returns_mutation_gate():
    calls = []
    result = _call(execute_read=lambda query: calls.append(query) or {"results": [_lesson()]})
    assert len(calls) == 1
    assert result["attempt_id"] == "pr-1987-head-79c77bf-validation-34053652613"
    assert result["retry_reentry_outcome"] == "consumed"
    assert result["lesson_retrieval_status"] == "sufficient"
    assert result["selected_lesson_ids"] == ["LL-51"]
    assert result["mutation_admissible"] is True
    assert result["github_writes_authorized"] is False
    assert result["side_effects_performed"] is False


def test_chatgpt_facade_fails_closed_when_material_lessons_cannot_be_read():
    result = _call(execute_read=None)
    assert result["retry_reentry_outcome"] == "unavailable-or-failed"
    assert result["lesson_retrieval_status"] == "insufficient"
    assert result["mutation_admissible"] is False
    assert result["blocking_attempt_id"] == "pr-1987-head-79c77bf-validation-34053652613"


def _raise_unavailable(_query):
    raise RuntimeError("the CKR6 runtime seam is absent on this surface")


def test_capability_unavailable_is_distinguishable_from_no_relevant_lesson():
    """#2142: capability outages must not reach #2281 as semantic repair recurrence."""
    capability = _call(specialized_knowledge_required=True, execute_read=_raise_unavailable)
    semantic = _call(specialized_knowledge_required=True, execute_read=lambda _query: {"results": []})

    # The coarse retry outcome stays identical for admission compatibility.
    assert capability["retry_reentry_outcome"] == semantic["retry_reentry_outcome"] == "unavailable-or-failed"
    assert capability["mutation_admissible"] is semantic["mutation_admissible"] is False

    # The exact disposition crosses the boundary, so the payloads differ.
    assert capability["lesson_disposition"] == "capability-unavailable"
    assert semantic["lesson_disposition"] == "no-relevant-lesson"
    assert capability != semantic


def test_consumed_disposition_crosses_the_facade_boundary():
    result = _call(execute_read=lambda _query: {"results": [_lesson()]})
    assert result["lesson_disposition"] == "consumed"
    assert result["retry_reentry_outcome"] == "consumed"


def test_each_new_failed_attempt_requires_its_own_runtime_activation():
    read = lambda _: {"results": [_lesson()]}
    first = _call(execute_read=read)
    second = _call(attempt_id="pr-1987-head-next-validation-next", execute_read=read)
    assert first["attempt_id"] != second["attempt_id"]
    assert first["retry_reentry_outcome"] == "consumed"
    assert second["retry_reentry_outcome"] == "consumed"
    assert first["mutation_admissible"] is True
    assert second["mutation_admissible"] is True
