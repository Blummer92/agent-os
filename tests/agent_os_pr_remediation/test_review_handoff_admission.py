from scripts.agent_os_pr_remediation.merge_evidence_summary import ReviewStatus, ai_review_evidence
from scripts.agent_os_pr_remediation.review_handoff_admission import (
    ReviewHandoffState,
    admit_review_handoff,
)

HEAD = "a" * 40
OLD = "b" * 40


def review(status=ReviewStatus.PERFORMED_CLEAR, sha=HEAD, provider="coderabbit"):
    return ai_review_evidence(
        provider=provider,
        status=status,
        reviewed_sha=sha,
        current_head_sha=HEAD,
    )


def test_1601_reproduction_green_validation_self_handoff_and_trigger_pending_is_not_complete():
    result = admit_review_handoff(
        review_required=True,
        current_head_sha=HEAD,
        review_evidence=None,
        provider_disabled_or_not_triggered=True,
        independent_reviewer=False,
        substantive_review=False,
    )
    assert result.state is ReviewHandoffState.REVIEW_UNAVAILABLE_MANUAL_REVIEW
    assert result.review_complete is False
    assert "provider-disabled-or-not-triggered" in result.reason_codes


def test_current_independent_substantive_review_may_complete():
    result = admit_review_handoff(
        review_required=True,
        current_head_sha=HEAD,
        review_evidence=review(),
        independent_reviewer=True,
        substantive_review=True,
    )
    assert result.state is ReviewHandoffState.SUBSTANTIVE_REVIEW_PERFORMED_CURRENT
    assert result.review_complete is True


def test_review_not_required_is_explicit_terminal_state():
    result = admit_review_handoff(
        review_required=False,
        current_head_sha=HEAD,
        review_evidence=None,
    )
    assert result.state is ReviewHandoffState.REVIEW_NOT_REQUIRED
    assert result.review_complete is True


def test_provider_unavailable_is_manual_review_with_clearing_condition():
    result = admit_review_handoff(
        review_required=True,
        current_head_sha=HEAD,
        review_evidence=review(ReviewStatus.UNAVAILABLE, None),
    )
    assert result.state is ReviewHandoffState.REVIEW_UNAVAILABLE_MANUAL_REVIEW
    assert result.review_complete is False
    assert result.clearing_condition


def test_stale_provider_review_on_old_head_is_not_current():
    stale = ai_review_evidence(
        provider="coderabbit",
        status=ReviewStatus.PERFORMED_CLEAR,
        reviewed_sha=OLD,
        current_head_sha=HEAD,
    )
    result = admit_review_handoff(
        review_required=True,
        current_head_sha=HEAD,
        review_evidence=stale,
        independent_reviewer=True,
        substantive_review=True,
    )
    assert result.review_complete is False
    assert "review-stale" in result.reason_codes


def test_ordinary_provider_comment_cannot_synthesize_substantive_review():
    result = admit_review_handoff(
        review_required=True,
        current_head_sha=HEAD,
        review_evidence=None,
        review_requested=False,
        substantive_review=False,
    )
    assert result.review_complete is False
    assert "review-not-requested" in result.reason_codes


def test_self_authored_review_artifact_does_not_satisfy_independent_review():
    result = admit_review_handoff(
        review_required=True,
        current_head_sha=HEAD,
        review_evidence=review(),
        independent_reviewer=False,
        substantive_review=True,
    )
    assert result.review_complete is False
    assert "substantive-review-unproven" in result.reason_codes


def test_requested_review_is_pending_not_complete():
    result = admit_review_handoff(
        review_required=True,
        current_head_sha=HEAD,
        review_evidence=None,
        review_requested=True,
    )
    assert result.state is ReviewHandoffState.REVIEW_REQUESTED_PENDING
    assert result.review_complete is False


def test_blocking_substantive_review_is_not_complete():
    result = admit_review_handoff(
        review_required=True,
        current_head_sha=HEAD,
        review_evidence=review(ReviewStatus.PERFORMED_BLOCKED),
        independent_reviewer=True,
        substantive_review=True,
    )
    assert result.review_complete is False
    assert "review-performed-blocked" in result.reason_codes


def test_provider_not_required_cannot_override_canonical_required_policy():
    result = admit_review_handoff(
        review_required=True,
        current_head_sha=HEAD,
        review_evidence=review(ReviewStatus.NOT_REQUIRED, None),
    )
    assert result.review_complete is False
    assert "review-policy-conflict" in result.reason_codes
