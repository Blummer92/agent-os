"""CKR11 complete-snapshot REPLACEMENT evaluation (Option 2): the relevance
retrieval cascade is replaced by one canonical complete bounded snapshot.

Fail-first: positive/boundary tests fail on main f469cb06. Fixtures are the
repo's saved synthetic count-consistent fixture plus labeled synthetic
extensions; the real 87-row corpus fixture is unavailable (see evidence pack).
"""

from copy import deepcopy

import pytest

import agent_memory_context_manager.lesson_retrieval_orchestrator as orch
from agent_memory_context_manager.lesson_preflight import (
    KnowledgeCurrentness,
    LessonRetrievalStatus,
)
from agent_memory_context_manager.coding_knowledge_selection import RetrievalEscalation
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    orchestrate_lesson_retrieval,
)

from agent_memory_context_manager.lesson_activation_bridge import (
    _AREA_ECOSYSTEM,
    _LEARNING_TYPE_CAPABILITY,
    normalize_lesson_row,
)
from agent_memory_context_manager.lesson_preflight import LessonRecordEvidence
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    build_escalation_query,
)

from test_lesson_retrieval_orchestrator import (
    _ckr6_area_row,
    _ckr6_filter_evaluating_reader,
    _ckr6_matches_provider_filter,
    _ckr6_qa_request,
    _ckr6_testing_request,
    _count_consistent_rows,
    _lesson_row,
    _select,
    request,
)

_EXTRA_AREAS = ("Documentation", "Governance", "Curriculum", "Automation", "Testing")
_EXTRA_TYPES = ("Mistake", "QA feedback", "Deployment lesson", "Trigger lesson")


def _extra_rows(count, *, start=7000):
    rows, n = [], start
    for i in range(count):
        n += 1
        rows.append(
            _ckr6_area_row(
                n, _EXTRA_AREAS[i % len(_EXTRA_AREAS)],
                learning_type=_EXTRA_TYPES[i % len(_EXTRA_TYPES)],
            )
        )
    return rows


def _planted(n=9001, area="Documentation"):
    return _ckr6_area_row(n, area, relevant=True, learning_type="Mistake")


# --- positive ---

def test_single_snapshot_retrieves_relevant_lesson_from_complete_corpus():
    # FAIL-FIRST. 86 saved-fixture rows + 1 planted = 87 rows, 1 read.
    rows = _count_consistent_rows() + [_planted()]
    assert len(rows) == 87
    calls = []
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, calls)
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert "LL-9001" in result.selected_lesson_ids
    assert len(calls) == 1
    assert calls[0]["page_size"] == 100
    assert result.retrieval_diagnostics["read_count"] == 1
    assert "incomplete_reason_code" not in result.retrieval_diagnostics
    selected = result.selection.selected[0].candidate
    assert selected.source_revision == "2026-11-04T12:00:00.000Z"
    assert selected.canonical_github_refs


def test_cross_area_lessons_are_all_candidates_from_one_snapshot():
    # FAIL-FIRST. Relevant lessons in three Areas all reach CKR2 from the
    # single snapshot; the cascade's area vocabulary no longer gates recall.
    rows = _count_consistent_rows() + [
        _planted(9001, "Documentation"),
        _planted(9002, "Curriculum"),
        _planted(9003, "Governance"),
    ]
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, [])
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert {"LL-9001", "LL-9002", "LL-9003"} <= set(result.selected_lesson_ids)


def test_snapshot_paginates_the_complete_cursor_chain():
    # FAIL-FIRST. 120 rows -> 2 pages of 100; relevant row on page 2.
    rows = _count_consistent_rows() + _extra_rows(33) + [_planted()]
    assert len(rows) == 120
    calls = []
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, calls)
    )
    assert "LL-9001" in result.selected_lesson_ids
    assert len(calls) == 2
    assert calls[1]["start_cursor"] == "100"
    assert result.retrieval_diagnostics["read_count"] == 2


def test_empty_complete_snapshot_is_a_genuine_miss():
    calls = []
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader([], calls)
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.retrieval_escalation is RetrievalEscalation.MANUAL_REVIEW
    assert result.retrieval_diagnostics["candidate_count"] == 0
    assert "incomplete_reason_code" not in result.retrieval_diagnostics
    assert len(calls) == 1


