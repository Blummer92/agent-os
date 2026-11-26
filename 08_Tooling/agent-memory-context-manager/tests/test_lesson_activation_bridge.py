from copy import deepcopy

import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    MAX_GUIDANCE_TEXT_CHARS,
    CodingKnowledgeRequest,
    KnowledgeCurrentness,
    RetrievalEscalation,
    SufficiencyStatus,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    MAX_RETRIEVAL_ROWS,
    MAX_SUPPORTING_REFS,
    MAX_ROW_LIST_ITEMS,
    MAX_ROW_TEXT_CHARS,
    LessonActivationSkip,
    LessonActivationError,
    _bound_relevant_lessons_with_order,
    build_filtered_query,
    build_known_reference_query,
    known_lesson_numbers,
    normalize_lesson_row,
    orchestrate_lesson_activation,
)
from agent_memory_context_manager.lesson_preflight import (
    LessonRecordEvidence, LessonRetrievalStatus, consume_lesson_preflight,
)
from agent_memory_context_manager.lesson_retrieval_orchestrator import orchestrate_lesson_retrieval


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
        return {"results": [], "has_more": False}

    orchestrate_lesson_activation(req, execute_read=executor)
    assert len(calls) == 1
    assert calls[0] == build_known_reference_query(("LL-42",))
    assert "filter_properties" not in calls[0]
    assert {"property": "Lesson ID", "unique_id": {"equals": 42}} in calls[0]["filter"]["or"]


def test_filtered_query_uses_request_relevance_signals():
    testing_query = build_filtered_query(request(ecosystem_hints=("python",), capability_keywords=("testing",)))
    deployment_query = build_filtered_query(request(ecosystem_hints=("agent-os",), capability_keywords=("deployment",)))
    assert testing_query != deployment_query
    assert testing_query["page_size"] == MAX_RETRIEVAL_ROWS
    assert "filter_properties" not in testing_query
    assert "filter_properties" not in deployment_query
    assert {"property": "Learning Type", "select": {"equals": "Testing lesson"}} in testing_query["filter"]["and"][-1]["or"]
    assert {"property": "Learning Type", "select": {"equals": "Deployment lesson"}} in deployment_query["filter"]["and"][-1]["or"]


def test_unmapped_vocabulary_keeps_existing_bounded_query_without_guessing():
    query = build_filtered_query(
        request(ecosystem_hints=("unmapped-runtime",), capability_keywords=(), target_path_hints=())
    )
    assert query["page_size"] == 5
    assert len(query["filter"]["and"]) == 2


def test_over_budget_retrieval_is_deterministically_narrowed_before_ckr2():
    rows = []
    for index in range(24):
        rows.append(
            live_row(
                id=f"row-{index}",
                properties={
                    "Lesson ID": _rich_text(f"LL-{index:02d}"),
                    "Area": _select("Automation"),
                    "Learning Type": _select("Trigger lesson"),
                    "Applies To": _multi_select("scheduling"),
                },
            )
        )
    rows.append(
        live_row(
            id="row-relevant",
            properties={
                "Lesson ID": _rich_text("LL-RELEVANT"),
                "Area": _select("Testing"),
                "Learning Type": _select("Testing lesson"),
                "Applies To": _multi_select("testing"),
            },
        )
    )
    result = orchestrate_lesson_activation(
        request(ecosystem_hints=("python",), capability_keywords=("testing",)),
        execute_read=lambda query: {"results": rows, "has_more": False},
    )
    assert result.candidate_count <= 5
    assert "LL-RELEVANT" in result.selected_lesson_ids


def test_lesson_without_provenance_cannot_reach_sufficient_despite_request_refs():
    req = request(canonical_rule_refs=("01_Shared_Standards/python/testing-standard.md",))
    row = live_row(properties={"Source Link": _url(None)})
    result = orchestrate_lesson_activation(req, execute_read=lambda query: {"results": [row], "has_more": False})
    assert result.lesson_retrieval_status is not LessonRetrievalStatus.SUFFICIENT
    assert "01_Shared_Standards/python/testing-standard.md" in result.handoff_projection["allowed_inspect_first"]


def test_current_provenance_valid_lesson_reaches_sufficient_and_projects_handoff():
    result = orchestrate_lesson_activation(request(), execute_read=lambda query: {"results": [live_row()], "has_more": False})
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-42",)
    assert result.handoff_projection["known_facts"]


