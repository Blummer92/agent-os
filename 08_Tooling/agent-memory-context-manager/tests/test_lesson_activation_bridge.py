from copy import deepcopy

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest,
    RetrievalEscalation,
    SufficiencyStatus,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    MAX_RETRIEVAL_ROWS,
    LessonActivationSkip,
    _bound_relevant_lessons,
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
        execute_read=lambda query: {"results": rows},
    )
    assert result.candidate_count <= 5
    assert "LL-RELEVANT" in result.selected_lesson_ids


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


def test_surface_before_work_false_survives_normalization_and_blocks_selection():
    # Known-reference reads carry no Surface filter, so the normalized flag is the gate (#3417 D1).
    row = live_row(properties={"Surface Before Work?": _checkbox(False)})
    before = deepcopy(row)
    assert normalize_lesson_row(row).surface_before_work is False
    result = orchestrate_lesson_activation(request(known_knowledge_refs=("LL-42",)), execute_read=lambda query: {"results": [row]})
    assert result.selected_lesson_ids == ()
    assert row == before  # normalization never mutates the live row


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
    bounded = _bound_relevant_lessons(request(), lessons)
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
        req, execute_read=lambda query: {"results": [live_row()]}
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
    bounded = _bound_relevant_lessons(request(), lessons)
    ll05 = [item for item in bounded if item.lesson_id == "LL-05"]
    assert len(ll05) == 2  # both conflicting revisions enter the bound
    assert {item.source_revision for item in ll05} == {
        "2026-11-04T12:00:00.000Z",
        "2026-11-05T12:00:00.000Z",
    }
    # End to end: the conflict must surface as manual review, not a silent pass.
    result = orchestrate_lesson_activation(
        request(), execute_read=lambda query: {"results": rows}
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert "duplicate-identity-conflict" in result.selection_reason_codes


def test_pr_a07_single_query_path_matches_orchestrator_identity_behavior():
    # Identical duplicates collapse and conflicting identities fail closed
    # through orchestrate_lesson_activation's single-query path too.
    identical = live_row()
    result = orchestrate_lesson_activation(
        request(), execute_read=lambda query: {"results": [identical, identical]}
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
        request(), execute_read=lambda query: {"results": [conflict_a, conflict_b]}
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
        req, execute_read=lambda query: {"results": [live_row()]}
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
        request(), execute_read=lambda query: {"results": [row, row]}
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
        bounded = _bound_relevant_lessons(request(), lessons)
        assert {item.lesson_id for item in bounded} == {
            "LL-01", "LL-02", "LL-03", "LL-04", "LL-05"
        }
        assert len([item for item in bounded if item.lesson_id == "LL-05"]) == 2
        result = orchestrate_lesson_activation(
            request(), execute_read=lambda query: {"results": rows}
        )
        assert result.candidate_count == 6  # four other IDs plus both revisions
        assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
        assert "duplicate-identity-conflict" in result.selection_reason_codes
        assert result.selected_lesson_ids == ()


# PR-1 diagnostic oracles: no selector loosening and no extra provider reads.

def test_diagnostic_exposes_normalization_skip_without_admitting_lesson():
    row = live_row(properties={"Area": _select("Unknown area")})
    calls = []

    def read(query):
        calls.append(query)
        return {"results": [row]}

    result = orchestrate_lesson_activation(
        request(specialized_knowledge_required=True), execute_read=read
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.selected_lesson_ids == ()
    assert result.candidate_count == 0
    assert result.rejected_candidate_provenance == ({
        "lesson_id": "LL-42",
        "source_revision": "",
        "currentness": "not-evaluated",
        "provenance": "normalization-or-eligibility-rejected",
        "rejection_reason": "ambiguous-area-vocabulary",
    },)
    assert len(calls) == 1
    assert result.authority_created is False


def test_diagnostic_exposes_no_task_signal_match_without_widening_selection():
    result = orchestrate_lesson_activation(
        request(
            ecosystem_hints=("javascript",),
            capability_keywords=("unrelated",),
            specialized_knowledge_required=True,
        ),
        execute_read=lambda _query: {"results": [live_row()]},
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.selected_count == 0
    assert result.selection_reason_codes == ("no-relevant-candidate",)
    assert result.rejected_candidate_provenance[0]["lesson_id"] == "LL-42"
    assert result.rejected_candidate_provenance[0]["rejection_reason"] == "no-task-signal-match"


def test_diagnostic_says_surface_flag_disabled_without_selecting():
    result = orchestrate_lesson_activation(
        request(specialized_knowledge_required=True),
        execute_read=lambda _query: {
            "results": [live_row(properties={"Surface Before Work?": _checkbox(False)})]
        },
    )
    assert result.selected_lesson_ids == ()
    assert result.rejected_candidate_provenance[0]["rejection_reason"] == "surface-before-work-disabled"
