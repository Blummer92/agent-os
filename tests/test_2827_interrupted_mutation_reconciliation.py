"""Regression fixtures for #2827: interrupted GitHub mutation receipt reconciliation.

Pins the mutation-receipt-loss classification contract using the existing
executable readback evaluator
(`scripts/agent_os_issue_acceptance/comment_mutation_readback.py`, #2785).
The classification table is provider-agnostic: it binds an intended body, a
provider signal that may be *absent* (receipt lost), and a canonical readback
— the same triple the GitHub Service Agent overlay requires for every
post-create readback obligation.

Scope and honesty boundary (test-only, no production change):

- These tests pin what the contract REQUIRES of the consumer. They do not
  add a production seam, a retry daemon, a scheduler, or host behavior.
- Receipt loss itself is unobservable to repository code: the mutation and
  its receipt travel through the host execution surface. The actual repair
  remains host-owned (#2827: "repository code does not fake a fix it cannot
  enforce"). A green suite here is contract evidence, not a fix.
- Incident scenarios mirrored: the 2026-09-22 batch (#2809-#2812) and the
  2026-10-13 #3577 issue-create, both lost their receipts to
  "The previous Code Mode continuation is no longer available."

The central invariant under test: a lost mutation response is classified
outcome-unknown (UNCERTAIN), never as proof the mutation failed, and never
authorizes an automatic retry or a duplicate write.
"""

import pytest

from scripts.agent_os_issue_acceptance.comment_mutation_readback import (
    CommentPersistenceStatus,
    CommentReadback,
    evaluate_comment_persistence,
)


def _reconcile(issue_number, intended_body, *, provider_signal, comments, complete=True):
    return evaluate_comment_persistence(
        issue_number=issue_number,
        intended_body=intended_body,
        provider_reported_success=provider_signal,
        readback_complete=complete,
        comments=tuple(comments),
    )


def test_3577_interrupted_create_with_persisted_issue_is_recognized_not_retried():
    """#3577: receipt lost, readback finds the exact persisted issue.

    Must return the canonical identity and must NOT authorize a retry —
    a second create would have duplicated #3577.
    """
    result = _reconcile(
        3577,
        "BUG — Day 1 worksheet not synchronized with revised Marketing Foundations slides",
        provider_signal=None,
        comments=(CommentReadback(9001, 3577, "BUG — Day 1 worksheet not synchronized with revised Marketing Foundations slides"),),
    )
    assert result.status is CommentPersistenceStatus.PERSISTED
    assert result.persisted_comment_id == 9001
    assert result.retry_safe is False
    assert result.side_effects_performed is False
    assert result.reason_codes == ("readback.persisted",)


def test_2809_2812_batch_each_interrupted_create_reconciled_independently():
    """Sept-22 incident: four interrupted creates, each reconciled on its own identity."""
    intended = {
        2809: "PPUX-SCHOOL1 — Schoology/Kami browser session routing",
        2810: "capture evidence bound to Recorder target/frame context",
        2811: "bounded file-input replay artifact binding",
        2812: "Schoology to Kami teacher-sandbox empirical canary",
    }
    persisted = {n: CommentReadback(7000 + n, n, body) for n, body in intended.items()}
    for number, body in intended.items():
        result = _reconcile(number, body, provider_signal=None, comments=(persisted[number],))
        assert result.status is CommentPersistenceStatus.PERSISTED
        assert result.persisted_comment_id == 7000 + number
        assert result.retry_safe is False


def test_interrupted_response_with_empty_readback_is_uncertain_not_failed():
    """Lost receipt + complete empty readback is UNCERTAIN, not NOT_PERSISTED.

    This is the #2827 central invariant: a missing response must never be
    mistaken for proof that the mutation failed.
    """
    result = _reconcile(2827, "intended mutation body", provider_signal=None, comments=())
    assert result.status is CommentPersistenceStatus.UNCERTAIN
    assert result.status is not CommentPersistenceStatus.NOT_PERSISTED
    assert result.retry_safe is False
    assert result.reason_codes == ("provider-outcome-uncertain",)


def test_interrupted_response_with_ambiguous_matches_fails_closed():
    """Two same-body matches on readback: fail closed, no retry, no identity claimed."""
    body = "intended mutation body"
    result = _reconcile(
        2827,
        body,
        provider_signal=None,
        comments=(CommentReadback(1, 2827, body), CommentReadback(2, 2827, body)),
    )
    assert result.status is CommentPersistenceStatus.UNCERTAIN
    assert result.retry_safe is False
    assert result.persisted_comment_id is None
    assert result.reason_codes == ("readback.duplicate-content",)


def test_interrupted_response_with_incomplete_readback_stays_uncertain():
    """An incomplete readback after receipt loss cannot prove absence."""
    result = _reconcile(2827, "intended mutation body", provider_signal=None, comments=(), complete=False)
    assert result.status is CommentPersistenceStatus.UNCERTAIN
    assert result.retry_safe is False
    assert result.reason_codes == ("readback.incomplete",)


def test_definite_provider_failure_is_retry_admissible():
    """provider_reported_success=False is a definite failure: retry is admissible."""
    result = _reconcile(2827, "intended mutation body", provider_signal=False, comments=())
    assert result.status is CommentPersistenceStatus.NOT_PERSISTED
    assert result.retry_safe is True
    assert result.reason_codes == ("provider-failure-and-no-persistence",)


def test_denied_write_path_is_distinguishable_from_lost_response():
    """Authorization denial remains distinct from response loss.

    A denied write (False) is retry-admissible once authorized; a lost
    response (None) is never retry-admissible without readback proof.
    """
    denied = _reconcile(2827, "intended mutation body", provider_signal=False, comments=())
    lost = _reconcile(2827, "intended mutation body", provider_signal=None, comments=())
    assert denied.status is CommentPersistenceStatus.NOT_PERSISTED
    assert denied.retry_safe is True
    assert lost.status is CommentPersistenceStatus.UNCERTAIN
    assert lost.retry_safe is False


def test_no_duplicate_mutation_after_verified_success():
    """Once readback proves persistence, no second mutation may be submitted."""
    body = "intended mutation body"
    result = _reconcile(
        2827, body, provider_signal=None, comments=(CommentReadback(42, 2827, body),)
    )
    assert result.status is CommentPersistenceStatus.PERSISTED
    assert result.retry_safe is False
    assert result.side_effects_performed is False


def test_readback_from_wrong_target_is_uncertain():
    """Comments read back from a different target prove nothing about this mutation."""
    result = _reconcile(
        2827,
        "intended mutation body",
        provider_signal=None,
        comments=(CommentReadback(5, 9999, "intended mutation body"),),
    )
    assert result.status is CommentPersistenceStatus.UNCERTAIN
    assert result.retry_safe is False
    assert result.reason_codes == ("readback.target-mismatch",)