def test_surface_before_work_false_survives_normalization_and_blocks_selection():
    # Known-reference reads carry no Surface filter, so the normalized flag is the gate (#3417 D1).
    row = live_row(properties={"Surface Before Work?": _checkbox(False)})
    before = deepcopy(row)
    assert normalize_lesson_row(row).surface_before_work is False
    result = orchestrate_lesson_activation(request(known_knowledge_refs=("LL-42",)), execute_read=lambda query: {"results": [row], "has_more": False})
    assert result.selected_lesson_ids == ()
    assert row == before  # normalization never mutates the live row


def test_unverifiable_relevant_candidate_fails_closed_to_manual_review():
    row = live_row(properties={"Source Link": _url(None)})
    result = orchestrate_lesson_activation(request(), execute_read=lambda query: {"results": [row], "has_more": False})
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
    result = orchestrate_lesson_activation(request(), execute_read=lambda query: {"results": [live_row()], "has_more": False})
    assert result.notion_write_performed is False
    assert result.github_write_performed is False
    assert result.authority_created is False


# --- CKR6 PR-A (R1 selector dedup / candidate-budget repair, #2425) ---
# A01/A02/A06/A07/A08/A09 from PR_A_TEST_MATRIX.csv. Written fail-first:
# A01 and A06 fail on the pre-repair record-counted bound; A02/A07/A08/A09
# pin behavior that must not change across the repair.


def test_pr_a01_bound_counts_distinct_ids_not_records():
    # Five bound slots are five DISTINCT lesson IDs. Ten rows that are five
    # identical pairs must bound to five distinct IDs, not to the first five
    # records (which cover only three distinct IDs).
    rows = []
    for index in range(1, 6):
        row = live_row(properties={"Lesson ID": _rich_text(f"LL-0{index}")})
        rows.append(row)
        rows.append(row)  # identical duplicate of the same provider row
    lessons = [normalize_lesson_row(row) for row in rows]
    assert all(isinstance(item, LessonRecordEvidence) for item in lessons)
    bounded, _ = _bound_relevant_lessons_with_order(request(), lessons)
    assert {item.lesson_id for item in bounded} == {
        "LL-01",
        "LL-02",
        "LL-03",
        "LL-04",
        "LL-05",
    }


