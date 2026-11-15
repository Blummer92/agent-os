from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest,
    RetrievalEscalation,
)
from agent_memory_context_manager.lesson_preflight import (
    FailedRepairAttempt,
    LessonRetrievalStatus,
    RepairContext,
    RetryReentryOutcome,
)
from agent_memory_context_manager.repair_lesson_activation import activate_repair_retry_lessons
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    MAX_ESCALATION_STEPS,
    MAX_RETRIEVAL_PAGES,
    MAX_RETRIEVAL_ROWS,
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


# --- CKR11 cursor-completeness regression (reuses #3973's finite contract) ---


def test_ckr11_finds_current_relevant_lesson_on_second_page():
    calls = []
    irrelevant = _lesson_row("LL-41")
    irrelevant["properties"]["Area"] = _select("Governance")
    irrelevant["properties"]["Learning Type"] = _select("Mistake")

    def read(query):
        calls.append(dict(query))
        if "start_cursor" not in query:
            return {"results": [irrelevant], "has_more": True, "next_cursor": "c1"}
        assert query["start_cursor"] == "c1"
        return {"results": [_lesson_row("LL-42")], "has_more": False, "next_cursor": None}

    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-42",)
    assert len(calls) == 2
    assert calls[1]["filter"] == calls[0]["filter"]
    assert calls[1]["page_size"] == calls[0]["page_size"]
    assert result.retrieval_diagnostics["read_count"] == 2
    assert result.retrieval_diagnostics["observed_rows"] == 2


def test_ckr11_legacy_single_page_response_is_unchanged():
    calls = []
    def read(query):
        calls.append(dict(query))
        return {"results": [_lesson_row("LL-42")]}
    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-42",)
    assert len(calls) == 1


def test_ckr11_relevant_first_page_cannot_admit_when_next_page_is_broken():
    calls = []
    def read(query):
        calls.append(dict(query))
        if len(calls) == 1:
            return {"results": [_lesson_row("LL-42")], "has_more": True, "next_cursor": "c1"}
        return {"results": [], "has_more": True, "next_cursor": None}

    activation = activate_repair_retry_lessons(
        request(),
        FailedRepairAttempt("attempt-42", "partial evidence enough", "previous failure"),
        execute_read=read,
        repair_context=RepairContext.CI_DIAGNOSIS,
    )
    assert len(calls) == 2
    assert activation.lesson_result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert "lesson-read-incomplete" in activation.lesson_result.selection_reason_codes
    assert activation.lesson_result.selected_lesson_ids == ()
    assert activation.attempt.retry_reentry_outcome is RetryReentryOutcome.UNAVAILABLE_OR_FAILED
    assert activation.boundary.mutation_admissible is False
    assert activation.boundary.blocking_attempt_id == "attempt-42"


def test_ckr11_repeated_cursor_fails_closed_without_third_read():
    calls = []
    def read(query):
        calls.append(dict(query))
        return {"results": [_lesson_row("LL-42")], "has_more": True, "next_cursor": "c1"}
    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    assert len(calls) == 2
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert "lesson-read-incomplete" in result.selection_reason_codes
    assert result.retrieval_diagnostics["read_count"] == 2
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "repeated-cursor"


def test_ckr11_page_cap_fails_closed_without_unbounded_reads():
    calls = []
    def read(query):
        calls.append(dict(query))
        return {"results": [], "has_more": True, "next_cursor": f"cursor-{len(calls)}"}
    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    assert len(calls) == MAX_RETRIEVAL_PAGES
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert "lesson-read-incomplete" in result.selection_reason_codes


def test_ckr11_row_cap_with_more_results_refuses_partial_selection():
    calls = []
    def read(query):
        calls.append(dict(query))
        return {
            "results": [_lesson_row(f"LL-{n}") for n in range(1, MAX_RETRIEVAL_ROWS + 1)],
            "has_more": True,
            "next_cursor": "later",
        }
    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    assert len(calls) == 1
    assert result.selected_lesson_ids == ()
    assert "lesson-read-incomplete" in result.selection_reason_codes


def test_ckr11_oversized_provider_page_fails_closed_without_silent_truncation():
    def read(_query):
        return {
            "results": [_lesson_row(f"LL-{n}") for n in range(1, MAX_RETRIEVAL_ROWS + 2)],
            "has_more": False,
        }
    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert "lesson-read-incomplete" in result.selection_reason_codes
    assert result.selected_lesson_ids == ()


def test_ckr11_malformed_pagination_state_fails_closed():
    for bad_page in (
        {"results": [_lesson_row("LL-42")], "has_more": "true"},
        {"results": [_lesson_row("LL-42")], "has_more": True, "next_cursor": 123},
    ):
        result = orchestrate_lesson_retrieval(request(), execute_read=lambda _q: bad_page)
        assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
        assert "lesson-read-incomplete" in result.selection_reason_codes
        assert result.selected_lesson_ids == ()
