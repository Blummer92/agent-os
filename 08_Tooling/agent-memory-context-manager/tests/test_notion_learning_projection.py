from agent_memory_context_manager.coding_failure_learning import (
    FailureKind,
    FailureObservation,
    LessonDisposition,
    LessonLearningResult,
    evaluate_coding_failure,
)
from agent_memory_context_manager.notion_learning_projection import (
    MAX_BACKFILL_BATCH_SIZE,
    ProjectionDisposition,
    plan_historical_backfill,
    project_lesson_to_notion,
)


def observation(**overrides):
    values = dict(
        source_reference="issue:#100",
        failure_kind=FailureKind.CODE_DEFECT,
        failure_signature="wrong-linked-issue",
        ecosystem="python",
        capability_kind="issue-acceptance",
        library_name=None,
        lesson_summary="Prefer explicit closing references",
        what_happened="An incidental issue reference was selected before the authoritative target.",
        what_to_do_next_time="Resolve exactly one explicit closing-keyword target.",
        guardrail="Route multiple or bare-only references to manual review.",
        learning_type="correctness",
        severity="medium",
        owner_agent="github-service-agent",
        canonical_github_refs=("https://github.com/Blummer92/agent-os/issues/100",),
        evidence_refs=("https://github.com/Blummer92/agent-os/pull/101",),
        future_use_hints=("linked issue parser",),
    )
    values.update(overrides)
    return FailureObservation(**values)


def reusable_result(index=0):
    return evaluate_coding_failure(
        observation(
            source_reference=f"issue:#{100 + index}",
            failure_signature=f"wrong-linked-issue-{index}",
            canonical_github_refs=(f"https://github.com/Blummer92/agent-os/issues/{100 + index}",),
            evidence_refs=(f"https://github.com/Blummer92/agent-os/pull/{200 + index}",),
        )
    )


def test_reusable_lesson_projects_distinct_diagnosis_to_non_authoritative_record():
    result = reusable_result()
    diagnosis = "The parser treated a bare reference as authoritative before evaluating closing-keyword intent."
    projected = project_lesson_to_notion(result, root_cause_or_diagnosis=diagnosis)
    assert projected.disposition is ProjectionDisposition.ELIGIBLE
    assert projected.record is not None
    assert projected.record.symptom != diagnosis
    assert projected.record.root_cause_or_diagnosis == diagnosis
    assert projected.record.source_of_truth == "GitHub"
    assert projected.record.notion_role == "non-authoritative-working-knowledge"
    assert projected.record.notion_write_performed is False
    assert projected.record.publication_authorized is False
    assert projected.record.canonical_github_refs
    assert projected.record.evidence_refs


def test_missing_diagnosis_is_explicit_and_never_copied_from_symptom():
    projected = project_lesson_to_notion(reusable_result())
    assert projected.record is not None
    assert projected.record.root_cause_or_diagnosis is None
    assert "root-cause-or-diagnosis-not-supplied" in projected.reason_codes


def test_non_reusable_result_is_skipped():
    result = evaluate_coding_failure(observation(failure_kind=FailureKind.TRIVIAL))
    projected = project_lesson_to_notion(result)
    assert projected.disposition is ProjectionDisposition.SKIP
    assert projected.record is None


def test_manual_review_is_preserved():
    result = LessonLearningResult(LessonDisposition.MANUAL_REVIEW, ("ambiguous",))
    projected = project_lesson_to_notion(result)
    assert projected.disposition is ProjectionDisposition.MANUAL_REVIEW
    assert projected.reason_codes == ("ambiguous",)


def test_backfill_rejects_duplicate_lesson_identity_across_full_set():
    result = reusable_result()
    planned = plan_historical_backfill((result, result))
    assert len(planned.results) == 1
    assert planned.results[0].disposition is ProjectionDisposition.MANUAL_REVIEW
    assert planned.results[0].reason_codes == ("duplicate-lesson-identity-in-backfill-set",)


def test_backfill_pages_more_than_fifty_without_global_cap():
    results = tuple(reusable_result(index) for index in range(MAX_BACKFILL_BATCH_SIZE + 7))
    first = plan_historical_backfill(results)
    assert first.batch_size == MAX_BACKFILL_BATCH_SIZE
    assert len(first.results) == MAX_BACKFILL_BATCH_SIZE
    assert first.total_results == MAX_BACKFILL_BATCH_SIZE + 7
    assert first.next_offset == MAX_BACKFILL_BATCH_SIZE
    assert first.complete is False

    second = plan_historical_backfill(results, offset=first.next_offset)
    assert second.batch_size == 7
    assert len(second.results) == 7
    assert second.next_offset is None
    assert second.complete is True