def test_known_reference_lookup_is_preserved_and_composes_with_snapshot():
    # FAIL-FIRST. Exact-ID lookup still resolves referenced lessons first.
    rows = _count_consistent_rows()
    calls = []

    def read(query):
        calls.append(query)
        import json as _json
        if "Lesson ID" in _json.dumps(query["filter"]):
            return {"results": [rows[0]], "has_more": False}
        return _ckr6_filter_evaluating_reader(rows, [])(query)

    result = orchestrate_lesson_retrieval(
        request(known_knowledge_refs=("LL-4001",)),
        execute_read=read,
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert "LL-4001" in result.selected_lesson_ids
    # The first read is the exact Lesson ID lookup, not the snapshot.
    assert "Lesson ID" in __import__("json").dumps(calls[0]["filter"])


# --- boundary ---

def test_exactly_100_rows_complete_in_one_page():
    rows = _count_consistent_rows() + _extra_rows(13) + [_planted()]
    assert len(rows) == 100
    calls = []
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, calls)
    )
    assert "LL-9001" in result.selected_lesson_ids
    assert len(calls) == 1


def test_exactly_500_rows_complete_at_the_five_page_bound():
    rows = _count_consistent_rows() + _extra_rows(413) + [_planted()]
    assert len(rows) == 500
    calls = []
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, calls)
    )
    assert "LL-9001" in result.selected_lesson_ids
    assert len(calls) == 5
    assert result.retrieval_diagnostics["read_count"] == 5


# --- negative / fail closed ---

def test_501_rows_fail_closed_without_truncation():
    rows = _count_consistent_rows() + _extra_rows(414) + [_planted()]
    assert len(rows) == 501
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, [])
    )
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "row-bound-exceeded"
    assert "lesson-read-incomplete" in result.selection_reason_codes


def test_oversized_supplied_page_is_rejected_not_truncated():
    def read(_query):
        return {"results": [_lesson_row(f"LL-{n}") for n in range(1, 102)], "has_more": False}
    result = orchestrate_lesson_retrieval(_ckr6_testing_request(), execute_read=read)
    assert result.selected_lesson_ids == ()
    assert "lesson-read-incomplete" in result.selection_reason_codes


def test_missing_repeated_and_malformed_cursors_fail_closed():
    rows = _count_consistent_rows() + _extra_rows(33)
    cases = (
        ({"results": rows[:100], "has_more": True, "next_cursor": None}, "missing-cursor"),
        ({"results": rows[:10], "has_more": True, "next_cursor": "x"}, "repeated-cursor"),
        ({"results": [], "has_more": "true"}, "malformed-pagination"),
        ({"results": [], "has_more": True, "next_cursor": 123}, "malformed-pagination"),
    )
    for page, code in cases:
        result = orchestrate_lesson_retrieval(
            _ckr6_testing_request(), execute_read=lambda _q, _p=page: _p
        )
        assert result.selected_lesson_ids == (), code
        assert result.retrieval_diagnostics["incomplete_reason_code"] == code, code


def test_budget_exhaustion_fails_closed(monkeypatch):
    monkeypatch.setattr(orch, "MAX_PREFLIGHT_READS", 1)
    rows = _count_consistent_rows() + _extra_rows(33) + [_planted()]
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, [])
    )
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "read-budget-exceeded"
    assert result.retrieval_diagnostics["read_count"] == 1


def test_provider_errors_are_sanitized_and_admit_nothing():
    for exc, reason in (
        (ConnectionError("x"), "lesson-read-connection-error"),
        (TimeoutError("x"), "lesson-read-timeout"),
        (RuntimeError("secret-token=must-not-leak"), "lesson-read-runtime-error"),
        (RuntimeError("notion-http-500"), "notion-http-500"),
    ):
        def read(_q, _e=exc):
            raise _e
        result = orchestrate_lesson_retrieval(_ckr6_testing_request(), execute_read=read)
        assert result.selected_lesson_ids == ()
        assert reason in result.selection_reason_codes
        assert all("secret-token" not in r for r in result.selection_reason_codes)


def test_no_partial_snapshot_reaches_ckr2_after_a_failed_read(monkeypatch):
    seen = []
    real = orch._bound_relevant_lessons

    def spy(req, accumulated):
        seen.append(list(accumulated))
        return real(req, accumulated)

    monkeypatch.setattr(orch, "_bound_relevant_lessons", spy)
    rows = _count_consistent_rows() + _extra_rows(33) + [_planted()]
    inner = _ckr6_filter_evaluating_reader(rows, [])
    state = {"n": 0}

    def read(query):
        state["n"] += 1
        if state["n"] == 2:
            raise ConnectionError("provider failure")
        return inner(query)

    result = orchestrate_lesson_retrieval(_ckr6_testing_request(), execute_read=read)
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["candidate_count"] == 0
    assert seen == []  # the bound/selection stage never ran at all


# --- identity, revision, dedup, no fabrication ---

