"""Tests for approval_source.py: trusted approval artifact conversation readers.

Fixtures use the canonical producer recipe from test_merge_authorization
(_bundle) so every serialized artifact is exactly what the owner tooling
would post.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.agent_os_issue_acceptance import (  # noqa: E402
    ApprovalKind,
    ApprovalState,
    build_approval_candidate,
    reconstruct_approval_record,
    serialize_approval_applicability_result,
    serialize_approval_record,
    serialize_approved_execution_projection,
)
from scripts.agent_os_issue_acceptance.approval_records import (  # noqa: E402
    ApprovalApplicabilityResult,
)
from scripts.agent_os_issue_acceptance.approval_source import (  # noqa: E402
    APPLICABILITY_MARKER,
    APPROVAL_MARKER,
    PROJECTION_MARKER,
    ApprovalCommentSnapshot,
    ApprovalSourceSnapshot,
    ApprovalSourceStatus,
    reacquire_approval_source,
    serialize_approval_comment,
)

_HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location(
    "_tauth", _HERE / "test_merge_authorization.py"
)
_tauth = importlib.util.module_from_spec(_spec)
sys.modules["_tauth"] = _tauth
_spec.loader.exec_module(_tauth)

OWNER = "Blummer92"
REPO = "blummer92/agent-os"
PR = 630


def _bundle():
    return _tauth._bundle()


def _comment(cid, body, author=OWNER):
    return ApprovalCommentSnapshot(
        comment_id=cid, author_login=author,
        created_at="2026-10-19T20:00:00Z", body=body,
    )


def _triple_comments(bundle, start=11):
    approval, applicability, projection = bundle[0], bundle[1], bundle[2]
    return [
        _comment(start, serialize_approval_comment(APPROVAL_MARKER, serialize_approval_record(approval))),
        _comment(start + 1, serialize_approval_comment(APPLICABILITY_MARKER, serialize_approval_applicability_result(applicability))),
        _comment(start + 2, serialize_approval_comment(PROJECTION_MARKER, serialize_approved_execution_projection(projection))),
    ]


class _Transport:
    def __init__(self, comments, owner_type="User", complete=True):
        self._comments = comments
        self._owner_type = owner_type
        self._complete = complete

    def read_approval_source(self, repository, pr_number):
        return ApprovalSourceSnapshot(
            repository=repository, pr_number=pr_number, owner_login=OWNER,
            owner_type=self._owner_type, comments_complete=self._complete,
            comments=tuple(self._comments),
        )


def _read(comments, **kwargs):
    return reacquire_approval_source(
        transport=_Transport(comments), repository=REPO, pr_number=PR, **kwargs
    )


def test_current_triple_accepted():
    result = _read(_triple_comments(_bundle()))
    assert result.status is ApprovalSourceStatus.CURRENT
    assert result.reason_codes == ("current",)
    assert result.approval is not None and result.applicability is not None
    assert result.projection is not None and result.projection.complete
    assert result.source_comment_ids == (11, 12, 13)


def test_wrong_author_ignored():
    result = _read([_comment(11, "agent-os-approval/v1\n{}", author="someone-else")])
    assert result.status is ApprovalSourceStatus.BLOCKED
    assert result.reason_codes == ("approval.absent",)


def test_malformed_payload_fails_closed():
    bundle = _bundle()
    comments = _triple_comments(bundle)
    comments[0] = _comment(11, APPROVAL_MARKER + "\nnot-json")
    result = _read(comments)
    assert result.status is ApprovalSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("source.trusted-record-malformed",)


def test_missing_applicability_blocked():
    bundle = _bundle()
    comments = [_triple_comments(bundle)[0], _triple_comments(bundle)[2]]
    result = _read(comments)
    assert result.status is ApprovalSourceStatus.BLOCKED
    assert result.reason_codes == ("approval.applicability-absent",)


def test_applicability_not_applicable_is_stale():
    bundle = _bundle()
    approval, _, projection = bundle[0], bundle[1], bundle[2]
    stale_app = ApprovalApplicabilityResult(
        status="blocked", approval_id=approval.approval_id,
        approval_revision=approval.approval_revision,
        current_proposal_id=None, reason_codes=(),
        changed_bindings=(), approval_applicable=False,
    )
    comments = [
        _comment(11, serialize_approval_comment(APPROVAL_MARKER, serialize_approval_record(approval))),
        _comment(12, serialize_approval_comment(APPLICABILITY_MARKER, serialize_approval_applicability_result(stale_app))),
        _comment(13, serialize_approval_comment(PROJECTION_MARKER, serialize_approved_execution_projection(projection))),
    ]
    result = _read(comments)
    assert result.status is ApprovalSourceStatus.STALE
    assert result.reason_codes == ("approval.not-applicable",)


def test_approval_not_approved_is_stale():
    bundle = _bundle()
    _, _, _, proposal, issueplan, repository = bundle
    candidate = build_approval_candidate(
        proposal, issueplan, repository,
        approval_kind=ApprovalKind.IMPLEMENTATION,
        authorizer_id="operator-requester", decision_id="approval-request",
        decision_at="2026-07-26T14:00:00Z", expires_at="2026-07-26T16:00:00Z",
    )
    rejected = _tauth.record_approval_decision(
        candidate, state=ApprovalState.REJECTED,
        decision_id="rejection", authorizer_id="repository-owner",
        decision_at="2026-07-26T14:10:00Z",
    )
    result = _read([
        _comment(11, serialize_approval_comment(APPROVAL_MARKER, serialize_approval_record(rejected))),
    ])
    assert result.status is ApprovalSourceStatus.STALE
    assert result.reason_codes == ("approval.not-approved",)


def test_two_different_approvals_is_ambiguous():
    first = _triple_comments(_bundle())
    second_bundle = _tauth._bundle(approval_expires="2026-07-26T17:00:00Z")
    second = _triple_comments(second_bundle, start=21)
    result = _read(first + second)
    assert result.status is ApprovalSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("approval.ambiguous",)


def test_expected_approval_id_filters():
    bundle = _bundle()
    comments = _triple_comments(bundle)
    ok = _read(comments, expected_approval_id=bundle[0].approval_id)
    assert ok.status is ApprovalSourceStatus.CURRENT
    missing = _read(comments, expected_approval_id="approval:" + "0" * 64)
    assert missing.status is ApprovalSourceStatus.BLOCKED
    assert missing.reason_codes == ("approval.absent",)


def test_tampered_applicability_id_rejected():
    bundle = _bundle()
    approval, applicability, projection = bundle[0], bundle[1], bundle[2]
    tampered = replace(applicability, approval_id="approval:" + "f" * 64)
    comments = [
        _comment(11, serialize_approval_comment(APPROVAL_MARKER, serialize_approval_record(approval))),
        _comment(12, serialize_approval_comment(APPLICABILITY_MARKER, serialize_approval_applicability_result(tampered))),
        _comment(13, serialize_approval_comment(PROJECTION_MARKER, serialize_approved_execution_projection(projection))),
    ]
    result = _read(comments)
    assert result.status is ApprovalSourceStatus.BLOCKED
    assert result.reason_codes == ("approval.applicability-absent",)


def test_duplicate_comment_ids_ambiguous():
    bundle = _bundle()
    comments = _triple_comments(bundle)
    comments.append(_comment(11, "noise"))
    result = _read(comments)
    assert result.status is ApprovalSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("source.ambiguous",)


def test_incomplete_snapshot_needs_decision():
    bundle = _bundle()
    transport = _Transport(_triple_comments(bundle), complete=False)
    result = reacquire_approval_source(
        transport=transport, repository=REPO, pr_number=PR
    )
    assert result.status is ApprovalSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("source.incomplete",)


def test_non_transport_rejected():
    with pytest.raises(TypeError):
        reacquire_approval_source(transport=object(), repository=REPO, pr_number=PR)


def test_serialize_rejects_multiline_or_bad_marker():
    with pytest.raises(ValueError):
        serialize_approval_comment(APPROVAL_MARKER, b"a\nb")
    with pytest.raises(ValueError):
        serialize_approval_comment("bogus/v1", b"{}")
