from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest,
    RetrievalEscalation,
)
import pytest
from agent_memory_context_manager.lesson_preflight import (
    MAX_LESSON_RECORDS,
    FailedRepairAttempt,
    LessonRetrievalStatus,
    RepairContext,
    RetryReentryOutcome,
)
from agent_memory_context_manager.repair_lesson_activation import activate_repair_retry_lessons
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    MAX_ESCALATION_STEPS,
    MAX_PREFLIGHT_READS,
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


def test_generic_exact_narrow_lookup_keeps_first_controlled_clause():
    """N2 / M05d: CKR6-only complementary routing must not apply to generic work."""
    req = request(capability_keywords=("testing",), language_hints=("Python",))
    filtered = build_escalation_query(
        req, RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY,
    )
    exact = build_escalation_query(
        req, RetrievalEscalation.EXACT_NARROW_LOOKUP,
    )
    assert "or" in filtered["filter"]["and"][-1]
    assert exact["filter"]["and"][-1] == {
        "property": "Area", "select": {"equals": "Automation"},
    }
    assert exact["page_size"] == MAX_LESSON_RECORDS


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
    # The overflow is partitioned; every sub-query overflows as well, so the
    # step still fails closed with no partial selection.
    assert len(calls) > 1
    assert len(calls) <= MAX_PREFLIGHT_READS
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


# #3986: CKR6's exact, already-controlled Testing hint must be used before
# generic Python area expansion. No new provider vocabulary or authority.
def test_ckr6_exact_context_first_query_targets_testing_only():
    req = request(
        ecosystem_hints=("GitHub Actions",),
        language_hints=("Python", "YAML"),
        capability_keywords=("CKR6 mutation boundary", "trusted owner request"),
    )
    focused = build_escalation_query(req, RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY)
    broad = build_escalation_query(req, RetrievalEscalation.WORKSPACE_SEARCH)
    assert focused["filter"]["and"][-1] == {
        "property": "Area", "select": {"equals": "Testing"}
    }
    assert broad != focused
    # The final bounded workspace-search slot is deliberately broader:
    # it retains only the existing surface and non-archived filters.
    assert len(broad["filter"]["and"]) == 2


def test_ckr6_focused_query_retrieves_verified_lesson_without_broad_overflow():
    req = request(
        task_reference="PR #3989 exact head",
        ecosystem_hints=("GitHub Actions",),
        language_hints=("Python", "YAML"),
        capability_keywords=("CKR6 mutation boundary", "trusted owner request"),
    )
    row = _lesson_row("LL-63")
    row["properties"]["Lesson Learned"] = _title("CKR6 mutation boundary verification")
    row["properties"]["What To Do Next Time"] = _rich_text(
        "Verify CKR6 mutation admission against the exact head."
    )
    calls = []

    def read(query):
        calls.append(query)
        # A broad Python union would return 25 rows with has_more=True;
        # the focused controlled Testing query returns a complete result.
        if "or" in query["filter"]["and"][-1]:
            return {"results": [row] * MAX_RETRIEVAL_ROWS,
                    "has_more": True, "next_cursor": "overflow"}
        return {"results": [row], "has_more": False, "next_cursor": None}

    result = orchestrate_lesson_retrieval(req, execute_read=read)
    assert len(calls) == 1
    assert calls[0]["filter"]["and"][-1]["select"]["equals"] == "Testing"
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-63",)
    assert result.selection.selected[0].candidate.source_revision == "2026-11-04T12:00:00.000Z"
    assert result.selection.selected[0].candidate.canonical_github_refs
    assert result.retrieval_diagnostics["read_count"] == 1


def test_ckr6_testing_query_still_stops_when_it_overflows():
    req = request(capability_keywords=("CKR6 mutation boundary",))
    calls = []

    def read(query):
        calls.append(query)
        return {"results": [_lesson_row("LL-63")] * MAX_RETRIEVAL_ROWS,
                "has_more": True, "next_cursor": "more"}

    result = orchestrate_lesson_retrieval(req, execute_read=read)
    # 1 overflowing Testing read, then the first Testing x Learning Type cell
    # overflows too: the step fails closed immediately, never a truncated
    # selection and never a partial union.
    assert len(calls) == 1 + 1
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "row-bound-exceeded"
    assert result.selected_lesson_ids == ()


def test_generic_python_testing_request_retains_broad_query():
    req = request(capability_keywords=("testing",))
    query = build_escalation_query(req, RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY)
    assert "or" in query["filter"]["and"][-1]
    assert {"property": "Learning Type", "select": {"equals": "Testing lesson"}} in query["filter"]["and"][-1]["or"]


# #3990 F1: real filter evaluation, not a stub that returns a lesson for
# every non-OR query. Reproduce the independent QA's S1/S2 mixed-area cases.
def _ckr6_filter_value(prop):
    kind = prop.get("type")
    if kind == "select":
        return (prop.get("select") or {}).get("name")
    if kind == "checkbox":
        return prop.get("checkbox")
    if kind == "multi_select":
        return [entry["name"] for entry in prop.get("multi_select", ())]
    if kind in ("title", "rich_text"):
        return "".join(entry.get("plain_text", "") for entry in prop.get(kind, ()))
    raise AssertionError("unexpected property type")