def test_duplicate_records_collapse_and_conflicting_revisions_survive(monkeypatch):
    # FAIL-FIRST. Identical record twice collapses; same ID with a different
    # revision is kept so CKR2's conflict handling sees it.
    rows = _count_consistent_rows()
    rows = rows + [deepcopy(rows[-1])]
    stale = _planted()
    stale["last_edited_time"] = "2026-09-01T00:00:00.000Z"
    rows = rows + [stale, _planted()]
    # Pin the accumulation-level dedup itself (R1 #2425): the accumulated
    # list must contain no exact-duplicate records, while both revisions of
    # the conflicting identity survive.
    seen = []
    real = orch._bound_relevant_lessons

    def spy(req, accumulated):
        seen.append(list(accumulated))
        return real(req, accumulated)

    monkeypatch.setattr(orch, "_bound_relevant_lessons", spy)
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, [])
    )
    assert seen
    accumulated = seen[0]
    assert len(accumulated) == len(set(accumulated)), "exact-duplicate records accumulated"
    assert sum(1 for lesson in accumulated if lesson.lesson_id == "LL-9001") == 2
    # Conflicting identity blocks clean admission rather than picking one.
    assert result.lesson_retrieval_status is not LessonRetrievalStatus.SUFFICIENT
    assert "LL-9001" not in result.selected_lesson_ids


def test_no_lesson_or_revision_is_fabricated():
    # Rows missing identity or revision are skipped, never invented; every
    # selected lesson comes from the fixture with its provider revision.
    no_id = _ckr6_area_row(9102, "Documentation", learning_type="Mistake")
    no_id["properties"]["Lesson ID"] = {"type": "rich_text", "rich_text": []}
    no_rev = _ckr6_area_row(9104, "Documentation", learning_type="Mistake")
    del no_rev["last_edited_time"]
    rows = _count_consistent_rows() + [no_id, no_rev, _planted()]
    fixture_ids = {
        r["properties"]["Lesson ID"]["rich_text"][0]["plain_text"]
        for r in rows
        if r["properties"]["Lesson ID"]["rich_text"]
    }
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, [])
    )
    assert "LL-9001" in result.selected_lesson_ids
    assert result.retrieval_diagnostics["missing_identity_rows"] == 1
    assert result.retrieval_diagnostics["missing_revision_rows"] == 1
    assert set(result.selected_lesson_ids) <= fixture_ids
    for item in result.selection.selected:
        assert item.candidate.source_revision == "2026-11-04T12:00:00.000Z"
        assert item.candidate.currentness is KnowledgeCurrentness.CURRENT


def test_relevant_lesson_with_unverifiable_source_link_blocks_admission():
    no_source = _planted(9103)
    no_source["properties"]["Source Link"] = {"type": "url", "url": None}
    rows = _count_consistent_rows() + [no_source]
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, [])
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert result.selected_lesson_ids == ()
    assert "unverifiable-relevant-candidate" in result.selection_reason_codes


# --- migration ports and invariants (reviewer conditions, 2026-11-16) ---
# These tests land BEFORE the cascade-contract retirements they supersede;
# the retire manifest maps each retired test here or marks it cascade-only.


def _vocab_rows():
    """Two rows for every controlled Area x Learning Type combination."""
    rows, n = [], 8000
    for area in sorted(_AREA_ECOSYSTEM):
        for learning_type in sorted(_LEARNING_TYPE_CAPABILITY):
            for _ in range(2):
                n += 1
                rows.append(_ckr6_area_row(n, area, learning_type=learning_type))
    return rows


def test_snapshot_accumulates_exactly_the_direct_filtered_corpus(monkeypatch):
    # Supersedes the retired partition-equivalence matrix
    # (test_partitioned_union_equals_direct_filter_for_every_area_and_learning_type):
    # with every controlled combination present, the snapshot's accumulated
    # record set equals a direct unbounded filtered read of the same rows.
    rows = _vocab_rows()
    assert len(rows) == 2 * len(_AREA_ECOSYSTEM) * len(_LEARNING_TYPE_CAPABILITY)
    assert len(rows) <= 500  # the invariant is pinned INSIDE the row bound
    seen = []
    real = orch._bound_relevant_lessons

    def spy(req, accumulated):
        seen.append(list(accumulated))
        return real(req, accumulated)

    monkeypatch.setattr(orch, "_bound_relevant_lessons", spy)
    req = _ckr6_testing_request()
    orchestrate_lesson_retrieval(req, execute_read=_ckr6_filter_evaluating_reader(rows, []))
    query = build_escalation_query(req, RetrievalEscalation.WORKSPACE_SEARCH)
    expected = set()
    for row in rows:
        if _ckr6_matches_provider_filter(row, query["filter"]):
            normalized = normalize_lesson_row(row)
            if isinstance(normalized, LessonRecordEvidence):
                expected.add(normalized)
    assert seen, "selection never saw the accumulated corpus"
    assert set(seen[0]) == expected


