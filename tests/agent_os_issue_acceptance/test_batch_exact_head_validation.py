import pytest

from scripts.agent_os_issue_acceptance.batch_exact_head_validation import (
    ExactHeadValidationEvidence,
    ReviewState,
    ValidationDisposition,
    ValidationState,
    evaluate_exact_head_validation,
)


HEAD = "a" * 40
OLD = "b" * 40


def evidence(**changes):
    values = dict(
        repository="Blummer92/agent-os",
        pull_request_number=42,
        current_head_sha=HEAD,
        tested_head_sha=HEAD,
        validation_state=ValidationState.SUCCESS,
        review_state=ReviewState.CLEARED,
        reviewed_head_sha=HEAD,
        retry_count=0,
        retry_ceiling=2,
    )
    values.update(changes)
    return ExactHeadValidationEvidence(**values)


def test_review_cleared_exact_head_success_hands_to_bm0():
    result = evaluate_exact_head_validation(evidence())
    assert result.disposition is ValidationDisposition.HANDOFF
    assert result.handoff_to_bm0 is True
    assert result.merge_authorized is False


@pytest.mark.parametrize(
    "state",
    [
        ValidationState.PENDING,
        ValidationState.CANCELLED,
        ValidationState.SKIPPED,
        ValidationState.MISSING,
        ValidationState.SUPERSEDED,
        ValidationState.UNAVAILABLE,
    ],
)
def test_incomplete_validation_defers_and_never_passes(state):
    result = evaluate_exact_head_validation(evidence(validation_state=state))
    assert result.disposition is ValidationDisposition.DEFERRED
    assert result.handoff_to_bm0 is False


def test_draft_aggregate_skipped_requires_dispatch_not_pass():
    result = evaluate_exact_head_validation(evidence(validation_state=ValidationState.SKIPPED))
    assert result.workflow_dispatch_required is True
    assert result.handoff_to_bm0 is False


def test_stale_validation_head_is_invalidated():
    result = evaluate_exact_head_validation(evidence(tested_head_sha=OLD))
    assert result.effective_validation_state is ValidationState.STALE
    assert result.disposition is ValidationDisposition.DEFERRED


@pytest.mark.parametrize(
    "review_state",
    [ReviewState.MISSING, ReviewState.STALE, ReviewState.BLOCKING_FINDINGS, ReviewState.MANUAL_BLOCKED],
)
def test_success_cannot_handoff_without_current_review_clearance(review_state):
    result = evaluate_exact_head_validation(evidence(review_state=review_state))
    assert result.disposition is ValidationDisposition.BLOCKED
    assert result.review_clearance_required is True
    assert result.handoff_to_bm0 is False


def test_new_head_invalidates_previously_cleared_review():
    result = evaluate_exact_head_validation(evidence(reviewed_head_sha=OLD))
    assert result.review_state is ReviewState.STALE
    assert result.disposition is ValidationDisposition.BLOCKED


def test_red_repairable_under_ceiling_returns_exact_retry_attempt():
    result = evaluate_exact_head_validation(
        evidence(
            validation_state=ValidationState.FAILURE,
            failed_attempt_id="attempt-7",
            retry_count=1,
            retry_ceiling=2,
        )
    )
    assert result.disposition is ValidationDisposition.RETRY_REQUIRED
    assert result.failed_attempt_id == "attempt-7"
    assert result.diagnostic_routing_required is True


def test_red_repairable_requires_failed_attempt_identity():
    with pytest.raises(ValueError, match="failed_attempt_id"):
        evaluate_exact_head_validation(
            evidence(validation_state=ValidationState.FAILURE, retry_count=0, retry_ceiling=2)
        )


def test_retry_ceiling_exhaustion_blocks():
    result = evaluate_exact_head_validation(
        evidence(validation_state=ValidationState.FAILURE, retry_count=2, retry_ceiling=2)
    )
    assert result.disposition is ValidationDisposition.BLOCKED


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"authorization_blocked": True}, "authorization-boundary"),
        ({"ckr6_mutation_blocked": True}, "ckr6-mutation-blocked"),
        ({"semantic_progress": False}, "semantic-progress-failed"),
    ],
)
def test_explicit_escalation_boundaries_block(changes, reason):
    result = evaluate_exact_head_validation(evidence(**changes))
    assert result.disposition is ValidationDisposition.BLOCKED
    assert reason in result.reason_codes


def test_authority_fields_are_non_authorizing():
    result = evaluate_exact_head_validation(evidence())
    assert result.mutation_authorized is False
    assert result.merge_authorized is False
    assert result.side_effects_performed is False


@pytest.mark.parametrize("sha", ["A" * 40, "a" * 39, "g" * 40, ""])
def test_exact_head_identity_fails_closed(sha):
    with pytest.raises(ValueError):
        evidence(current_head_sha=sha)