def _ckr6_matches_provider_filter(row, expression):
    if "and" in expression:
        return all(_ckr6_matches_provider_filter(row, part) for part in expression["and"])
    if "or" in expression:
        return any(_ckr6_matches_provider_filter(row, part) for part in expression["or"])
    value = _ckr6_filter_value(row["properties"][expression["property"]])
    for kind in ("select", "checkbox"):
        if kind in expression:
            constraint = expression[kind]
            if "equals" in constraint:
                return value == constraint["equals"]
            if "does_not_equal" in constraint:
                return value != constraint["does_not_equal"]
    if "multi_select" in expression:
        return expression["multi_select"]["contains"] in value
    if "title" in expression:
        return expression["title"]["contains"] in value
    raise AssertionError("unsupported provider filter")


def _ckr6_area_row(n, area, *, relevant=False, learning_type="Mistake"):
    row = _lesson_row(f"LL-{n}")
    row["properties"]["Area"] = _select(area)
    row["properties"]["Learning Type"] = _select(learning_type)
    row["properties"]["Lesson Learned"] = _title(
        f"CKR6 mutation boundary guard {n}" if relevant else f"Generic lesson {n}"
    )
    row["properties"]["What To Do Next Time"] = _rich_text(
        "Bind CKR6 mutation admission to the exact head."
        if relevant else "Review general implementation guidance."
    )
    return row


def _ckr6_filter_evaluating_reader(rows, calls):
    def read(query):
        calls.append(query)
        filtered = [
            row for row in rows
            if _ckr6_matches_provider_filter(row, query["filter"])
        ]
        start = int(query.get("start_cursor") or 0)
        size = query["page_size"]
        page = filtered[start:start + size]
        more = start + size < len(filtered)
        return {
            "results": page,
            "has_more": more,
            "next_cursor": str(start + size) if more else None,
        }
    return read


def _ckr6_qa_request():
    return request(
        task_reference="PR #3989 CKR6 sanitized diagnostics artifact",
        ecosystem_hints=("GitHub Actions", "CKR6 trusted owner request", "Notion learned lessons"),
        language_hints=("Python", "YAML"),
        capability_keywords=(
            "CKR6 mutation boundary", "sanitized diagnostics artifact",
            "exact-head binding", "fail-closed admission",
        ),
        target_path_hints=(".github/workflows/",),
    )


def test_ckr6_complementary_query_preserves_automation_lesson_recall():
    req = _ckr6_qa_request()
    first = build_escalation_query(req, RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY)
    second = build_escalation_query(req, RetrievalEscalation.EXACT_NARROW_LOOKUP)
    testing = {"property": "Area", "select": {"equals": "Testing"}}
    automation = {"property": "Area", "select": {"equals": "Automation"}}
    dashboard = {"property": "Area", "select": {"equals": "Dashboard"}}
    assert first["filter"]["and"][-1] == testing
    assert second["filter"]["and"][-1] == {"or": [automation, dashboard]}
    assert second["page_size"] == MAX_LESSON_RECORDS
    assert first["filter"] != second["filter"]
    rows = (
        [_ckr6_area_row(i, "Testing") for i in range(1, 11)]
        + [_ckr6_area_row(300, "Automation", relevant=True)]
        + [_ckr6_area_row(400 + i, "Governance") for i in range(30)]
    )
    calls = []
    result = orchestrate_lesson_retrieval(
        req, execute_read=_ckr6_filter_evaluating_reader(rows, calls)
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-300",)
    assert result.selection.selected[0].candidate.source_revision == "2026-11-04T12:00:00.000Z"
    assert result.selection.selected[0].candidate.canonical_github_refs
    assert len(calls) == 2
    assert calls[0]["filter"]["and"][-1] == testing
    assert calls[1]["filter"]["and"][-1] == {"or": [automation, dashboard]}


def test_ckr6_complementary_query_retains_testing_first_cure():
    req = _ckr6_qa_request()
    rows = (
        [_ckr6_area_row(i, "Testing") for i in range(1, 20)]
        + [_ckr6_area_row(100, "Testing", relevant=True)]
        + [_ckr6_area_row(200 + i, "Automation") for i in range(20)]
    )
    calls = []
    result = orchestrate_lesson_retrieval(
        req, execute_read=_ckr6_filter_evaluating_reader(rows, calls)
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-100",)
    assert len(calls) == 1


def test_ckr6_complementary_query_still_rejects_incomplete_automation_page():
    req = _ckr6_qa_request()
    rows = (
        [_ckr6_area_row(i, "Testing") for i in range(1, 3)]
        + [_ckr6_area_row(300 + i, "Automation") for i in range(MAX_RETRIEVAL_ROWS + 1)]
    )
    calls = []
    result = orchestrate_lesson_retrieval(
        req, execute_read=_ckr6_filter_evaluating_reader(rows, calls)
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "row-bound-exceeded"
    assert len(calls) <= MAX_PREFLIGHT_READS


def test_ckr6_exact_lookup_without_other_area_stays_finite():
    req = request(
        ecosystem_hints=(),
        language_hints=(),
        capability_keywords=("CKR6 mutation boundary",),
    )
    first = build_escalation_query(req, RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY)
    second = build_escalation_query(req, RetrievalEscalation.EXACT_NARROW_LOOKUP)
    assert first["filter"]["and"][-1] == {
        "property": "Area", "select": {"equals": "Testing"}
    }
    assert second["page_size"] == MAX_LESSON_RECORDS
    assert second["filter"]["and"][-1] == {
        "property": "Area", "select": {"equals": "Testing"}
    }


def _ckr6_testing_request():
    return request(capability_keywords=("CKR6 mutation boundary",))


def _testing_rows(per_type, *, relevant_id=None):
    rows, n = [], 1000
    for learning_type, count in per_type.items():
        for _ in range(count):
            n += 1
            rows.append(_ckr6_area_row(n, "Testing", learning_type=learning_type))
    if relevant_id is not None:
        rows.append(
            _ckr6_area_row(relevant_id, "Testing", relevant=True, learning_type="Testing lesson")
        )
    return rows


def test_testing_overflow_is_partitioned_by_learning_type_and_selects_lesson():
    # Measured shape on 2026-11-15: Testing is 26+ but each Learning Type cell
    # is at most 25 (Testing lesson exactly 25).
    rows = _testing_rows(
        {"Mistake": 13, "QA feedback": 15, "Testing lesson": 24, "Trigger lesson": 5},
        relevant_id=9001,
    )
    assert len(rows) > MAX_RETRIEVAL_ROWS
    calls = []
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, calls)
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert "LL-9001" in result.selected_lesson_ids
    assert len(calls) == 1 + 6
    # Every controlled Learning Type is queried, including empty ones: no
    # snapshot count is hard-coded.
    cell_types = sorted(c["filter"]["and"][-1]["select"]["equals"] for c in calls[1:])
    assert cell_types == sorted(
        ["Mistake", "QA feedback", "Testing lesson", "Deployment lesson",
         "Scope/permission lesson", "Trigger lesson"]
    )
    for call in calls[1:]:
        assert call["filter"]["and"][-2] == {"property": "Area", "select": {"equals": "Testing"}}
        assert call["page_size"] == MAX_LESSON_RECORDS * 5
    assert result.retrieval_diagnostics["read_count"] == 7
    assert "incomplete_reason_code" not in result.retrieval_diagnostics


def test_exactly_25_row_cell_completes_but_a_26th_row_fails_closed():
    base = {"Mistake": 13, "QA feedback": 15, "Testing lesson": 24}
    ok_rows = _testing_rows(base, relevant_id=9001)  # Testing lesson cell == 25
    calls = []
    ok = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(ok_rows, calls)
    )
    assert ok.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    grown = _testing_rows({**base, "Testing lesson": 25}, relevant_id=9001)  # 26
    calls = []
    bad = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(grown, calls)
    )
    assert bad.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert bad.selected_lesson_ids == ()
    assert bad.retrieval_diagnostics["incomplete_reason_code"] == "row-bound-exceeded"
    assert "lesson-read-incomplete" in bad.selection_reason_codes


