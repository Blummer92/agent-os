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


def test_ckr11_explicit_single_page_response_is_unchanged():
    calls = []
    def read(query):
        calls.append(dict(query))
        return {"results": [_lesson_row("LL-42")], "has_more": False}
    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-42",)
    assert len(calls) == 1


def test_ckr11_missing_has_more_fails_closed_with_truthful_code():
    # P6 fix: missing has_more is malformed pagination, not a complete page.
    result = orchestrate_lesson_retrieval(
        request(), execute_read=lambda _q: {"results": [_lesson_row("LL-42")]}
    )
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "malformed-pagination"


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






def _budget_stop_bucket(monkeypatch, cap, req=None, reader=None):
    import agent_memory_context_manager.lesson_retrieval_orchestrator as orch
    monkeypatch.setattr(orch, "MAX_PREFLIGHT_READS", cap)
    seen = []

    def read(query):
        seen.append(query)
        if reader is not None:
            return reader(query)
        return {"results": [_lesson_row("LL-1")] * 25,
                "has_more": True, "next_cursor": "private"}

    result = orchestrate_lesson_retrieval(
        req if req is not None else request(capability_keywords=("testing",)),
        execute_read=read,
    )
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "read-budget-exceeded"
    assert result.retrieval_diagnostics["read_count"] == len(seen) == cap
    return result.retrieval_diagnostics["terminal_query_bucket"]

def test_max_preflight_reads_constant_is_pinned_at_32():
    # Restored coverage (GAP 1): A must keep the read budget pinned at 32.
    assert MAX_PREFLIGHT_READS == 32


def test_budget_stop_names_last_issued_query_not_the_refused_one(monkeypatch):
    # Restored coverage (GAP 1b): execute the surviving helper. With known
    # knowledge refs and the budget capped at 1, the known-reference read is
    # ISSUED (bucket "known-reference") and the workspace snapshot read is
    # REFUSED (bucket "workspace"). The diagnostic must name the issued
    # query; a mutant naming the refused snapshot query would report
    # "workspace" and fail this pin.
    req = request(known_knowledge_refs=("LL-1",))
    complete_page = lambda _q: {"results": [], "has_more": False}
    assert _budget_stop_bucket(monkeypatch, 1, req, complete_page) == "known-reference"


def test_terminal_row_overflow_reports_exact_bucket_and_read_count_without_selecting():
    # Restored coverage (GAP 2): exact terminal bucket and read_count pins.
    # Full 100-row pages with advancing cursors overflow the snapshot row
    # bound at exactly 5 reads; the bucket names the issued snapshot query
    # and nothing is selected.
    seen = []

    def read(query):
        seen.append(query)
        return {
            "results": [_lesson_row(f"LL-{len(seen)}x{i}") for i in range(100)],
            "has_more": True,
            "next_cursor": f"cursor-{len(seen)}",
        }

    result = orchestrate_lesson_retrieval(
        request(capability_keywords=("testing",)), execute_read=read
    )
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "row-bound-exceeded"
    assert result.retrieval_diagnostics["terminal_query_bucket"] == "workspace"
    assert result.retrieval_diagnostics["read_count"] == len(seen) == 5


def _adapter_executor(pages):
    """Real adapter + ordered fake provider pages, via lesson_reader_composition.

    The sibling packages are imported here, not at module scope: CI runs
    each 08_Tooling package's tests with only that package's src on
    sys.path, and agent_os_execution_service is not an installed
    distribution in that environment, so a module-level import fails
    collection of this whole module (and of test_lesson_snapshot_replacement,
    which imports helpers from here). This is the same sys.path.insert
    convention test_provider_failure_detail_survives_canonical_reader_chain
    already uses in this file; repo root is included because
    agent_os_execution_service.models resolves
    scripts.agent_os_execution_capabilities through the shared namespace
    package.
    """
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
    from workflow_scheduler.adapters.notion_readonly_adapter import (
        NotionReadOnlyAdapter,
    )

    state = {"pages": list(pages)}

    def post(url, headers, body, timeout):
        return dict(state["pages"].pop(0))

    adapter = NotionReadOnlyAdapter(
        token="fake-token-for-qa", http_post_query_data_source=post
    )
    return build_lesson_read_executor(data_source_id="ds-qa", adapter=adapter)


