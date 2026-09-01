from agent_memory_context_manager.ci_review_learning import (
    LearningSignal,
    ProducerDisposition,
    StructuredLearningOutcome,
    normalize_learning_outcome,
)
from agent_memory_context_manager.coding_failure_learning import (
    FailureKind,
    evaluate_coding_failure,
)
from agent_memory_context_manager.coding_knowledge_selection import KnowledgeCurrentness


def outcome(signal=LearningSignal.ESCAPED_REGRESSION, **overrides):
    values = dict(
        source_reference="github:pr:1560:head:abc",
        signal=signal,
        failure_signature="fail-closed-state-bypass",
        ecosystem="python",
        capability_kind="ci-review",
        lesson_summary="Preserve fail-closed state checks",
        what_happened="A bounded exact-head outcome proved the invariant could be bypassed.",
        severity="high",
        owner_agent="GitHub Service Agent",
        canonical_github_refs=("https://github.com/Blummer92/agent-os/issues/1560",),
        evidence_refs=("validation:abc",),
        affected_paths=("scripts/example.py",),
        future_use_hints=("state-machine",),
        what_to_do_next_time="Exercise the fail-closed branch before accepting the repair.",
        guardrail="Keep a deterministic regression for the bypass.",
        reusable_rule_proven=True,
    )
    values.update(overrides)
    return StructuredLearningOutcome(**values)


def test_escaped_regression_reaches_existing_ckr5():
    produced = normalize_learning_outcome(outcome())
    assert produced.disposition is ProducerDisposition.CKR5_CANDIDATE
    assert produced.observation.failure_kind is FailureKind.CODE_DEFECT
    learned = evaluate_coding_failure(produced.observation)
    assert learned.proposal is not None
    assert learned.authority_created is False
    assert learned.notion_write_performed is False


def test_substantive_review_finding_reaches_ckr5_without_redefining_finding_semantics():
    produced = normalize_learning_outcome(outcome(LearningSignal.SUBSTANTIVE_REVIEW_FINDING))
    assert produced.observation.failure_kind is FailureKind.REVIEW_FINDING


def test_expected_failure_and_transient_environment_are_noise():
    for signal in (LearningSignal.EXPECTED_TEST_FAILURE, LearningSignal.TRANSIENT_ENVIRONMENT):
        produced = normalize_learning_outcome(outcome(signal))
        assert produced.disposition is ProducerDisposition.NOT_REUSABLE
        assert produced.observation is None


def test_property_counterexample_requires_permanent_regression_evidence():
    missing = normalize_learning_outcome(outcome(LearningSignal.PROPERTY_COUNTEREXAMPLE))
    assert missing.disposition is ProducerDisposition.INSUFFICIENT
    admitted = normalize_learning_outcome(outcome(
        LearningSignal.PROPERTY_COUNTEREXAMPLE,
        permanent_regression_ref="test:test_regression_case",
    ))
    assert admitted.disposition is ProducerDisposition.CKR5_CANDIDATE
    assert "test:test_regression_case" in admitted.observation.canonical_github_refs


def test_surviving_mutation_is_quality_evidence_until_reusable_rule_is_proven():
    produced = normalize_learning_outcome(outcome(
        LearningSignal.SURVIVING_MUTATION,
        reusable_rule_proven=False,
    ))
    assert produced.disposition is ProducerDisposition.NOT_REUSABLE


def test_stale_or_conflicting_evidence_fails_closed():
    stale = normalize_learning_outcome(outcome(currentness=KnowledgeCurrentness.STALE))
    conflict = normalize_learning_outcome(outcome(authority_conflict=True))
    assert stale.disposition is ProducerDisposition.MANUAL_REVIEW
    assert conflict.disposition is ProducerDisposition.MANUAL_REVIEW


def test_oversized_structured_payload_is_rejected_instead_of_becoming_raw_log_ingestion():
    try:
        outcome(what_happened="x" * 1025)
    except ValueError as exc:
        assert "bounded structured-evidence size" in str(exc)
    else:
        raise AssertionError("oversized evidence must be rejected")


def test_ckr5_text_bounds_are_enforced_before_observation_construction():
    try:
        outcome(lesson_summary="x" * 513)
    except ValueError as exc:
        assert "bounded structured-evidence size" in str(exc)
    else:
        raise AssertionError("CKR5-incompatible text must be rejected")


def test_combined_hints_over_ckr5_budget_fail_closed():
    produced = normalize_learning_outcome(outcome(
        future_use_hints=tuple(f"hint-{index}" for index in range(20)),
        affected_paths=("scripts/extra.py",),
    ))
    assert produced.disposition is ProducerDisposition.MANUAL_REVIEW
    assert produced.reason_codes == ("ckr5-reference-budget-exceeded",)
    assert produced.observation is None


def test_regression_ref_over_ckr5_budget_fails_closed():
    produced = normalize_learning_outcome(outcome(
        LearningSignal.PROPERTY_COUNTEREXAMPLE,
        canonical_github_refs=tuple(f"issue:{index}" for index in range(20)),
        permanent_regression_ref="test:test_regression_case",
    ))
    assert produced.disposition is ProducerDisposition.MANUAL_REVIEW
    assert produced.reason_codes == ("ckr5-reference-budget-exceeded",)
    assert produced.observation is None


def test_identical_bounded_evidence_is_deterministic_and_non_authorizing():
    left = normalize_learning_outcome(outcome())
    right = normalize_learning_outcome(outcome())
    assert left == right
    assert left.side_effects_performed is False
    assert left.validation_authorized is False
    assert left.merge_authorized is False
    assert left.closure_authorized is False
    assert left.production_authorized is False
    assert left.external_write_authorized is False