def test_partition_spends_the_unchanged_preflight_read_budget_and_fails_closed():
    # A reader that overflows every sequence; the shared 20-read ceiling is
    # never exceeded and the failure code is a closed vocabulary value.
    calls = []

    def read(query):
        calls.append(query)
        return {"results": [_lesson_row("LL-1")] * MAX_RETRIEVAL_ROWS,
                "has_more": True, "next_cursor": "x"}

    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    assert MAX_PREFLIGHT_READS == 32
    assert len(calls) <= MAX_PREFLIGHT_READS
    assert result.retrieval_diagnostics["incomplete_reason_code"] in {
        "row-bound-exceeded", "read-budget-exceeded"}
    assert result.selected_lesson_ids == ()


def test_broad_workspace_search_step_is_not_partitioned():
    req = request(
        ecosystem_hints=(), language_hints=(), capability_keywords=(),
        target_path_hints=(), known_knowledge_refs=(),
    )
    calls = []

    def read(query):
        calls.append(query)
        return {"results": [_lesson_row("LL-1")] * MAX_RETRIEVAL_ROWS,
                "has_more": True, "next_cursor": "x"}

    result = orchestrate_lesson_retrieval(req, execute_read=read)
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "row-bound-exceeded"
    assert len(calls) <= MAX_ESCALATION_STEPS


def _stress_snapshot_rows():
    # ADVERSARIAL STRESS FIXTURE, not a count-consistent reproduction.
    # Area totals follow the 2026-11-15 counts-only measurement (Testing 26+,
    # Automation 26+, Governance 23, Documentation 5, Dashboard 0, Testing x
    # Testing lesson 25, Automation x Testing lesson 8), but the Learning Type
    # totals do not: 30 Mistake rows against 13 measured. See
    # _count_consistent_rows for the replay that respects the measured marginals.
    plan = {
        ("Testing", "Testing lesson"): 25,
        ("Testing", "Mistake"): 3,
        ("Automation", "Testing lesson"): 8,
        ("Automation", "Mistake"): 10,
        ("Automation", "QA feedback"): 9,
        ("Governance", "QA feedback"): 6,
        ("Governance", "Mistake"): 17,
        ("Documentation", "Scope/permission lesson"): 5,
    }
    rows, n = [], 2000
    for (area, learning_type), count in plan.items():
        for _ in range(count):
            n += 1
            rows.append(_ckr6_area_row(n, area, learning_type=learning_type))
    return rows


