import pytest

from agent_memory_context_manager.coding_knowledge_selection import CodingKnowledgeRequest
from agent_memory_context_manager.lesson_preflight import (
    FailedRepairAttempt,
    LessonRetrievalStatus,
    RepairContext,
    RetryReentryOutcome,
)
from agent_memory_context_manager.repair_lesson_activation import (
    RepairLessonDisposition,
    activate_repair_retry_lessons,
)


def request(**overrides):
    data = dict(
        task_reference="issue:#1873",
        ecosystem_hints=("python",),
        capability_keywords=("testing",),
        target_path_hints=(),
        canonical_rule_refs=(),
        known_knowledge_refs=(),
        specialized_knowledge_required=None,
    )
    data.update(overrides)
    return CodingKnowledgeRequest(**data)


def failed(attempt_id="attempt-1"):
    return FailedRepairAttempt(attempt_id, "repair hypothesis", "validation remained red")


def _title(text):
    return {"type": "title", "title": [{"plain_text": text}]}


def _rich(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def _select(name):
    return {"type": "select", "select": {"name": name}}


def live_row():
    return {
        "object": "page",
        "url": "https://www.notion.so/lesson-51",
        "last_edited_time": "2026-09-04T19:00:00Z",
        "properties": {
            "Lesson ID": _rich("LL-51"),
            "Lesson Learned": _title("Failed repairs must re-enter CKR6"),
            "Status": _select("Applied"),
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": _select("Testing"),
            "Applies To": {"type": "multi_select", "multi_select": [{"name": "Notion"}]},
            "Learning Type": _select("Testing lesson"),
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/1362"},
            "Guardrail": _rich("Do not mutate again before retry-specific lesson re-entry."),
            "What To Do Next Time": _rich("Preserve the failed hypothesis, consume CKR6, then continue."),
        },
    }


def test_failed_attempt_automatically_reads_and_records_consumed_before_next_mutation():
    calls = []

    def read(query):
        calls.append(query)
        return {"results": [live_row()], "has_more": False}

    result = activate_repair_retry_lessons(request(), failed(), execute_read=read)
    assert len(calls) == 1
    assert result.lesson_result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.attempt.retry_reentry_outcome is RetryReentryOutcome.CONSUMED
    assert result.lesson_disposition is RepairLessonDisposition.CONSUMED
    assert result.boundary.mutation_admissible is True


def test_each_new_failed_attempt_requires_its_own_activation():
    first = activate_repair_retry_lessons(request(), failed("attempt-1"), execute_read=lambda _: {"results": [live_row()], "has_more": False})
    second = activate_repair_retry_lessons(request(), failed("attempt-2"), execute_read=lambda _: {"results": [live_row()], "has_more": False})
    assert first.attempt.attempt_id != second.attempt.attempt_id
    assert first.attempt.retry_reentry_outcome is RetryReentryOutcome.CONSUMED
    assert second.attempt.retry_reentry_outcome is RetryReentryOutcome.CONSUMED
    assert first.boundary.mutation_admissible is True
    assert second.boundary.mutation_admissible is True


def test_specialized_required_unavailable_fails_closed_and_blocks_mutation():
    result = activate_repair_retry_lessons(
        request(specialized_knowledge_required=True),
        failed(),
        execute_read=None,
    )
    assert result.lesson_result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.attempt.retry_reentry_outcome is RetryReentryOutcome.UNAVAILABLE_OR_FAILED
    assert result.lesson_disposition is RepairLessonDisposition.CAPABILITY_UNAVAILABLE
    assert result.boundary.mutation_admissible is False
    assert result.boundary.blocking_attempt_id == "attempt-1"


def test_explicit_not_material_opt_out_performs_zero_reads_but_records_boundary():
    calls = []
    result = activate_repair_retry_lessons(
        request(
            ecosystem_hints=(),
            capability_keywords=(),
            specialized_knowledge_required=False,
        ),
        failed(),
        execute_read=lambda query: calls.append(query),
        repair_context=RepairContext.CI_DIAGNOSIS,
    )
    assert calls == []
    assert result.lesson_result.lesson_retrieval_status is LessonRetrievalStatus.NOT_NEEDED
    assert result.attempt.retry_reentry_outcome is RetryReentryOutcome.NOT_MATERIAL
    assert result.lesson_disposition is RepairLessonDisposition.NOT_MATERIAL
    assert result.boundary.mutation_admissible is True


def test_activation_is_retry_specific_and_rejects_already_satisfied_attempt():
    done = FailedRepairAttempt(
        "attempt-1",
        "repair hypothesis",
        "validation remained red",
        RetryReentryOutcome.CONSUMED,
    )
    try:
        activate_repair_retry_lessons(request(), done, execute_read=lambda _: {"results": [], "has_more": False})
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "already has" in str(exc)


def test_no_relevant_lesson_is_distinct_from_capability_failure():
    result = activate_repair_retry_lessons(
        request(specialized_knowledge_required=True),
        failed(),
        execute_read=lambda _: {"results": [], "has_more": False},
    )
    assert result.attempt.retry_reentry_outcome is RetryReentryOutcome.UNAVAILABLE_OR_FAILED
    assert result.lesson_disposition is RepairLessonDisposition.NO_RELEVANT_LESSON
    assert result.boundary.mutation_admissible is False


@pytest.mark.parametrize("field,value,error", [
    ("request", None, TypeError),
    ("attempt", None, TypeError),
    ("repair_context", RepairContext.NONE, ValueError),
    ("repair_context", "failed-pr-repair", ValueError),
])
def test_bad_retry_context_cannot_dispatch_a_read(field, value, error):
    calls = []
    inputs = {"request": request(), "attempt": failed(),
              "repair_context": RepairContext.FAILED_PR_REPAIR}
    inputs[field] = value
    with pytest.raises(error):
        activate_repair_retry_lessons(
            **inputs, execute_read=lambda query: calls.append(query),
        )
    assert calls == []


def test_sparse_repair_forces_retrieval_and_records_only_the_current_attempt():
    query = request(ecosystem_hints=(), capability_keywords=())
    previous = failed("this-attempt")
    calls = []
    result = activate_repair_retry_lessons(
        query, previous, execute_read=lambda item: (calls.append(item) or {"results": [], "has_more": False}),
    )
    assert len(calls) == 1
    assert result.attempt.attempt_id == previous.attempt_id
    assert previous.retry_reentry_outcome is None
    assert query.specialized_knowledge_required is None
    assert result.attempt.retry_reentry_outcome is RetryReentryOutcome.UNAVAILABLE_OR_FAILED
    assert result.lesson_disposition is RepairLessonDisposition.NO_RELEVANT_LESSON
    assert result.boundary.mutation_admissible is False


@pytest.mark.parametrize("case,disposition", [
    ("missing-primary", RepairLessonDisposition.UNVERIFIABLE_RELEVANT_LESSON),
    ("conflicting-revision", RepairLessonDisposition.CANDIDATE_DATA_DEFECT),
])
def test_repair_activation_reports_distinct_source_defects_without_admitting(case, disposition):
    first, second = live_row(), live_row()
    if case == "missing-primary":
        first["properties"]["Source Link"]["url"] = None
        rows = [first]
    else:
        second["last_edited_time"] = "2026-09-05T19:00:00Z"
        rows = [first, second]
    result = activate_repair_retry_lessons(
        request(), failed(), execute_read=lambda _: {"results": rows, "has_more": False},
    )
    assert result.lesson_disposition is disposition
    assert result.attempt.retry_reentry_outcome is RetryReentryOutcome.UNAVAILABLE_OR_FAILED
    assert result.boundary.mutation_admissible is False
    assert result.boundary.blocking_attempt_id == "attempt-1"
    assert result.lesson_result.selected_lesson_ids == ()
    assert result.lesson_result.authority_created is False