def _planted_testing_row():
    return _ckr6_area_row(9001, "Testing", relevant=True, learning_type="Mistake")


def test_adapter_missing_has_more_fails_closed_with_malformed_pagination():
    # #4016 R-1: a provider page without has_more must not become an
    # apparently complete snapshot through the canonical adapter.
    executor = _adapter_executor([{"results": [_planted_testing_row()]}])
    result = orchestrate_lesson_retrieval(_ckr6_testing_request(), execute_read=executor)
    assert result.selected_lesson_ids == ()
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.retrieval_diagnostics.get("incomplete_reason_code") == "malformed-pagination"
    assert "notion-malformed-pagination" in result.selection_reason_codes


def test_adapter_wrong_type_has_more_fails_closed_with_malformed_pagination():
    executor = _adapter_executor(
        [{"results": [_planted_testing_row()], "has_more": "false", "next_cursor": None}]
    )
    result = orchestrate_lesson_retrieval(_ckr6_testing_request(), execute_read=executor)
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics.get("incomplete_reason_code") == "malformed-pagination"


def test_adapter_missing_has_more_on_second_page_fails_closed():
    # #4016 R-1 (late page): a valid first page must not leave a lesson
    # selected when the second page's pagination metadata is missing.
    executor = _adapter_executor(
        [
            {
                "results": [_planted_testing_row()],
                "has_more": True,
                "next_cursor": "c1",
            },
            {"results": [_ckr6_area_row(7001, "Documentation", learning_type="Mistake")]},
        ]
    )
    result = orchestrate_lesson_retrieval(_ckr6_testing_request(), execute_read=executor)
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics.get("incomplete_reason_code") == "malformed-pagination"


def test_adapter_oversized_page_fails_closed_with_row_bound():
    # #4016 R-2: an oversized provider page is rejected by the snapshot's
    # row bound instead of being silently sliced by the adapter.
    rows = [
        _ckr6_area_row(7000 + i, "Documentation", learning_type="Mistake")
        for i in range(100)
    ]
    rows.append(_planted_testing_row())
    executor = _adapter_executor([{"results": rows, "has_more": False}])
    result = orchestrate_lesson_retrieval(_ckr6_testing_request(), execute_read=executor)
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics.get("incomplete_reason_code") == "row-bound-exceeded"



# #4011 finite terminal-page diagnostics on the merged snapshot path.
@pytest.mark.parametrize("count,bucket", [(24,"0-99"),(25,"0-99"),(26,"0-99"),(99,"0-99"),(100,"100")])
def test_4011_snapshot_missing_cursor_signature(count, bucket):
    seen = []
    def read(query):
        seen.append(query)
        return {"results": [_lesson_row("LL-42")] * count,
                "has_more": True, "next_cursor": None}
    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    diag = result.retrieval_diagnostics
    assert len(seen) == 1
    assert diag["incomplete_reason_code"] == "missing-cursor"
    assert diag["terminal_query_bucket"] == "workspace"
    assert diag["terminal_page_row_count_bucket"] == bucket
    assert diag["terminal_page_has_more"] == "true"
    assert diag["terminal_page_cursor_present"] is False
    assert result.selected_lesson_ids == ()


def test_4011_oversize_snapshot_signature():
    result = orchestrate_lesson_retrieval(request(), execute_read=lambda q: {
        "results": [_lesson_row("LL-42")] * 101,
        "has_more": False, "next_cursor": None})
    diag = result.retrieval_diagnostics
    assert diag["incomplete_reason_code"] == "row-bound-exceeded"
    assert diag["terminal_page_row_count_bucket"] == "over-100"
    assert diag["terminal_page_has_more"] == "false"
    assert diag["terminal_page_cursor_present"] is False
    assert result.selected_lesson_ids == ()


@pytest.mark.parametrize("metadata", [{}, {"has_more": None}, {"has_more": "false"}, {"has_more": 0}])
def test_4011_missing_or_malformed_completion_flag_reports_invalid(metadata):
    result = orchestrate_lesson_retrieval(request(), execute_read=lambda _q: {
        "results": [_lesson_row("LL-42")], **metadata,
    })
    assert result.selected_lesson_ids == ()
    diagnostics = result.retrieval_diagnostics
    assert diagnostics["incomplete_reason_code"] == "malformed-pagination"
    assert diagnostics["terminal_page_has_more"] == "invalid"
    assert diagnostics["terminal_page_row_count_bucket"] == "0-99"