def test_stress_replay_testing_only_shape_no_longer_row_bound_fails():
    rows = _stress_snapshot_rows() + [
        _ckr6_area_row(9001, "Testing", relevant=True, learning_type="Mistake")
    ]
    calls = []
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, calls)
    )
    assert "lesson-read-incomplete" not in result.selection_reason_codes
    assert "incomplete_reason_code" not in result.retrieval_diagnostics
    assert "LL-9001" in result.selected_lesson_ids
    assert result.retrieval_diagnostics["read_count"] == 7


def _stress_or_shape_rows(*, with_testing_lesson_overflow):
    # ADVERSARIAL STRESS FIXTURE, not a count-consistent reproduction.
    # Mistake 26 and QA feedback 28 exceed the measured 13 and 15, and the
    # optional Governance overflow (25 rows) exceeds the measured 23. The
    # single planted Automation x Testing lesson row also contradicts the exact
    # measured Automation x Testing lesson = 8. It stays
    # useful because it forces every OR alternative and the Learning Type
    # alternative to overflow. The only Testing-lesson-typed row is planted in
    # Automation, so selecting it proves the cell union reached it.
    plan = {("Testing", "Mistake"): 13, ("Testing", "QA feedback"): 15,
            ("Automation", "Mistake"): 13, ("Automation", "QA feedback"): 13}
    rows, n = [], 3000
    for (area, learning_type), count in plan.items():
        for _ in range(count):
            n += 1
            rows.append(_ckr6_area_row(n, area, learning_type=learning_type))
    planted = _ckr6_area_row(9003, "Automation", learning_type="Testing lesson")
    rows.append(planted)
    if with_testing_lesson_overflow:
        rows += [_ckr6_area_row(3500 + i, "Governance", learning_type="Testing lesson")
                 for i in range(25)]
    return rows


def test_stress_replay_or_shape_selects_planted_row_inside_the_20_read_ceiling():
    calls = []
    result = orchestrate_lesson_retrieval(
        request(capability_keywords=("testing",)),
        execute_read=_ckr6_filter_evaluating_reader(
            _stress_or_shape_rows(with_testing_lesson_overflow=False), calls),
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-9003",)
    # 1 OR overflow + Automation (1+6) + Dashboard 1 + Testing (1+6) + Learning Type 1
    assert result.retrieval_diagnostics["read_count"] == 17 <= MAX_PREFLIGHT_READS
    assert "incomplete_reason_code" not in result.retrieval_diagnostics


def test_stress_replay_or_shape_needs_21_reads_when_testing_lesson_also_overflows(monkeypatch):
    import agent_memory_context_manager.lesson_retrieval_orchestrator as orch

    rows = _stress_or_shape_rows(with_testing_lesson_overflow=True)
    # Negative control: at the previous 20-read ceiling this shape fails closed
    # rather than truncating.
    monkeypatch.setattr(orch, "MAX_PREFLIGHT_READS", 20)
    calls = []
    capped = orchestrate_lesson_retrieval(
        request(capability_keywords=("testing",)),
        execute_read=_ckr6_filter_evaluating_reader(rows, calls),
    )
    assert capped.retrieval_diagnostics["incomplete_reason_code"] == "read-budget-exceeded"
    assert capped.retrieval_diagnostics["read_count"] == 20
    assert capped.selected_lesson_ids == ()
    # At the production ceiling (32) it completes in 21 reads and selects.
    monkeypatch.undo()
    assert MAX_PREFLIGHT_READS == 32
    calls = []
    result = orchestrate_lesson_retrieval(
        request(capability_keywords=("testing",)),
        execute_read=_ckr6_filter_evaluating_reader(rows, calls),
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids  # 25 generic Testing-lesson rows also compete
    assert result.retrieval_diagnostics["read_count"] == 21
    assert "incomplete_reason_code" not in result.retrieval_diagnostics


def test_stress_replay_overflow_in_a_cell_never_truncates_to_a_selection():
    rows = _stress_snapshot_rows() + [
        _ckr6_area_row(9100 + i, "Testing", learning_type="Testing lesson") for i in range(2)
    ]  # Testing x Testing lesson = 27
    calls = []
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, calls)
    )
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "row-bound-exceeded"
    assert "lesson-read-incomplete" in result.selection_reason_codes


def test_identical_sub_queries_reached_from_two_alternatives_are_read_once():
    rows = _stress_snapshot_rows()
    calls = []
    orchestrate_lesson_retrieval(
        request(capability_keywords=("testing",)),
        execute_read=_ckr6_filter_evaluating_reader(rows, calls),
    )
    keys = [
        sorted(str(sorted(c.items())) for c in call["filter"]["and"]) + [str(call.get("start_cursor"))]
        for call in calls
    ]
    assert len(keys) == len({str(k) for k in keys})


