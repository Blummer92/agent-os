from agent_memory_context_manager.coding_failure_learning import (
    FailureKind,
    FailureObservation,
    LessonDisposition,
    LessonLearningResult,
    evaluate_coding_failure,
)
from agent_memory_context_manager.notion_learning_projection import (
    MAX_BACKFILL_RESULTS,
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


def test_reusable_lesson_projects_to_non_authoritative_record():
    result = evaluate_coding_failure(observation())
    projected = project_lesson_to_notion(result)
    assert projected.disposition is ProjectionDisposition.ELIGIBLE
    assert projected.record is not None
    assert projected.record.source_of_truth == "GitHub"
    assert projected.record.notion_role == "non-authoritative-working-knowledge"
    assert projected.record.notion_write_performed is False
    assert projected.record.publication_authorized is False
    assert projected.record.canonical_github_refs
    assert projected.record.evidence_refs


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


def test_backfill_rejects_duplicate_lesson_identity():
    result = evaluate_coding_failure(observation())
    planned = plan_historical_backfill((result, result))
    assert len(planned) == 1
    assert planned[0].disposition is ProjectionDisposition.MANUAL_REVIEW
    assert planned[0].reason_codes == ("duplicate-lesson-identity-in-batch",)


def test_backfill_is_bounded():
    result = evaluate_coding_failure(observation())
    planned = plan_historical_backfill(tuple(result for _ in range(MAX_BACKFILL_RESULTS + 1)))
    assert planned[0].reason_codes == ("backfill-budget-exceeded",)
