from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest,
    RetrievalEscalation,
    SufficiencyStatus,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    LessonActivationError,
    LessonActivationSkip,
    build_filtered_query,
    build_known_reference_query,
    normalize_lesson_row,
    orchestrate_lesson_activation,
)
from agent_memory_context_manager.lesson_preflight import LessonRecordEvidence, LessonRetrievalStatus


def request(**overrides):
    data = dict(
        task_reference="issue:#1516",
        ecosystem_hints=("python",),
        capability_keywords=("testing",),
        target_path_hints=(),
        canonical_rule_refs=(),
        known_knowledge_refs=(),
        specialized_knowledge_required=None,
    )
    data.update(overrides)
    return CodingKnowledgeRequest(**data)


def _title(text):
    return {"type": "title", "title": [{"plain_text": text}]}


def _rich_text(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _multi_select(*names):
    return {"type": "multi_select", "multi_select": [{"name": name} for name in names]}


def _checkbox(value):
    return {"type": "checkbox", "checkbox": value}


def _url(value):
    return {"type": "url", "url": value}


def live_row(**overrides):
    properties = {
        "Lesson ID": _rich_text("LL-42"),
        "Lesson Learned": _title("Recheck currentness before routing"),
        "Status": _select("Applied"),
        "Surface Before Work?": _checkbox(True),
        "Area": _select("Testing"),
        "Applies To": _multi_select("Notion", "Curriculum"),
        "Learning Type": _select("Testing lesson"),
        "Source Link": _url("https://github.com/Blummer92/agent-os/blob/main/01_Shared_Standards/python/testing-standard.md"),
        "Guardrail": _rich_text("Never reuse stale evidence."),
        "What To Do Next Time": _rich_text("Reacquire evidence after head advances."),
    }
    properties.update(overrides.pop("properties", {}))
    row = {
        "object": "page",
        "id": "11111111-1111-1111-1111-111111111111",
        "url": "https://www.notion.so/lesson-page-abc123",
        "last_edited_time": "2026-08-30T12:00:00.000Z",
        "properties": properties,
    }
    row.update(overrides)
    return row


def test_normalize_real_shaped_live_row_is_deterministic():
    result = normalize_lesson_row(live_row())
    assert isinstance(result, LessonRecordEvidence)
    assert result.lesson_id == "LL-42"
    assert result.ecosystem == "python"
    assert result.capability_kind == "testing"
    assert result.status == "Applied"
    assert result.surface_before_work is True
    assert result.canonical_github_refs == (
        "https://github.com/Blummer92/agent-os/blob/main/01_Shared_Standards/python/testing-standard.md",
    )
    assert result.keywords == ("Notion", "Curriculum")


def test_status_semantics_are_consumed_and_archived_flag_follows_status():
    followup = normalize_lesson_row(live_row(properties={"Status": _select("Needs follow-up")}))
    assert isinstance(followup, LessonRecordEvidence)
    assert followup.status == "Needs follow-up"
    assert followup.archived is False

    archived = normalize_lesson_row(live_row(properties={"Status": _select("Archived note")}))
    assert isinstance(archived, LessonRecordEvidence)
    assert archived.archived is True


def test_missing_source_link_yields_unverifiable_not_current():
    result = normalize_lesson_row(live_row(properties={"Source Link": _url(None)}))
    assert isinstance(result, LessonRecordEvidence)
    assert result.canonical_github_refs == ()


def test_ambiguous_status_vocabulary_is_explicit_non_ready():
    result = normalize_lesson_row(live_row(properties={"Status": _select("Backlog")}))
    assert isinstance(result, LessonActivationSkip)
    assert result.reason == "ambiguous-status-vocabulary"


def test_ambiguous_area_vocabulary_is_explicit_non_ready():
    result = normalize_lesson_row(live_row(properties={"Area": _select("Marketing")}))
    assert isinstance(result, LessonActivationSkip)
    assert result.reason == "ambiguous-area-vocabulary"


def test_ambiguous_learning_type_vocabulary_is_explicit_non_ready():
    result = normalize_lesson_row(live_row(properties={"Learning Type": _select("Unclassified")}))
    assert isinstance(result, LessonActivationSkip)
    assert result.reason == "ambiguous-learning-type-vocabulary"


def test_missing_stable_identity_is_explicit_non_ready():
    result = normalize_lesson_row(live_row(properties={"Lesson ID": _rich_text("")}))
    assert isinstance(result, LessonActivationSkip)
    assert result.reason == "missing-stable-identity"


def test_malformed_row_is_rejected_without_raising():
    assert normalize_lesson_row("not-a-row").reason == "malformed-row"
    assert normalize_lesson_row({"object": "page"}).reason == "missing-properties"


def test_oversized_applies_to_collection_is_rejected():
    oversized = live_row(properties={"Applies To": _multi_select(*[f"tag-{i}" for i in range(25)])})
    result = normalize_lesson_row(oversized)
    assert isinstance(result, LessonActivationSkip)
    assert result.reason == "ambiguous-applies-to-vocabulary"


def test_not_needed_plan_performs_zero_read_executor_calls():
    calls = []
    req = request(
        ecosystem_hints=(),
        capability_keywords=(),
        target_path_hints=(),
        specialized_knowledge_required=False,
    )
    result = orchestrate_lesson_activation(req, execute_read=lambda query: calls.append(query))
    assert calls == []
    assert result.lesson_retrieval_status is LessonRetrievalStatus.NOT_NEEDED


def test_known_reference_is_attempted_before_filtered_query():
    calls = []
    req = request(known_knowledge_refs=("LL-42",))

    def executor(query):
        calls.append(query)
        return {"results": []}

    orchestrate_lesson_activation(req, execute_read=executor)
    assert len(calls) == 1
    assert calls[0] == build_known_reference_query(("LL-42",))
    assert {"property": "Lesson ID", "rich_text": {"equals": "LL-42"}} in calls[0]["filter"]["or"]


def test_filtered_query_is_bounded_before_ckr6():
    query = build_filtered_query(request())
    assert query["page_size"] <= 5
    assert set(query["filter_properties"]).issubset(
        {
            "Lesson ID",
            "Lesson Learned",
            "Status",
            "Surface Before Work?",
            "Area",
            "Applies To",
            "Learning Type",
            "Source Link",
            "Guardrail",
            "What To Do Next Time",
        }
    )


def test_more_than_five_returned_rows_fails_closed():
    rows = {"results": [live_row(id=f"row-{i}") for i in range(6)]}
    try:
        orchestrate_lesson_activation(request(), execute_read=lambda query: rows)
        assert False, "expected LessonActivationError"
    except LessonActivationError:
        pass


def test_lesson_without_provenance_cannot_reach_sufficient_despite_request_refs():
    req = request(canonical_rule_refs=("01_Shared_Standards/python/testing-standard.md",))
    row = live_row(properties={"Source Link": _url(None)})
    result = orchestrate_lesson_activation(req, execute_read=lambda query: {"results": [row]})
    assert result.lesson_retrieval_status is not LessonRetrievalStatus.SUFFICIENT
    assert "01_Shared_Standards/python/testing-standard.md" in result.handoff_projection["allowed_inspect_first"]


def test_current_provenance_valid_lesson_reaches_sufficient_and_projects_handoff():
    result = orchestrate_lesson_activation(request(), execute_read=lambda query: {"results": [live_row()]})
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-42",)
    assert result.handoff_projection["known_facts"]


def test_unverifiable_relevant_candidate_fails_closed_to_manual_review():
    row = live_row(properties={"Source Link": _url(None)})
    result = orchestrate_lesson_activation(request(), execute_read=lambda query: {"results": [row]})
    assert result.lesson_retrieval_status in (
        LessonRetrievalStatus.MANUAL_REVIEW,
        LessonRetrievalStatus.INSUFFICIENT,
    )


def test_retrieval_unavailable_preserves_safe_fallback():
    result = orchestrate_lesson_activation(request(), execute_read=None)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.UNAVAILABLE_SAFE_FALLBACK
    assert result.notion_write_performed is False
    assert result.github_write_performed is False
    assert result.authority_created is False


def test_no_write_schema_or_authority_side_effects_from_activation():
    result = orchestrate_lesson_activation(request(), execute_read=lambda query: {"results": [live_row()]})
    assert result.notion_write_performed is False
    assert result.github_write_performed is False
    assert result.authority_created is False