def test_partition_rules_enumerate_every_controlled_value_and_every_alternative():
    from agent_memory_context_manager.lesson_retrieval_orchestrator import _partition_queries

    base = [
        {"property": "Surface Before Work?", "checkbox": {"equals": True}},
        {"property": "Status", "select": {"does_not_equal": "Archived note"}},
    ]
    lt = {"property": "Learning Type", "select": {"equals": "Testing lesson"}}
    area = {"property": "Area", "select": {"equals": "Testing"}}
    alts = [
        {"property": "Area", "select": {"equals": name}}
        for name in ("Automation", "Dashboard", "Testing")
    ]

    parts, crossed = _partition_queries({"filter": {"and": [*base, lt]}}, crossed=False)
    assert crossed is True
    assert sorted(p["filter"]["and"][-1]["select"]["equals"] for p in parts) == sorted(
        ["Curriculum", "Automation", "Dashboard", "Governance", "Documentation", "Testing"]
    )
    parts, crossed = _partition_queries({"filter": {"and": [*base, area]}}, crossed=False)
    assert len(parts) == 6 and crossed is True
    parts, crossed = _partition_queries({"filter": {"and": [*base, {"or": alts}]}}, crossed=False)
    assert [p["filter"]["and"][-1] for p in parts] == alts and crossed is False
    # A crossed cell and an unrecognized clause are never split further.
    assert _partition_queries({"filter": {"and": [*base, area, lt]}}, crossed=True)[0] == []
    title = {"property": "Lesson Learned", "title": {"contains": "x"}}
    assert _partition_queries({"filter": {"and": [*base, title]}}, crossed=False)[0] == []


@pytest.mark.parametrize(
    ("label", "make_request", "expected_reads", "expected_code"),
    [
        ("stress: testing-only miss path", lambda: request(capability_keywords=("CKR6 mutation boundary",)), 28, "row-bound-exceeded"),
        ("stress: QA shape miss path", _ckr6_qa_request, 28, "row-bound-exceeded"),
        ("stress: OR shape miss path", lambda: request(capability_keywords=()), 31, "row-bound-exceeded"),
    ],
)
def test_stress_miss_paths_fit_a_32_read_ceiling_and_end_at_the_unpartitioned_broad_step(
    monkeypatch, label, make_request, expected_reads, expected_code
):
    # STRESS fixture (Mistake 30 vs 13 measured), no relevant row: every step runs. The only
    # terminal failure is the unchanged, unpartitioned broad step (base filter
    # is 26+ on this snapshot), which stays fail closed.
    import agent_memory_context_manager.lesson_retrieval_orchestrator as orch

    monkeypatch.setattr(orch, "MAX_PREFLIGHT_READS", 32)
    calls = []
    result = orchestrate_lesson_retrieval(
        make_request(), execute_read=_ckr6_filter_evaluating_reader(_stress_snapshot_rows(), calls)
    )
    assert result.retrieval_diagnostics["read_count"] == expected_reads, label
    assert result.retrieval_diagnostics["incomplete_reason_code"] == expected_code
    assert result.selected_lesson_ids == ()
    # And at the unchanged 20 ceiling the same shapes fail closed earlier.
    monkeypatch.setattr(orch, "MAX_PREFLIGHT_READS", 20)
    calls = []
    capped = orchestrate_lesson_retrieval(
        make_request(), execute_read=_ckr6_filter_evaluating_reader(_stress_snapshot_rows(), calls)
    )
    assert capped.retrieval_diagnostics["read_count"] == 20
    assert capped.selected_lesson_ids == ()


# --- independent-QA checklist additions (coverage, conflicts, boundaries, P6) ---

def _spy_bound(monkeypatch):
    import agent_memory_context_manager.lesson_retrieval_orchestrator as orch

    seen = []
    real = orch._bound_relevant_lessons

    def spy(req, accumulated):
        seen.append(list(accumulated))
        return real(req, accumulated)

    monkeypatch.setattr(orch, "_bound_relevant_lessons", spy)
    return seen


def test_conflicting_revisions_in_different_cells_both_reach_ckr2(monkeypatch):
    seen = _spy_bound(monkeypatch)
    rows = _testing_rows({"Mistake": 14, "QA feedback": 14}, relevant_id=9001)
    stale = _ckr6_area_row(9001, "Testing", relevant=True, learning_type="Mistake")
    stale["last_edited_time"] = "2026-10-01T00:00:00.000Z"
    orchestrate_lesson_retrieval(
        _ckr6_testing_request(),
        execute_read=_ckr6_filter_evaluating_reader(rows + [stale], []),
    )
    revisions = {
        r.source_revision for r in seen[-1] if r.lesson_id == "LL-9001"
    }
    assert revisions == {"2026-10-01T00:00:00.000Z", "2026-11-04T12:00:00.000Z"}


