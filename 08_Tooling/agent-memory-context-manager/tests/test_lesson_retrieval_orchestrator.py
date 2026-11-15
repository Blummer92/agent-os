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
    assert len(calls) == 1
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


def _ckr6_area_row(n, area, *, relevant=False):
    row = _lesson_row(f"LL-{n}")
    row["properties"]["Area"] = _select(area)
    row["properties"]["Learning Type"] = _select("Mistake")
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
    assert len(calls) == 1 + MAX_RETRIEVAL_PAGES


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