@pytest.mark.parametrize("count", [24,25,26,100])
def test_4011_complete_snapshot_omits_signature(count):
    result = orchestrate_lesson_retrieval(request(), execute_read=lambda q: {
        "results": [_lesson_row("LL-42")] * count, "has_more": False})
    assert "incomplete_reason_code" not in result.retrieval_diagnostics
    assert not any(k.startswith("terminal_page_") for k in result.retrieval_diagnostics)


def test_4011_malformed_page_signature_no_leak():
    result = orchestrate_lesson_retrieval(request(), execute_read=lambda q: {
        "results": "PRIVATE_UNTRUSTED", "has_more": "PRIVATE_UNTRUSTED",
        "next_cursor": {"token": "PRIVATE_UNTRUSTED"}})
    d = result.retrieval_diagnostics
    assert d["incomplete_reason_code"] == "malformed-page"
    assert d["terminal_page_row_count_bucket"] == "unobserved"
    assert d["terminal_page_has_more"] == "invalid"
    assert d["terminal_page_cursor_present"] is False
    assert "PRIVATE" not in str(d)


def test_4011_no_stale_page_metadata_after_failed_continuation():
    def read(q):
        if "start_cursor" not in q:
            return {"results": [_lesson_row("LL-42")],
                    "has_more": True, "next_cursor": "SECRET_CURSOR"}
        raise ConnectionError("SECRET_EXCEPTION")
    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    assert result.selected_lesson_ids == ()
    assert not any(k.startswith("terminal_page_") for k in result.retrieval_diagnostics)
    assert "SECRET" not in str(result.retrieval_diagnostics)


def test_4011_read_budget_stop_retains_issued_page_signature(monkeypatch):
    import agent_memory_context_manager.lesson_retrieval_orchestrator as orch
    monkeypatch.setattr(orch, "MAX_PREFLIGHT_READS", 1)
    seen = []
    def read(q):
        seen.append(q)
        return {"results": [], "has_more": False}
    result = orchestrate_lesson_retrieval(
        request(known_knowledge_refs=("LL-1",)), execute_read=read)
    d = result.retrieval_diagnostics
    assert len(seen) == d["read_count"] == 1
    assert d["incomplete_reason_code"] == "read-budget-exceeded"
    assert d["terminal_query_bucket"] == "known-reference"
    assert d["terminal_page_row_count_bucket"] == "0-24"
    assert d["terminal_page_has_more"] == "false"
    assert d["terminal_page_cursor_present"] is False


def test_4011_snapshot_late_page_overflow_signature_is_latest_only():
    seen = []
    def read(q):
        seen.append(q)
        if len(seen) == 1:
            return {"results": [_lesson_row("LL-42")] * 100,
                    "has_more": True, "next_cursor": "SECRET_CURSOR"}
        return {"results": [_lesson_row("LL-42")] * 101,
                "has_more": False, "next_cursor": None}
    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    d = result.retrieval_diagnostics
    assert len(seen) == 2
    assert d["incomplete_reason_code"] == "row-bound-exceeded"
    assert d["terminal_page_row_count_bucket"] == "over-100"
    assert d["terminal_page_has_more"] == "false"
    assert d["terminal_page_cursor_present"] is False
    assert "SECRET_CURSOR" not in str(d)


def test_4011_snapshot_exact_500_with_more_is_incomplete():
    seen = []
    def read(q):
        seen.append(q)
        return {"results": [_lesson_row("LL-42")] * 100,
                "has_more": True, "next_cursor": f"SECRET-{len(seen)}"}
    result = orchestrate_lesson_retrieval(request(), execute_read=read)
    d = result.retrieval_diagnostics
    assert len(seen) == 5
    assert d["incomplete_reason_code"] == "row-bound-exceeded"
    assert d["terminal_query_bucket"] == "workspace"
    assert d["terminal_page_row_count_bucket"] == "100"
    assert d["terminal_page_has_more"] == "true"
    assert d["terminal_page_cursor_present"] is True
    assert result.selected_lesson_ids == ()