def test_pr_a02_original_canary_stays_insufficient_after_repair():
    # The 2026-11-11 canary request matches no lesson in the finite
    # vocabulary; the dedup/budget repair must not manufacture a match.
    req = request(
        task_reference="issue:#2425 ckr6-p1-host-enforcement-20261111",
        ecosystem_hints=("agent-os", "ckr6"),
        capability_keywords=("ckr6", "lesson-preflight", "host-enforcement", "issue-start"),
        canonical_rule_refs=("#2425", "#2851", "#3559"),
        specialized_knowledge_required=True,
    )
    result = orchestrate_lesson_activation(
        req, execute_read=lambda query: {"results": [live_row()], "has_more": False}
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert "no-relevant-candidate" in result.selection_reason_codes
    assert result.selected_lesson_ids == ()


def test_pr_a06_bound_edge_conflict_preserved_and_reported():
    # A conflicting identity at the bound edge must enter the bound with ALL
    # its records, so the duplicate-identity-conflict is reported instead of
    # being silently dropped with the second revision.
    rows = []
    for index in range(1, 5):
        rows.append(live_row(properties={"Lesson ID": _rich_text(f"LL-0{index}")}))
    conflict_a = live_row(
        properties={"Lesson ID": _rich_text("LL-05")},
        last_edited_time="2026-11-04T12:00:00.000Z",
    )
    conflict_b = live_row(
        properties={
            "Lesson ID": _rich_text("LL-05"),
            "Guardrail": _rich_text("A different guardrail for the same lesson."),
        },
        last_edited_time="2026-11-05T12:00:00.000Z",
    )
    rows.extend([conflict_a, conflict_b])
    lessons = [normalize_lesson_row(row) for row in rows]
    assert all(isinstance(item, LessonRecordEvidence) for item in lessons)
    bounded, _ = _bound_relevant_lessons_with_order(request(), lessons)
    ll05 = [item for item in bounded if item.lesson_id == "LL-05"]
    assert len(ll05) == 2  # both conflicting revisions enter the bound
    assert {item.source_revision for item in ll05} == {
        "2026-11-04T12:00:00.000Z",
        "2026-11-05T12:00:00.000Z",
    }
    # End to end: the conflict must surface as manual review, not a silent pass.
    result = orchestrate_lesson_activation(
        request(), execute_read=lambda query: {"results": rows, "has_more": False}
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert "duplicate-identity-conflict" in result.selection_reason_codes


def test_pr_a07_single_query_path_matches_orchestrator_identity_behavior():
    # Identical duplicates collapse and conflicting identities fail closed
    # through orchestrate_lesson_activation's single-query path too.
    identical = live_row()
    result = orchestrate_lesson_activation(
        request(), execute_read=lambda query: {"results": [identical, identical], "has_more": False}
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-42",)
    assert result.selected_count == 1
    assert result.candidate_count == 2  # raw count preserved

    conflict_a = live_row(last_edited_time="2026-11-04T12:00:00.000Z")
    conflict_b = live_row(
        properties={"Guardrail": _rich_text("A different guardrail.")},
        last_edited_time="2026-11-05T12:00:00.000Z",
    )
    result = orchestrate_lesson_activation(
        request(), execute_read=lambda query: {"results": [conflict_a, conflict_b], "has_more": False}
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert "duplicate-identity-conflict" in result.selection_reason_codes


def test_pr_a08_unrelated_request_selects_nothing():
    # An unrelated request (deployment hints against testing lessons)
    # selects nothing and keeps the same STOP semantics.
    req = request(
        ecosystem_hints=("agent-os",),
        capability_keywords=("deployment",),
    )
    result = orchestrate_lesson_activation(
        req, execute_read=lambda query: {"results": [live_row()], "has_more": False}
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert "no-relevant-candidate" in result.selection_reason_codes
    assert result.selected_lesson_ids == ()


def test_pr_a09_missing_source_link_stays_unverifiable_after_repair():
    # The dedup/budget repair must not launder provenance. A relevant lesson
    # with no Source Link is still UNVERIFIABLE and forces manual review,
    # even when it arrives among identical duplicates.
    row = live_row(properties={"Source Link": _url(None)})
    result = orchestrate_lesson_activation(
        request(), execute_read=lambda query: {"results": [row, row], "has_more": False}
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert "unverifiable-relevant-candidate" in result.selection_reason_codes

def test_pr_a10_unranked_revision_of_ranked_id_fails_closed_at_bound_edge():
    # Regression for review #5868522723: LL-05 ranks based on one revision;
    # its conflicting revision is unranked, but must not disappear. LL-06
    # remains outside the five-distinct-ID bound.
    ranked = [
        live_row(properties={"Lesson ID": _rich_text(f"LL-0{index}")})
        for index in range(1, 7)
    ]
    conflicting_unranked = live_row(
        properties={
            "Lesson ID": _rich_text("LL-05"),
            "Area": _select("Governance"),
            "Learning Type": _select("Scope/permission lesson"),
            "Applies To": _multi_select("Drive"),
            "Guardrail": _rich_text("Conflicting guidance for the same lesson."),
        },
        last_edited_time="2026-11-05T12:00:00.000Z",
    )
    for rows in ([conflicting_unranked, *ranked], [*ranked, conflicting_unranked]):
        lessons = [normalize_lesson_row(row) for row in rows]
        assert all(isinstance(item, LessonRecordEvidence) for item in lessons)
        bounded, _ = _bound_relevant_lessons_with_order(request(), lessons)
        assert {item.lesson_id for item in bounded} == {
            "LL-01", "LL-02", "LL-03", "LL-04", "LL-05"
        }
        assert len([item for item in bounded if item.lesson_id == "LL-05"]) == 2
        result = orchestrate_lesson_activation(
            request(), execute_read=lambda query: {"results": rows, "has_more": False}
        )
        assert result.candidate_count == 6  # four other IDs plus both revisions
        assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
        assert "duplicate-identity-conflict" in result.selection_reason_codes
        assert result.selected_lesson_ids == ()


def _snapshot_with_source(primary, *, supporting=None):
    properties = {"Source Link": _url(primary)}
    if supporting is not None:
        properties["Supporting Source Links"] = _rich_text(supporting)
    row = live_row(properties=properties)
    return normalize_lesson_row(row), orchestrate_lesson_retrieval(
        request(specialized_knowledge_required=True),
        execute_read=lambda query: {"results": [row], "has_more": False, "next_cursor": None},
    )


def test_primary_source_requires_concrete_resource_in_qualified_snapshot():
    incomplete = (
        "https://github.com/",
        "https://github.com/Blummer92",
        "https://github.com/Blummer92/agent-os",
        "https://github.com/Blummer92/agent-os/issues",
        "https://github.com/Blummer92/agent-os/issues/0",
        "https://github.com/Blummer92/agent-os/pull/notes",
        "https://github.com/Blummer92/agent-os/pull/2425#issuecomment-1",
        "https://github.com/Blummer92/agent-os/blob/main",
        "https://github.com/Blummer92/agent-os/actions/runs",
        "https://github.com/Blummer92/agent-os/actions/runs/44457169061/job",
        "https://github.com/Blummer92/agent-os/actions/runs/44457169061/job/not-a-job-id",
        "https://github.com.evidence.invalid/Blummer92/agent-os/issues/2425",
        "00_Governance/",
        "08_Tooling/../README.md",
    )
    for primary in incomplete:
        lesson, result = _snapshot_with_source(
            primary, supporting="https://github.com/Blummer92/agent-os/issues/2425"
        )
        assert lesson.currentness is KnowledgeCurrentness.UNVERIFIABLE, primary
        assert lesson.canonical_github_refs == (), primary
        assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW, primary
        assert result.selected_lesson_ids == (), primary
        assert "unverifiable-relevant-candidate" in result.selection_reason_codes, primary


def test_primary_source_concrete_resources_keep_qualified_snapshot_sufficient():
    concrete = (
        "https://github.com/Blummer92/agent-os/issues/2425",
        "https://github.com/Blummer92/agent-os/pull/4030",
        "https://github.com/Blummer92/agent-os/blob/main/00_Governance/README.md",
        "https://github.com/Blummer92/agent-os/commit/07f9e0657d6fd8f5e3e2734e926856ded5111147",
        "https://github.com/Blummer92/agent-os/actions/runs/44457169061",
        "https://github.com/Blummer92/agent-os/actions/runs/44149572188/job/134274343781",
        "https://github.com/other-owner/other.repo/issues/42",
        "00_Governance/README.md",
        "01_Shared_Standards/python/testing-standard.md",
        "02_Agent_Overlays/chatgpt-orchestrator.md",
        "04_Registry/README.md",
        "08_Tooling/agent-memory-context-manager/CKR6_LESSON_PREFLIGHT.md",
    )
    supporting = "https://github.com/Blummer92/agent-os/issues/3418"
    for primary in concrete:
        lesson, result = _snapshot_with_source(primary, supporting=supporting)
        assert lesson.currentness is KnowledgeCurrentness.CURRENT, primary
        assert lesson.canonical_github_refs == (primary, supporting), primary
        assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT, primary
        assert result.selected_lesson_ids == ("LL-42",), primary


def test_activation_and_preflight_keep_the_same_candidate_provenance_and_text_roles():
    raw = live_row()
    lesson = normalize_lesson_row(raw)
    assert isinstance(lesson, LessonRecordEvidence)
    direct = consume_lesson_preflight(request(), (lesson,))
    routed = orchestrate_lesson_retrieval(
        request(), execute_read=lambda _: {"results": [raw], "has_more": False}
    )
    assert direct.selection is not None
    assert routed.selection is not None
    assert direct.selection.to_dict() == routed.selection.to_dict()
    assert routed.selected_lesson_ids == ("LL-42",)
    [selected] = routed.selection.selected
    assert selected.candidate.source_revision == raw["last_edited_time"]
    assert selected.candidate.use_when == (
        "Reacquire evidence after head advances.", "Never reuse stale evidence."
    )
    assert selected.candidate.canonical_github_refs == lesson.canonical_github_refs
    assert routed.authority_created is False


@pytest.mark.parametrize("closed", [True, False], ids=["terminal-cap", "continuing-cap"])
def test_legacy_activation_preserves_exact_twenty_five_row_boundary(closed):
    calls = []
    normalized_row = live_row()

    def read(query):
        calls.append(query)
        if len(calls) == 1:
            return {"results": [normalized_row] * 24, "has_more": True, "next_cursor": " opaque "}
        return {"results": [normalized_row], "has_more": not closed,
                "next_cursor": None if closed else "unread"}

    req = request(known_knowledge_refs=("LL-42",))
    if closed:
        result = orchestrate_lesson_activation(req, execute_read=read)
        assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
        assert result.selected_lesson_ids == ("LL-42",)
        assert result.authority_created is False
    else:
        with pytest.raises(LessonActivationError, match="^paginated retrieval exceeded row bound$"):
            orchestrate_lesson_activation(req, execute_read=read)
    exact_query = build_known_reference_query(("LL-42",))
    assert calls == [exact_query, {**exact_query, "start_cursor": " opaque "}]


def test_legacy_exact_query_rejects_unrequested_identity():
    requested = request(known_knowledge_refs=("LL-42",))
    wrong = live_row(properties={"Lesson ID": _rich_text("LL-43")})

    def read(query):
        assert query == build_known_reference_query(("LL-42",))
        return {"results": [live_row(), wrong], "has_more": False}

    with pytest.raises(LessonActivationError, match="^known-reference response contained an unrequested lesson$"):
        orchestrate_lesson_activation(requested, execute_read=read)


@pytest.mark.parametrize("prior_known", [False, True])
def test_legacy_activation_does_not_repeat_a_recorded_filtered_query(prior_known):
    attempted = (RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,)
    if prior_known:
        attempted += (RetrievalEscalation.KNOWN_REFERENCE,)
    req = request(
        known_knowledge_refs=("LL-42",) if prior_known else (),
        attempted_retrieval=attempted,
        specialized_knowledge_required=True,
    )
    calls = []

    def read(query):
        calls.append(query)
        return {"results": [live_row()], "has_more": False}

    result = orchestrate_lesson_activation(req, execute_read=read)
    assert calls == []
    assert result.selected_lesson_ids == ()
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.retrieval_escalation is RetrievalEscalation.MANUAL_REVIEW


def test_legacy_recorded_filtered_query_does_not_consume_unused_exact_route():
    req = request(
        known_knowledge_refs=("LL-42",),
        attempted_retrieval=(RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,),
        specialized_knowledge_required=True,
    )
    calls = []

    def read(query):
        calls.append(query)
        return {"results": [live_row()], "has_more": False}

    result = orchestrate_lesson_activation(req, execute_read=read)
    assert calls == [build_known_reference_query(("LL-42",))]
    assert result.selected_lesson_ids == ("LL-42",)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT


def test_known_lookup_bound_counts_distinct_provider_numbers():
    refs = ("LL-01", "1", "#19", "LL-2", "LL-3", "LL-4", "LL-5", "LL-6")
    assert known_lesson_numbers(refs) == (1, 2, 3, 4, 5)
    clauses = build_known_reference_query(refs)["filter"]["or"]
    assert [clause["unique_id"]["equals"] for clause in clauses] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize(("field", "kind", "bound", "result_field", "over_reason"), [
    ("Lesson Learned", "title", MAX_ROW_TEXT_CHARS, "title", "missing-title"),
    ("Guardrail", "rich_text", MAX_GUIDANCE_TEXT_CHARS, "guardrail", "oversized-activation-guidance"),
    ("What To Do Next Time", "rich_text", MAX_GUIDANCE_TEXT_CHARS,
     "what_to_do_next_time", "oversized-activation-guidance"),
])
def test_shared_text_decoder_keeps_exact_boundary_and_distinct_overflow_reason(
    field, kind, bound, result_field, over_reason,
):
    def decode(size):
        value = [{"plain_text": " " + ("x" * (size - 1))}, {"plain_text": "y "}]
        return normalize_lesson_row(live_row(properties={field: {"type": kind, kind: value}}))

    accepted = decode(bound)
    assert isinstance(accepted, LessonRecordEvidence)
    assert getattr(accepted, result_field) == "x" * (bound - 1) + "y"
    assert decode(bound + 1) == LessonActivationSkip("LL-42", over_reason)


@pytest.mark.parametrize("items", [
    {"plain_text": "not an array"},
    ({"plain_text": "tuple is not a provider array"},),
    [{"plain_text": "valid prefix"}, {}],
    [{"plain_text": "valid prefix"}, "not an object"],
    [{"plain_text": "x"}] * (MAX_ROW_LIST_ITEMS + 1),
])
def test_shared_text_decoder_rejects_malformed_or_unbounded_segments(items):
    fields = {
        "Lesson Learned": ("title", "missing-title"),
        "Guardrail": ("rich_text", "missing-activation-guidance"),
        "What To Do Next Time": ("rich_text", "missing-activation-guidance"),
    }
    for field, (kind, reason) in fields.items():
        actual = normalize_lesson_row(live_row(properties={field: {"type": kind, kind: items}}))
        assert actual == LessonActivationSkip("LL-42", reason)


@pytest.mark.parametrize("source", ["href", "legacy", "nested"])
@pytest.mark.parametrize("value", ["match", "different", "", 0, "malformed-container"])
def test_all_supported_annotations_independently_agree_with_the_displayed_ref(source, value):
    primary = "https://github.com/Blummer92/agent-os/issues/4125"
    supporting = "https://github.com/Blummer92/agent-os/issues/1520"
    target = (" " + supporting + " " if value == "match"
              else primary if value == "different" else value)
    link = target if value == "malformed-container" else {"url": target}
    annotation = (
        {"href": target} if source == "href"
        else {"link": link} if source == "legacy" else {"text": {"link": link}}
    )
    props = {
        "Source Link": _url(primary),
        "Supporting Source Links": {
            "type": "rich_text", "rich_text": [{"plain_text": supporting, **annotation}],
        },
    }
    actual = normalize_lesson_row(live_row(properties=props))
    assert isinstance(actual, LessonRecordEvidence)
    assert actual.canonical_github_refs == ((primary, supporting) if value == "match" else (primary,))
    assert actual.dropped_supporting_refs == (() if value == "match" else (supporting,))


def test_guidance_type_tag_cannot_be_recovered_from_unrelated_property():
    payload = {"type": "number", "rich_text": [{"plain_text": "Expected-looking text."}]}
    result = normalize_lesson_row(live_row(properties={"Guardrail": payload}))
    assert result == LessonActivationSkip("LL-42", "missing-activation-guidance")


def test_legacy_bridge_skips_malformed_rows_without_preventing_valid_selection():
    raw = {"results": [{"object": "page", "properties": {}}, live_row()], "has_more": False}
    actual = orchestrate_lesson_activation(request(), execute_read=lambda _: raw)
    assert actual.selected_lesson_ids == ("LL-42",)
    assert actual.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert actual.authority_created is False


@pytest.mark.parametrize("payload,reason", [
    (["not a property"], "<malformed-supporting-property>"),
    ({"type": "rich_text", "rich_text": ({"plain_text": "text"},)}, "<oversized-supporting-list>"),
    ({"type": "rich_text", "rich_text": [{"plain_text": "text"}] * (MAX_ROW_LIST_ITEMS + 1)},
     "<oversized-supporting-list>"),
])
def test_supporting_prop_must_be_bounded_provider_shape(payload, reason):
    actual = normalize_lesson_row(live_row(properties={"Supporting Source Links": payload}))
    assert isinstance(actual, LessonRecordEvidence)
    assert len(actual.canonical_github_refs) == 1
    assert actual.dropped_supporting_refs == (reason,)


def test_supporting_property_exact_capacity_preserves_dropped_refs_with_and_without_primary():
    primary = "https://github.com/Blummer92/agent-os/issues/4125"
    refs = tuple(f"https://github.com/Blummer92/agent-os/issues/{i}"
                 for i in range(100, 100 + MAX_ROW_LIST_ITEMS))
    supporting = {"type": "rich_text", "rich_text": [{"plain_text": x} for x in refs]}
    with_primary = normalize_lesson_row(live_row(properties={
        "Source Link": _url(primary), "Supporting Source Links": supporting,
    }))
    without_primary = normalize_lesson_row(live_row(properties={
        "Source Link": _url(None), "Supporting Source Links": supporting,
    }))
    assert isinstance(with_primary, LessonRecordEvidence)
    assert isinstance(without_primary, LessonRecordEvidence)
    assert with_primary.canonical_github_refs == (primary, *refs[:MAX_SUPPORTING_REFS])
    assert with_primary.dropped_supporting_refs == refs[MAX_SUPPORTING_REFS:]
    assert without_primary.canonical_github_refs == ()
    assert without_primary.dropped_supporting_refs == refs[MAX_SUPPORTING_REFS:] + refs[:MAX_SUPPORTING_REFS]


def test_blank_supporting_cell_is_absent_not_rejected_evidence():
    actual = normalize_lesson_row(live_row(properties={"Supporting Source Links": _rich_text(" ")}))
    assert isinstance(actual, LessonRecordEvidence)
    assert actual.dropped_supporting_refs == ()


@pytest.mark.parametrize("path", ["00_Governance/", "08_Tooling/reference/", "04_Registry/./README.md"])
def test_supporting_governance_path_requires_same_concrete_resource_as_primary(path):
    lesson, result = _snapshot_with_source(path)
    assert lesson.currentness is KnowledgeCurrentness.UNVERIFIABLE
    assert result.selected_lesson_ids == ()

    primary = "https://github.com/Blummer92/agent-os/issues/4125"
    lesson, result = _snapshot_with_source(primary, supporting=path)
    assert lesson.canonical_github_refs == (primary,)
    assert lesson.dropped_supporting_refs == (path,)
    assert result.canonical_github_refs == (primary,)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT


@pytest.mark.parametrize("kind", ["primary", "supporting"])
def test_concrete_governance_resource_preserves_exact_reference_text_bound(kind):
    stem = "00_Governance/"
    exact = stem + ("a" * (MAX_ROW_TEXT_CHARS - len(stem)))
    primary = "https://github.com/Blummer92/agent-os/issues/4125"
    if kind == "primary":
        good, _ = _snapshot_with_source(exact)
        bad, _ = _snapshot_with_source(exact + "a")
        assert good.canonical_github_refs == (exact,)
        assert bad.canonical_github_refs == ()
    else:
        good, _ = _snapshot_with_source(primary, supporting=exact)
        bad, _ = _snapshot_with_source(primary, supporting=exact + "a")
        assert good.canonical_github_refs == (primary, exact)
        assert bad.canonical_github_refs == (primary,)
        assert bad.dropped_supporting_refs == (exact,)


@pytest.mark.parametrize("primary_property", [
    ["not a source property"],
    {"type": "rich_text", "url": "https://github.com/Blummer92/agent-os/issues/4125"},
    {"type": "url", "url": " "},
])
def test_invalid_primary_property_preserves_the_lesson_as_unverifiable(primary_property):
    actual = normalize_lesson_row(live_row(properties={"Source Link": primary_property}))
    assert isinstance(actual, LessonRecordEvidence)
    assert actual.canonical_github_refs == ()
    assert actual.currentness is KnowledgeCurrentness.UNVERIFIABLE


@pytest.mark.parametrize("resource", [
    "issues/4125/notes",
    "discussions/4125",
    "pull/4125?tab=files",
    "blob/main/README.md?raw=1",
    "blob/main/README .md",
    "blob/main/./README.md",
    "blob/main/README.md#heading",
    "commit/not-a-sha",
    "discussions/deadbeef",
    "commit/deadbeef/extra",
    "actions/run/4125",
    "actions/runs/latest",
    "actions/runs/4125/steps/1",
    "actions/runs/not-a-number/job/1",
    "foo/runs/4125",
])
def test_primary_ref_requires_the_exact_supported_resource_shape(resource):
    actual, result = _snapshot_with_source("https://github.com/Blummer92/agent-os/" + resource)
    assert actual.currentness is KnowledgeCurrentness.UNVERIFIABLE
    assert result.selected_lesson_ids == ()


@pytest.mark.parametrize("value", [
    "https://github.com/Blummer92/agent!os/issues/4125",
    "Blummer92/agent-os/issues/4125",
    "00_Governance/README.md#heading",
    "00_Governance/README\\draft.md",
    "00_Governance/README\x01draft.md",
    "00_Governance/README\x7fdraft.md",
])
def test_primary_canonical_refs_drop_malformed_identifier_or_path_text(value):
    actual, result = _snapshot_with_source(value)
    assert actual.currentness is KnowledgeCurrentness.UNVERIFIABLE
    assert result.selected_lesson_ids == ()


def test_governance_path_preserves_an_ordinary_internal_space():
    actual, result = _snapshot_with_source("00_Governance/Release Notes.md")
    assert actual.canonical_github_refs == ("00_Governance/Release Notes.md",)
    assert result.selected_lesson_ids == ("LL-42",)


def test_blob_reference_can_name_a_single_file_at_the_root():
    actual, result = _snapshot_with_source("https://github.com/Blummer92/agent-os/blob/main/README.md")
    assert actual.canonical_github_refs == ("https://github.com/Blummer92/agent-os/blob/main/README.md",)
    assert result.selected_lesson_ids == ("LL-42",)
