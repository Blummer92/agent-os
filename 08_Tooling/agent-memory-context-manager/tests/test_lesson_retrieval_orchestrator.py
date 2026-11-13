from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest,
    RetrievalEscalation,
)
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    MAX_ESCALATION_STEPS,
    build_escalation_query,
    orchestrate_lesson_retrieval,
    record_retrieval_attempt,
)


def request(**overrides):
    data = dict(
        task_reference="issue:#2141",
        ecosystem_hints=("python",),
        capability_keywords=("testing",),
        target_path_hints=(),
        canonical_rule_refs=(),
        known_knowledge_refs=(),
        specialized_knowledge_required=True,
    )
    data.update(overrides)
    return CodingKnowledgeRequest(**data)


def test_record_retrieval_attempt_advances_ckr2_ledger_without_mutating_input():
    original = request()
    updated = record_retrieval_attempt(
        original,
        RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,
    )
    assert original.attempted_retrieval == ()
    assert updated.attempted_retrieval == (
        RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,
    )


def test_exact_lookup_is_not_the_same_query_as_filtered_query():
    req = request()
    filtered = build_escalation_query(
        req,
        RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,
    )
    exact = build_escalation_query(
        req,
        RetrievalEscalation.EXACT_NARROW_LOOKUP,
    )
    assert exact != filtered
    assert exact["page_size"] <= filtered["page_size"]


def test_bounded_empty_escalation_terminates_at_manual_review():
    calls = []

    def read(query):
        calls.append(query)
        return {"results": []}

    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.retrieval_escalation is RetrievalEscalation.MANUAL_REVIEW
    assert len(calls) == 3
    assert len(calls) <= MAX_ESCALATION_STEPS
    assert calls[0] != calls[1]
    assert calls[1] != calls[2]


def test_known_reference_is_attempted_before_other_steps_and_still_terminates():
    calls = []

    def read(query):
        calls.append(query)
        return {"results": []}

    result = orchestrate_lesson_retrieval(
        request(known_knowledge_refs=("LL-63",)),
        execute_read=read,
    )
    assert result.retrieval_escalation is RetrievalEscalation.MANUAL_REVIEW
    assert len(calls) == MAX_ESCALATION_STEPS
    assert calls[0]["filter"]["or"][0]["property"] == "Lesson ID"


def test_unavailable_executor_uses_existing_ckr6_unavailability_contract():
    result = orchestrate_lesson_retrieval(request(), execute_read=None)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.retrieval_escalation is RetrievalEscalation.MANUAL_REVIEW


def test_sanitized_provider_failure_reason_survives_unavailable_projection():
    def read(_query):
        raise RuntimeError("notion-http-400")

    result = orchestrate_lesson_retrieval(request(), execute_read=read)

    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert "lesson-retrieval-unavailable-specialized-knowledge-required" in result.selection_reason_codes
    assert "notion-http-400" in result.selection_reason_codes


def test_arbitrary_runtime_error_text_is_not_exposed_in_ckr6_evidence():
    def read(_query):
        raise RuntimeError("secret-token=must-not-leak")

    result = orchestrate_lesson_retrieval(request(), execute_read=read)

    assert "lesson-read-runtime-error" in result.selection_reason_codes
    assert all("secret-token" not in reason for reason in result.selection_reason_codes)


