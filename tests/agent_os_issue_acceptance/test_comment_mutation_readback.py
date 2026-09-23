from scripts.agent_os_issue_acceptance.comment_mutation_readback import (
    CommentPersistenceStatus,
    CommentReadback,
    content_digest,
    evaluate_comment_persistence,
)


def test_persisted_comment_requires_exact_canonical_readback():
    result = evaluate_comment_persistence(
        issue_number=2784,
        intended_body="decision record",
        provider_reported_success=True,
        readback_complete=True,
        comments=(CommentReadback(99, 2784, "decision record"),),
    )
    assert result.status is CommentPersistenceStatus.PERSISTED
    assert result.persisted_comment_id == 99
    assert result.retry_safe is False


def test_provider_success_without_comment_is_not_persisted_and_can_retry_once():
    result = evaluate_comment_persistence(
        issue_number=2784,
        intended_body="decision record",
        provider_reported_success=True,
        readback_complete=True,
        comments=(),
    )
    assert result.status is CommentPersistenceStatus.NOT_PERSISTED
    assert result.reason_codes == ("provider-success-without-persistence",)
    assert result.retry_safe is True


def test_incomplete_or_uncertain_readback_never_authorizes_retry():
    incomplete = evaluate_comment_persistence(
        issue_number=2784, intended_body="decision record",
        provider_reported_success=True, readback_complete=False, comments=(),
    )
    uncertain = evaluate_comment_persistence(
        issue_number=2784, intended_body="decision record",
        provider_reported_success=None, readback_complete=True, comments=(),
    )
    assert incomplete.status is CommentPersistenceStatus.UNCERTAIN
    assert uncertain.status is CommentPersistenceStatus.UNCERTAIN
    assert incomplete.retry_safe is False and uncertain.retry_safe is False


def test_duplicate_content_fails_closed_instead_of_reposting():
    comments = (
        CommentReadback(10, 2784, "decision record"),
        CommentReadback(11, 2784, "decision record"),
    )
    result = evaluate_comment_persistence(
        issue_number=2784, intended_body="decision record",
        provider_reported_success=True, readback_complete=True, comments=comments,
    )
    assert result.status is CommentPersistenceStatus.UNCERTAIN
    assert result.reason_codes == ("readback.duplicate-content",)
    assert result.retry_safe is False


def test_content_identity_is_target_bound_and_deterministic():
    assert content_digest(2784, "x") == content_digest(2784, "x")
    assert content_digest(2784, "x") != content_digest(2785, "x")
