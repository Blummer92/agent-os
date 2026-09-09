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
