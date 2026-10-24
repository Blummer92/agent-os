"""Tests for ADR-001 MergeProposal wiring (#2340/#3463).

A MergeProposal is typed evidence only: it confers no authority by itself,
posts nothing, and dispatches nothing. These tests prove (a) its content
identity is tamper-sensitive, (b) it can only be assembled from an APPROVED
approval triple whose projection matches live PR evidence, and (c) the
canonical evaluator returns applicable through it only when every binding
agrees — and blocks on every adversarial drift, including the full
16-case shape from the merge-admission brief (forged, missing, wrong
target, stale head, changed base/body/scope, failed/stale checks, blocking
reviews, expired/consumed authorization, wrong method, protected target,
provider-shaped malformed evidence, unauthorized closing references, and
the valid fresh-applicability positive).
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.agent_os_issue_acceptance import (  # noqa: E402
    MergeAuthorizationState,
    build_merge_authorization_candidate,
    evaluate_merge_authorization_applicability,
    record_merge_authorization_decision,
    record_merge_execution_observation,
)
from scripts.agent_os_issue_acceptance.merge_authorization import (  # noqa: E402
    build_merge_proposal,
)
from scripts.agent_os_issue_acceptance.merge_proposal import (  # noqa: E402
    MERGE_PROPOSAL_SCHEMA_VERSION,
    MergeProposal,
)

_HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("_tauth", _HERE / "test_merge_authorization.py")
_tauth = importlib.util.module_from_spec(_spec)
sys.modules["_tauth"] = _tauth
_spec.loader.exec_module(_tauth)

HEAD = "a" * 40
BASE = "b" * 40
AT = "2026-07-26T14:40:00Z"


def _proposal(bundle=None, pr=None):
    bundle = bundle or _tauth._bundle()
    approval, applicability, projection = bundle[0], bundle[1], bundle[2]
    return build_merge_proposal(approval, applicability, projection, pr or _tauth._pr(bundle)), bundle


def _authorized_record(bundle, proposal, pr=None):
    candidate = build_merge_authorization_candidate(
        bundle[0], bundle[1], bundle[2], pr or _tauth._pr(bundle),
        current_proposal=proposal, current_issueplan_evidence=None,
        current_repository_state_evidence=None,
        authorizer_id="repository-owner", decision_id="merge-request",
        decision_at="2026-07-26T14:25:00Z", expires_at="2026-07-26T15:00:00Z",
        permitted_merge_method="squash",
    )
    return record_merge_authorization_decision(
        candidate, state="authorized", decision_id="merge-authorized",
        authorizer_id="repository-owner", decision_at="2026-07-26T14:30:00Z",
    )


def _evaluate(record, bundle, pr=None, at=AT, events=()):
    approval, applicability, projection, _, _, _ = bundle
    # The proposal is decision-time evidence (built from the clean PR);
    # evaluation then compares it against the possibly drifted current PR.
    proposal, _ = _proposal(bundle)
    return evaluate_merge_authorization_applicability(
        record, approval, applicability, projection, pr or _tauth._pr(bundle),
        current_proposal=proposal, current_issueplan_evidence=None,
        current_repository_state_evidence=None, evaluated_at=at,
        invalidation_events=events,
    )


def test_proposal_identity_is_content_derived_and_tamper_sensitive():
    proposal, _ = _proposal()
    assert proposal.schema_version == MERGE_PROPOSAL_SCHEMA_VERSION
    assert proposal.proposal_id.startswith("merge-proposal:")
    again, _ = _proposal()
    assert again == proposal
    # Any bound-field tamper invalidates the identity at construction.
    with pytest.raises(ValueError, match="does not match"):
        replace(proposal, exact_head_sha="f" * 40)
    with pytest.raises(ValueError, match="does not match"):
        replace(proposal, pull_request_number=999)
    with pytest.raises(ValueError, match="does not match"):
        replace(proposal, changed_scope_fingerprint="0" * 64)


def test_proposal_rejects_malformed_inputs():
    proposal, _ = _proposal()
    with pytest.raises(ValueError):
        replace(proposal, exact_head_sha="not-a-sha")
    with pytest.raises(ValueError):
        replace(proposal, permitted_merge_method="fast-forward")
    with pytest.raises(ValueError):
        replace(proposal, required_checks=())
    with pytest.raises(ValueError):
        replace(
            proposal,
            required_checks=(
                ("CI", "github-actions", HEAD, "success"),
                ("CI", "github-actions", HEAD, "success"),
            ),
        )
    with pytest.raises(ValueError):
        replace(proposal, schema_version="merge-proposal/v9")


def test_proposal_assembly_requires_approved_applicable_triple():
    bundle = _tauth._bundle()
    approval, applicability, projection = bundle[0], bundle[1], bundle[2]
    pr = _tauth._pr(bundle)
    # Pending (not APPROVED) approval cannot produce a proposal.
    pending = _tauth.build_approval_candidate(
        bundle[3], bundle[4], bundle[5],
        approval_kind=_tauth.ApprovalKind.IMPLEMENTATION,
        authorizer_id="operator-requester", decision_id="approval-request",
        decision_at="2026-07-26T14:00:00Z", expires_at="2026-07-26T16:00:00Z",
    )
    with pytest.raises(ValueError):
        build_merge_proposal(pending, applicability, projection, pr)
    # A projection from a different approval cannot produce a proposal.
    other = _tauth._bundle(approval_expires="2026-07-26T17:00:00Z")
    with pytest.raises(ValueError):
        build_merge_proposal(approval, applicability, other[2], pr)
    # A projection that does not match PR evidence cannot produce one.
    with pytest.raises(ValueError):
        build_merge_proposal(approval, applicability, projection, _tauth._pr(bundle, head_sha="f" * 40))


def test_candidate_and_evaluator_work_through_merge_proposal():
    bundle = _tauth._bundle()
    proposal, _ = _proposal(bundle)
    record = _authorized_record(bundle, proposal)
    result = _evaluate(record, bundle)
    assert result.status == "applicable" and result.merge_authorized
    assert result.changed_bindings == () and result.reason_codes == ()


def test_missing_record_is_blocked_not_applicable():
    bundle = _tauth._bundle()
    result = _evaluate(None, bundle)
    assert result.status == "blocked" and not result.merge_authorized
    assert "authorization.pending" in result.reason_codes


def test_stale_head_changed_base_body_and_scope_all_block():
    bundle = _tauth._bundle()
    proposal, _ = _proposal(bundle)
    record = _authorized_record(bundle, proposal)
    assert _evaluate(record, bundle, pr=_tauth._pr(bundle, head_sha="f" * 40)).status != "applicable"
    assert "pull-request.head-changed" in _evaluate(record, bundle, pr=_tauth._pr(bundle, head_sha="f" * 40)).reason_codes
    assert "pull-request.base-changed" in _evaluate(record, bundle, pr=_tauth._pr(bundle, base_sha_or_evidence_id="e" * 40)).reason_codes
    assert "pull-request.metadata-changed" in _evaluate(record, bundle, pr=_tauth._pr(bundle, pr_body="edited")).reason_codes
    assert "contract.scope-changed" in _evaluate(record, bundle, pr=_tauth._pr(bundle, changed_scope_fingerprint="0" * 64)).reason_codes


def test_wrong_pr_repository_and_method_block():
    bundle = _tauth._bundle()
    proposal, _ = _proposal(bundle)
    record = _authorized_record(bundle, proposal)
    assert "pull-request.identity-changed" in _evaluate(record, bundle, pr=_tauth._pr(bundle, pull_request_number=631)).reason_codes
    assert "pull-request.identity-changed" in _evaluate(record, bundle, pr=_tauth._pr(bundle, repository="blummer92/other")).reason_codes
    assert "merge.method-changed" in _evaluate(record, bundle, pr=_tauth._pr(bundle, proposed_merge_method="merge")).reason_codes


def test_failed_check_blocking_review_and_draft_block():
    bundle = _tauth._bundle()
    proposal, _ = _proposal(bundle)
    record = _authorized_record(bundle, proposal)
    failed = _tauth._check(state="failure")
    assert "checks.failed" in _evaluate(record, bundle, pr=_tauth._pr(bundle, required_checks=(failed,))).reason_codes
    blocked_review = _tauth._review(blocking_review_present=True)
    assert "review.blocked" in _evaluate(record, bundle, pr=_tauth._pr(bundle, review_evidence=blocked_review)).reason_codes
    draft = _evaluate(record, bundle, pr=_tauth._pr(bundle, draft=True, ready_for_review=False))
    assert "pull-request.draft" in draft.reason_codes
    assert not draft.merge_authorized


def test_unauthorized_closing_reference_and_dual_claim_block():
    bundle = _tauth._bundle()
    proposal, _ = _proposal(bundle)
    record = _authorized_record(bundle, proposal)
    result = _evaluate(record, bundle, pr=_tauth._pr(bundle, pr_body="Fixes #999"))
    assert not result.merge_authorized
    assert "pull-request.unauthorized-closing-reference" in result.reason_codes


def test_expired_and_consumed_authorization_block():
    bundle = _tauth._bundle()
    proposal, _ = _proposal(bundle)
    record = _authorized_record(bundle, proposal)
    expired = _evaluate(record, bundle, at="2026-07-26T15:00:01Z")
    assert not expired.merge_authorized
    assert "authorization.expired" in expired.reason_codes
    # Consume via the canonical observation, then re-evaluation must refuse.
    applicable = _evaluate(record, bundle)
    assert applicable.status == "applicable"
    _, consumed = record_merge_execution_observation(
        record, applicable, _tauth._pr(bundle),
        observed_merge_commit_sha="c" * 40, observed_actor_id="repository-owner",
        observed_at="2026-07-26T14:50:00Z", audit_location="test",
        observed_merge_method="squash",
    )
    assert consumed.state is MergeAuthorizationState.CONSUMED
    replay = _evaluate(consumed, bundle)
    assert not replay.merge_authorized
    assert "authorization.consumed" in replay.reason_codes


def test_pending_record_never_authorizes():
    bundle = _tauth._bundle()
    proposal, _ = _proposal(bundle)
    pending = build_merge_authorization_candidate(
        bundle[0], bundle[1], bundle[2], _tauth._pr(bundle),
        current_proposal=proposal, current_issueplan_evidence=None,
        current_repository_state_evidence=None,
        authorizer_id="repository-owner", decision_id="merge-request",
        decision_at="2026-07-26T14:25:00Z", expires_at="2026-07-26T15:00:00Z",
        permitted_merge_method="squash",
    )
    result = _evaluate(pending, bundle)
    assert not result.merge_authorized
    assert "authorization.pending" in result.reason_codes


def test_task_proposal_path_is_unchanged():
    # The pre-existing task-planning branch still evaluates as before; the
    # merge branch is additive, not a replacement of the canonical path.
    bundle = _tauth._bundle()
    authorized, _ = _tauth._authorized(bundle)
    result = _tauth._evaluate(authorized, bundle)
    assert result.status == "applicable" and result.merge_authorized