def test_workspace_snapshot_read_is_single_and_unpartitioned():
    # Supersedes test_broad_workspace_search_step_is_not_partitioned: the
    # corpus read is exactly one snapshot chain - identical surface+status
    # filter on every page, page_size 100, no per-area partition queries.
    rows = _count_consistent_rows()
    calls = []
    orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, calls)
    )
    expected_filter = {
        "and": [
            {"property": "Surface Before Work?", "checkbox": {"equals": True}},
            {"property": "Status", "select": {"does_not_equal": "Archived note"}},
        ]
    }
    assert calls, "expected at least the snapshot read"
    assert all(c["filter"] == expected_filter for c in calls)
    assert all(c["page_size"] == 100 for c in calls)
    assert len(calls) == 1  # the 86-row fixture fits one page


def test_diagnostics_report_every_skip_reason_by_name():
    # Pins complete skip accounting: a row failing normalization for a reason
    # outside the four legacy buckets must still appear, by name, and the
    # named reasons must sum to skipped_rows.
    bad = _lesson_row("LL-7700")
    bad["properties"]["Lesson Learned"] = {"type": "title", "title": []}
    rows = _count_consistent_rows() + [bad]
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, [])
    )
    diagnostics = result.retrieval_diagnostics
    assert diagnostics["skip_reasons"].get("missing-title") == 1
    assert diagnostics["skipped_rows"] == sum(diagnostics["skip_reasons"].values())


def test_known_reference_read_failure_admits_nothing_and_reports_incomplete():
    # Port of the cascade no-partial-after-subquery-failure pins: a provider
    # failure at the known-reference read admits nothing and fails closed.
    def read(_query):
        raise ConnectionError("provider down")

    result = orchestrate_lesson_retrieval(
        request(known_knowledge_refs=("LL-4001",)), execute_read=read
    )
    assert result.selected_lesson_ids == ()
    assert "lesson-read-connection-error" in result.selection_reason_codes
    assert "lesson-retrieval-unavailable-specialized-knowledge-required" in result.selection_reason_codes


@pytest.mark.parametrize("build_request", [_ckr6_testing_request, _ckr6_qa_request])
def test_miss_after_complete_snapshot_is_honest_and_forces_manual_review(build_request):
    # Port of the cascade miss-path pins: a complete snapshot with no
    # relevant eligible lesson is INSUFFICIENT with no-relevant-candidate,
    # no incomplete code, and retrieval_escalation forced to MANUAL_REVIEW.
    result = orchestrate_lesson_retrieval(
        build_request(), execute_read=_ckr6_filter_evaluating_reader(_count_consistent_rows(), [])
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert "incomplete_reason_code" not in result.retrieval_diagnostics
    assert "no-relevant-candidate" in result.selection_reason_codes
    assert result.retrieval_escalation is RetrievalEscalation.MANUAL_REVIEW


def test_selection_stays_bounded_when_relevant_lessons_exceed_the_candidate_budget():
    # Pins the CKR2 candidate bound on the snapshot path (kills bound-skip
    # mutants): 25 eligible relevant lessons enter, the bound still holds.
    rows = [
        _ckr6_area_row(6000 + i, "Testing", relevant=True, learning_type="Testing lesson")
        for i in range(25)
    ]
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(), execute_read=_ckr6_filter_evaluating_reader(rows, [])
    )
    assert result.candidate_count <= 20
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT


def test_bad_unrelated_corpus_row_is_skipped_without_losing_valid_lesson():
    # The complete 88-row corpus includes one invalid guidance field that
    # used to abort normalization after an otherwise complete snapshot.
    good = _planted()
    bad = _lesson_row("LL-8701")
    bad["properties"]["Guardrail"] = {"type": "rich_text", "rich_text": [{"plain_text": "invalid\\ncontrol"}]}
    rows = _count_consistent_rows() + [bad, good]
    assert len(rows) == 88
    calls = []
    result = orchestrate_lesson_retrieval(
        _ckr6_testing_request(),
        execute_read=_ckr6_filter_evaluating_reader(rows, calls),
    )
    assert len(calls) == 1
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert "LL-9001" in result.selected_lesson_ids
    assert "LL-8701" not in result.selected_lesson_ids
    assert result.retrieval_diagnostics["skip_reasons"].get(
        "oversized-or-malformed-field", 0
    ) >= 1
    assert "incomplete_reason_code" not in result.retrieval_diagnostics
