"""#4026: ambiguous generic lesson ties cannot authorize CKR6 preflight.

Tests the production retrieval path without modifying historical PR #4068
replay fixtures or asserting human-adjudicated relevance.
"""

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest,
    RetrievalEscalation,
)
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    orchestrate_lesson_retrieval,
)
from test_lesson_retrieval_orchestrator import _lesson_row, _title


def request(**overrides):
    data = {
        "task_reference": "Repair CKR6 33-way lesson relevance and sufficiency",
        "capability_keywords": ("testing",),
        "specialized_knowledge_required": True,
    }
    data.update(overrides)
    return CodingKnowledgeRequest(**data)


def read(rows):
    def executor(_query):
        return {"results": list(rows), "has_more": False, "next_cursor": None}
    return executor


def test_four_generic_candidates_require_review_without_selection():
    result = orchestrate_lesson_retrieval(
        request(), execute_read=read([_lesson_row(f"LL-{n}") for n in range(10, 14)])
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert result.selection_reason_codes == ("generic-relevance-unverified",)
    assert result.selected_count == 0
    assert result.selected_lesson_ids == ()
    assert result.knowledge_refs == ()
    assert result.canonical_github_refs == ()
    assert result.selection is None
    assert result.retrieval_escalation is RetrievalEscalation.MANUAL_REVIEW
    assert result.handoff_projection["stop_conditions"] == [
        "coding-knowledge:generic-relevance-unverified"
    ]
    assert result.retrieval_diagnostics["best_bucket_tied_identities"] == 4
    assert result.retrieval_diagnostics["selection_basis"] == "generic-tie-lexical-cut"
    assert result.retrieval_diagnostics["read_count"] == 1
    assert not result.authority_created
    assert not result.github_write_performed
    assert not result.notion_write_performed


def test_thirty_three_way_generic_tie_remains_fail_closed_after_input_shuffle():
    rows = [_lesson_row(f"LL-{n}") for n in range(10, 43)]
    first = orchestrate_lesson_retrieval(request(), execute_read=read(rows))
    second = orchestrate_lesson_retrieval(request(), execute_read=read(rows[::-1]))
    for result in (first, second):
        assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
        assert result.selected_lesson_ids == ()
        assert result.retrieval_diagnostics["best_bucket_tied_identities"] == 33
        assert result.retrieval_diagnostics["selection_basis"] == "generic-tie-lexical-cut"
    assert first.to_dict() == second.to_dict()


def test_three_generic_candidates_preserve_existing_non_tie_behavior():
    result = orchestrate_lesson_retrieval(
        request(), execute_read=read([_lesson_row(f"LL-{n}") for n in range(10, 13)])
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_count == 3
    assert result.retrieval_diagnostics["selection_basis"] == "generic-unique"


def test_known_identity_request_preserves_admission():
    calls = []
    rows = {f"LL-{n}": _lesson_row(f"LL-{n}") for n in range(10, 15)}

    def known_only(query):
        calls.append(query)
        assert query["filter"]["or"] == [
            {"property": "Lesson ID", "unique_id": {"equals": 14}}
        ]
        return {"results": [rows["LL-14"]], "has_more": False, "next_cursor": None}

    result = orchestrate_lesson_retrieval(
        request(known_knowledge_refs=("LL-14",)),
        execute_read=known_only,
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-14",)
    assert result.retrieval_diagnostics["selection_basis"] == "identity-scoped"
    assert result.retrieval_diagnostics["best_bucket_tied_identities"] == 1
    assert len(calls) == 1


def test_abstention_keeps_caller_rules_but_not_unverified_lesson_references():
    caller_ref = "https://github.com/Blummer92/agent-os/issues/4026"
    result = orchestrate_lesson_retrieval(
        request(canonical_rule_refs=(caller_ref,)),
        execute_read=read([_lesson_row(f"LL-{n}") for n in range(10, 14)]),
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert result.selected_lesson_ids == ()
    assert result.canonical_github_refs == (caller_ref,)
    assert result.handoff_projection["allowed_inspect_first"] == [caller_ref]


def test_exact_library_match_preserves_admission_against_generic_tie():
    rows = [_lesson_row(f"LL-{n}") for n in range(10, 15)]
    rows[0]["properties"]["Lesson Learned"] = _title("unique-capability-specific")
    result = orchestrate_lesson_retrieval(
        request(library_hints=("unique-capability-specific",)),
        execute_read=read(rows),
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-10",)
    assert result.retrieval_diagnostics["selection_basis"] == "title-echo"


def test_no_relevant_candidate_remains_insufficient():
    result = orchestrate_lesson_retrieval(
        request(capability_keywords=("missing",)),
        execute_read=read([_lesson_row(f"LL-{n}") for n in range(10, 14)]),
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.selected_lesson_ids == ()


def test_provider_read_failure_does_not_become_generic_manual_review():
    def broken(_query):
        raise ConnectionError("offline")
    result = orchestrate_lesson_retrieval(request(), execute_read=broken)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.selected_lesson_ids == ()
    assert result.selection_reason_codes != ("generic-relevance-unverified",)