def test_identical_record_returned_by_two_cells_collapses_to_one(monkeypatch):
    seen = _spy_bound(monkeypatch)
    rows = _testing_rows({"Mistake": 14, "QA feedback": 14}, relevant_id=9001)
    orchestrate_lesson_retrieval(
        request(capability_keywords=("testing",)),
        execute_read=_ckr6_filter_evaluating_reader(rows, []),
    )
    ids = [r.lesson_id for r in seen[-1]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("failing_call", [2, 4, 7])
def test_no_partial_result_reaches_ckr2_after_a_sub_query_failure(monkeypatch, failing_call):
    seen = _spy_bound(monkeypatch)
    rows = _testing_rows({"Mistake": 13, "QA feedback": 15, "Testing lesson": 24}, relevant_id=9001)
    inner = _ckr6_filter_evaluating_reader(rows, [])
    count = {"n": 0}

    def read(query):
        count["n"] += 1
        if count["n"] == failing_call:
            raise ConnectionError("provider failure")
        return inner(query)

    result = orchestrate_lesson_retrieval(_ckr6_testing_request(), execute_read=read)
    assert seen == []  # the bounding/selection stage never saw partial rows
    assert result.selected_lesson_ids == ()
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.retrieval_diagnostics["candidate_count"] == 0


@pytest.mark.parametrize("req_kind", ["area-or-type-or", "learning-type-only", "single-area"])
@pytest.mark.parametrize("seed", range(40))
def test_partitioned_union_equals_direct_filter_for_every_area_and_learning_type(seed, req_kind):
    # Randomized coverage: rows spread over every Area x Learning Type cell plus
    # rows with missing or out-of-vocabulary metadata. With every cell at most
    # 25 rows, the union the partition reads must contain every row the direct
    # filter matches that the normalizer can use; unsupported rows are skipped
    # by the normalizer either way.
    import random
    from agent_memory_context_manager.lesson_activation_bridge import (
        LessonActivationSkip, normalize_lesson_row)

    rng = random.Random(seed)
    areas = ["Curriculum", "Automation", "Dashboard", "Governance", "Documentation", "Testing"]
    types = ["Mistake", "QA feedback", "Testing lesson", "Deployment lesson",
             "Scope/permission lesson", "Trigger lesson"]
    rows, n = [], 5000
    for area in areas:
        for lt in types:
            for _ in range(rng.randint(0, 6)):
                n += 1
                rows.append(_ckr6_area_row(n, area, learning_type=lt))
    for _ in range(rng.randint(0, 6)):
        n += 1
        row = _ckr6_area_row(n, rng.choice(areas), learning_type="Mistake")
        row["properties"]["Learning Type"] = {"type": "select", "select": None}
        rows.append(row)
    for _ in range(rng.randint(0, 6)):
        n += 1
        row = _ckr6_area_row(n, "Testing", learning_type="Mistake")
        row["properties"]["Area"] = _select("Retired area")
        rows.append(row)
    req = {
        "area-or-type-or": request(capability_keywords=("testing",)),  # 3 Areas + TL
        "learning-type-only": request(ecosystem_hints=(), capability_keywords=("testing",)),
        "single-area": request(capability_keywords=("CKR6 mutation boundary",)),
    }[req_kind]
    from agent_memory_context_manager.lesson_retrieval_orchestrator import build_escalation_query
    query = build_escalation_query(req, RetrievalEscalation.FILTERED_DATA_SOURCE_QUERY)
    direct = {
        r["id"] for r in rows
        if _ckr6_matches_provider_filter(r, query["filter"])
        and not isinstance(normalize_lesson_row(r), LessonActivationSkip)
    }
    returned = set()
    inner = _ckr6_filter_evaluating_reader(rows, [])

    def read(q):
        out = inner(q)
        returned.update(r["id"] for r in out["results"])
        return out

    # Force the partition path: a mutated reader that overflows only the
    # first (unpartitioned) query.
    def forcing(q):
        # Overflow every query that is not already an Area x Learning Type
        # cell (base clauses plus one relevance clause or an OR), so the
        # whole two-level partition is exercised.
        if len(q["filter"]["and"]) <= 3:
            return {"results": rows[:MAX_RETRIEVAL_ROWS], "has_more": True, "next_cursor": "x"}
        return read(q)

    import agent_memory_context_manager.lesson_retrieval_orchestrator as orch
    orch.orchestrate_lesson_retrieval(req, execute_read=forcing)
    usable = {
        r["id"] for r in rows
        if r["id"] in returned and not isinstance(normalize_lesson_row(r), LessonActivationSkip)
    }
    assert direct, "fixture must contain usable rows"
    assert direct <= usable


@pytest.mark.parametrize(("cap", "expect_ok"), [(21, True), (20, False)])
def test_read_ceiling_boundary_for_the_21_read_shape(monkeypatch, cap, expect_ok):
    import agent_memory_context_manager.lesson_retrieval_orchestrator as orch

    monkeypatch.setattr(orch, "MAX_PREFLIGHT_READS", cap)
    result = orchestrate_lesson_retrieval(
        request(capability_keywords=("testing",)),
        execute_read=_ckr6_filter_evaluating_reader(
            _stress_or_shape_rows(with_testing_lesson_overflow=True), []),
    )
    if expect_ok:
        assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
        assert result.retrieval_diagnostics["read_count"] == 21
    else:
        assert result.retrieval_diagnostics["incomplete_reason_code"] == "read-budget-exceeded"
        assert result.selected_lesson_ids == ()


@pytest.mark.parametrize("capability", [
    (), ("testing",), ("CKR6 mutation boundary",), ("fail-closed lesson preflight", "scheduling"),
    ("failure-avoidance", "quality-assurance", "deployment", "authorization-routing"),
])
def test_p6_broad_and_title_fallback_queries_have_no_partition_shape(capability):
    # Proof for the claimed P6 equivalence: for every request shape below, the
    # unpartitioned steps expose no OR/Area/Learning Type last clause, so the
    # partitioner would return nothing even if the step were marked partitionable.
    from agent_memory_context_manager.lesson_retrieval_orchestrator import (
        _partition_queries, build_escalation_query)

    for eco in ((), ("python",), ("python", "agent-os")):
        req = request(ecosystem_hints=eco, capability_keywords=capability)
        broad = build_escalation_query(req, RetrievalEscalation.WORKSPACE_SEARCH)
        assert _partition_queries(broad, crossed=False)[0] == []


# --- count-consistent replay (INFERRED distribution within measured bounds) ---
#
# Measured on 2026-11-15, counts only (26 means 26 or more): Areas Testing 26+,
# Automation 26+, Governance 23, Documentation 5, Dashboard 0, Curriculum 0;
# Learning Types Testing lesson 26+, Mistake 13, QA feedback 15,
# Scope/permission lesson 12, Deployment lesson 8, Trigger lesson 5; Testing x Testing lesson
# exactly 25; Automation x Testing lesson exactly 8.
# The remaining cells below were NOT measured. This is ONE distribution that
# satisfies every measured marginal and exact cell; others exist.
_CC_PLAN = {
    ("Testing", "Testing lesson"): 25,  # measured exactly
    ("Automation", "Testing lesson"): 8,  # measured exactly
    ("Testing", "Mistake"): 3,  # inferred
    ("Testing", "Scope/permission lesson"): 4,  # inferred
    ("Automation", "Mistake"): 10,  # inferred
    ("Automation", "QA feedback"): 5,  # inferred
    ("Automation", "Scope/permission lesson"): 3,  # inferred
    ("Governance", "QA feedback"): 10,  # inferred
    ("Governance", "Deployment lesson"): 8,  # inferred
    ("Governance", "Trigger lesson"): 5,  # inferred
    ("Documentation", "Scope/permission lesson"): 5,  # inferred
}
_CC_AREA_AT_LEAST = {"Testing": 26, "Automation": 26}
_CC_AREA_EXACT = {"Governance": 23, "Documentation": 5, "Dashboard": 0, "Curriculum": 0}
_CC_TYPE_EXACT = {"Mistake": 13, "QA feedback": 15, "Scope/permission lesson": 12,
                  "Deployment lesson": 8, "Trigger lesson": 5}


def _count_consistent_rows(extra=()):
    rows, n = [], 4000
    for (area, learning_type), count in _CC_PLAN.items():
        for _ in range(count):
            n += 1
            rows.append(_ckr6_area_row(n, area, learning_type=learning_type))
    return rows + list(extra)


def test_count_consistent_fixture_respects_every_measured_marginal_and_exact_cell():
    from collections import Counter

    by_area, by_type = Counter(), Counter()
    for (area, learning_type), count in _CC_PLAN.items():
        by_area[area] += count
        by_type[learning_type] += count
    for area, floor in _CC_AREA_AT_LEAST.items():
        assert by_area[area] >= floor
    for area, exact in _CC_AREA_EXACT.items():
        assert by_area[area] == exact
    for learning_type, exact in _CC_TYPE_EXACT.items():
        assert by_type[learning_type] == exact
    assert by_type["Testing lesson"] >= 26
    assert _CC_PLAN[("Testing", "Testing lesson")] == 25
    assert _CC_PLAN[("Automation", "Testing lesson")] == 8
    assert max(_CC_PLAN.values()) <= MAX_RETRIEVAL_ROWS  # no cell overflows
    assert len(_count_consistent_rows()) == sum(_CC_PLAN.values())


def test_count_consistent_generated_rows_use_controlled_vocabulary_and_normalize():
    # Check the rows actually generated, not the plan labels: every Area and
    # Learning Type is a controlled value, every row normalizes to a usable
    # record, and the normalized marginals equal the measured ones.
    from collections import Counter
    from agent_memory_context_manager.lesson_activation_bridge import (
        LessonRecordEvidence,
        _AREA_ECOSYSTEM,
        _LEARNING_TYPE_CAPABILITY,
        normalize_lesson_row,
    )

    rows = _count_consistent_rows()
    area_counts, type_counts, cell_counts = Counter(), Counter(), Counter()
    for row in rows:
        area = row["properties"]["Area"]["select"]["name"]
        learning_type = row["properties"]["Learning Type"]["select"]["name"]
        assert area in _AREA_ECOSYSTEM, area
        assert learning_type in _LEARNING_TYPE_CAPABILITY, learning_type
        assert isinstance(normalize_lesson_row(row), LessonRecordEvidence)
        area_counts[area] += 1
        type_counts[learning_type] += 1
        cell_counts[(area, learning_type)] += 1
    for area, floor in _CC_AREA_AT_LEAST.items():
        assert area_counts[area] >= floor
    for area, exact in _CC_AREA_EXACT.items():
        assert area_counts[area] == exact
    for learning_type, exact in _CC_TYPE_EXACT.items():
        assert type_counts[learning_type] == exact
    assert type_counts["Testing lesson"] >= 26
    assert cell_counts[("Testing", "Testing lesson")] == 25
    assert cell_counts[("Automation", "Testing lesson")] == 8
    assert set(area_counts) <= set(_AREA_ECOSYSTEM) and set(type_counts) <= set(_LEARNING_TYPE_CAPABILITY)


@pytest.mark.parametrize(
    ("label", "make_request", "reads_at_32", "code_at_32"),
    [
        ("testing-only miss path", lambda: request(capability_keywords=("CKR6 mutation boundary",)), 27, "row-bound-exceeded"),
        ("QA shape miss path", _ckr6_qa_request, 27, "row-bound-exceeded"),
        ("OR shape miss path", lambda: request(capability_keywords=()), 30, "row-bound-exceeded"),
    ],
)
def test_count_consistent_replay_miss_paths(monkeypatch, label, make_request, reads_at_32, code_at_32):
    # Replay on the count-consistent fixture, not a live execution path.
    import agent_memory_context_manager.lesson_retrieval_orchestrator as orch

    result = orchestrate_lesson_retrieval(
        make_request(), execute_read=_ckr6_filter_evaluating_reader(_count_consistent_rows(), [])
    )
    assert result.retrieval_diagnostics["read_count"] == reads_at_32, label
    assert result.retrieval_diagnostics["incomplete_reason_code"] == code_at_32
    assert result.selected_lesson_ids == ()
    monkeypatch.setattr(orch, "MAX_PREFLIGHT_READS", 20)
    capped = orchestrate_lesson_retrieval(
        make_request(), execute_read=_ckr6_filter_evaluating_reader(_count_consistent_rows(), [])
    )
    assert capped.retrieval_diagnostics["incomplete_reason_code"] == "read-budget-exceeded"
    assert capped.selected_lesson_ids == ()


def test_count_consistent_replay_testing_only_hit_completes_in_7_reads():
    rows = _count_consistent_rows(
        [_ckr6_area_row(9001, "Testing", relevant=True, learning_type="Mistake")]
    )
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, [])
    )
    assert "incomplete_reason_code" not in result.retrieval_diagnostics
    assert "LL-9001" in result.selected_lesson_ids
    assert result.retrieval_diagnostics["read_count"] == 7