def test_provider_failure_detail_survives_canonical_reader_chain():
    # #3032 regression: token present + verified source ID present + retrieval
    # required + canonical adapter read attempted. When the canonical reader's
    # adapter raises a provider-shaped failure, the projected unavailable result
    # must carry the actual provider cause next to the generic CKR6 reason.
    #
    # CI runs each 08_Tooling package's tests with only that package's src on
    # sys.path, so the sibling packages backing the canonical reader are added
    # here (same sys.path.insert convention used by this package's other test
    # modules). Repo root is included because agent_os_execution_service.models
    # resolves scripts.agent_os_execution_capabilities through the shared
    # namespace package.
    import sys
    from pathlib import Path

    _test_file = Path(__file__).resolve()
    _tooling = _test_file.parents[2]
    sys.path.insert(0, str(_tooling / "agent-os-execution-service" / "src"))
    sys.path.insert(0, str(_tooling / "workflow-scheduler" / "src"))
    sys.path.insert(0, str(_tooling.parent))

    from agent_os_execution_service.lesson_reader_composition import (
        build_lesson_read_executor,
    )

    class RaisingAdapter:
        def execute(self, task):
            raise RuntimeError("Notion API returned HTTP 403: Forbidden")

    reader = build_lesson_read_executor(
        data_source_id="2dfd0def-fa42-4c61-992e-c977a1fcaaf4",
        adapter=RaisingAdapter(),
    )
    assert reader is not None

    result = orchestrate_lesson_retrieval(request(), execute_read=reader)

    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.retrieval_escalation is RetrievalEscalation.MANUAL_REVIEW
    assert "lesson-retrieval-unavailable-specialized-knowledge-required" in result.selection_reason_codes
    assert "notion-http-403" in result.selection_reason_codes


# --- CKR6 PR-A (R1 selector dedup / candidate-budget repair, #2425) ---
# A01 (orchestrator half) from PR_A_TEST_MATRIX.csv. Written fail-first:
# it fails on the pre-repair accumulation (identical windows accumulate as
# new candidates) and passes once accumulation collapses by full equality.


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


def _lesson_row(lesson_id, *, last_edited="2026-11-04T12:00:00.000Z"):
    return {
        "object": "page",
        "id": f"row-{lesson_id}",
        "url": f"https://www.notion.so/lesson-{lesson_id}",
        "last_edited_time": last_edited,
        "properties": {
            "Lesson ID": _rich_text(lesson_id),
            "Lesson Learned": _title("Recheck currentness before routing"),
            "Status": _select("Applied"),
            "Surface Before Work?": _checkbox(True),
            "Area": _select("Testing"),
            "Applies To": _multi_select("Notion"),
            "Learning Type": _select("Testing lesson"),
            "Source Link": _url(
                "https://github.com/Blummer92/agent-os/blob/main/01_Shared_Standards/python/testing-standard.md"
            ),
            "Guardrail": _rich_text("Never reuse stale evidence."),
            "What To Do Next Time": _rich_text("Reacquire evidence after head advances."),
        },
    }


def test_pr_a01_identical_windows_collapse_across_escalation_steps():
    # Two distinct lessons, returned identically on every escalation step.
    # The retrieval escalates because a required library hint is uncovered,
    # so the same window is read three times. Identical records must collapse
    # by full equality in the accumulation: two candidates, not six (and not
    # five, the old record-counted bound's silent truncation).
    rows = [_lesson_row("LL-01"), _lesson_row("LL-02")]
    calls = []

    def read(query):
        calls.append(query)
        return {"results": rows}

    req = request(library_hints=("hypothesis",))
    result = orchestrate_lesson_retrieval(req, execute_read=read)
    assert len(calls) == 3
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert "required-library-uncovered" in result.selection_reason_codes
    assert result.candidate_count == 2
    assert result.selected_lesson_ids == ("LL-01", "LL-02")


def test_escalation_diagnostics_keep_existing_read_budget_and_deduplicate_skips():
    bad = _lesson_row("LL-96")
    bad["properties"]["Area"] = _select("Unknown area")
    calls = []

    def read(query):
        calls.append(query)
        return {"results": [bad]}

    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert len(calls) == 3
    assert len(calls) <= MAX_ESCALATION_STEPS
    assert result.selected_lesson_ids == ()
    assert len(result.rejected_candidate_provenance) == 1
    assert result.rejected_candidate_provenance[0]["rejection_reason"] == "ambiguous-area-vocabulary"


def test_diagnostics_are_bounded_over_retrieved_rows():
    rows = []
    for number in range(30):
        bad = _lesson_row(f"LL-{number:02d}")
        bad["properties"]["Area"] = _select("Unknown area")
        rows.append(bad)
    result = orchestrate_lesson_retrieval(
        request(), execute_read=lambda _query: {"results": rows}
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert len(result.rejected_candidate_provenance) <= 5
    assert result.selected_lesson_ids == ()