def test_count_consistent_replay_cross_area_or_needs_21_reads_because_testing_lesson_has_33_rows(monkeypatch):
    # Testing lesson totals 33 rows on this fixture (25 + 8), so the Learning
    # Type alternative overflows and is partitioned by Area.
    import agent_memory_context_manager.lesson_retrieval_orchestrator as orch

    rows = _count_consistent_rows()
    result = orchestrate_lesson_retrieval(
        request(capability_keywords=("testing",)),
        execute_read=_ckr6_filter_evaluating_reader(rows, []),
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids
    assert result.retrieval_diagnostics["read_count"] == 21
    monkeypatch.setattr(orch, "MAX_PREFLIGHT_READS", 20)
    capped = orchestrate_lesson_retrieval(
        request(capability_keywords=("testing",)),
        execute_read=_ckr6_filter_evaluating_reader(rows, []),
    )
    assert capped.retrieval_diagnostics["incomplete_reason_code"] == "read-budget-exceeded"
    assert capped.selected_lesson_ids == ()

def test_terminal_query_bucket_has_only_closed_controlled_values():
    import agent_memory_context_manager.lesson_retrieval_orchestrator as orch
    base = {"filter": {"and": [
        {"property": "Surface Before Work?", "checkbox": {"equals": True}},
        {"property": "Status", "select": {"does_not_equal": "Archived note"}},
    ]}}
    assert orch._terminal_query_bucket(base) == "workspace"
    query = {**base, "filter": {"and": [
        *base["filter"]["and"],
        {"or": [{"property": "Area", "select": {"equals": "Testing"}},
                {"property": "Learning Type", "select": {"equals": "Testing lesson"}}]},
    ]}}
    assert orch._terminal_query_bucket(query) == "broad-or"
    query["filter"]["and"][-1] = {"property": "Area", "select": {"equals": "Testing"}}
    assert orch._terminal_query_bucket(query) == "area:Testing"
    query["filter"]["and"].append(
        {"property": "Learning Type", "select": {"equals": "Testing lesson"}}
    )
    assert orch._terminal_query_bucket(query) == "area:Testing/type:Testing lesson"
    reversed_query = {"filter": {"and": [
        *base["filter"]["and"],
        {"property": "Learning Type", "select": {"equals": "Testing lesson"}},
        {"property": "Area", "select": {"equals": "Testing"}},
    ]}}
    assert orch._terminal_query_bucket(reversed_query) == (
        "area:Testing/type:Testing lesson"
    )
    reversed_query["filter"]["and"][-1]["select"]["equals"] = "SENSITIVE_UNTRUSTED"
    assert orch._terminal_query_bucket(reversed_query) == "unobserved"
    query["filter"]["and"][-1]["select"]["equals"] = "SENSITIVE_UNTRUSTED"
    assert orch._terminal_query_bucket(query) == "unobserved"
    assert orch._terminal_query_bucket({"filter": {"or": []}}) == "known-reference"


def test_terminal_leaf_overflow_reports_exact_bucket_without_selecting():
    req = request(capability_keywords=("testing",))
    seen = []
    def read(query):
        seen.append(query)
        return {"results": [_lesson_row("LL-1")] * 25,
                "has_more": True, "next_cursor": "private-cursor"}
    result = orchestrate_lesson_retrieval(req, execute_read=read)
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "row-bound-exceeded"
    # After OR -> Automation -> first exact controlled type cell.
    assert result.retrieval_diagnostics["terminal_query_bucket"] == (
        "area:Automation/type:Deployment lesson"
    )
    assert result.retrieval_diagnostics["read_count"] == len(seen) == 3


def test_terminal_read_budget_diagnostic_still_fails_closed(monkeypatch):
    import agent_memory_context_manager.lesson_retrieval_orchestrator as orch
    monkeypatch.setattr(orch, "MAX_PREFLIGHT_READS", 1)
    result = orchestrate_lesson_retrieval(
        request(capability_keywords=("testing",)),
        execute_read=lambda _query: {"results": [_lesson_row("LL-1")] * 25,
                                     "has_more": True, "next_cursor": "private"},
    )
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "read-budget-exceeded"
    assert result.retrieval_diagnostics["terminal_query_bucket"] == "area:Automation"


