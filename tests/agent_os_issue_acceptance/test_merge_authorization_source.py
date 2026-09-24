from __future__ import annotations

import json

from scripts.agent_os_issue_acceptance.merge_authorization import (
    MergeAuthorizationState,
    reconstruct_merge_authorization_record,
    serialize_merge_authorization_record,
)
from scripts.agent_os_issue_acceptance.merge_authorization_source import (
    AUTHORIZATION_MARKER,
    MergeAuthorizationCommentSnapshot,
    MergeAuthorizationSourceSnapshot,
    MergeAuthorizationSourceStatus,
    reacquire_merge_authorization_source,
    serialize_merge_authorization_comment,
)
from tests.agent_os_issue_acceptance.test_merge_authorization import _authorized


class Transport:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def read_merge_authorization_source(self, repository, pr_number):
        return self.snapshot


def snapshot(*comments, complete=True, owner_type="User"):
    return MergeAuthorizationSourceSnapshot(
        repository="blummer92/agent-os",
        pr_number=630,
        owner_login="Blummer92",
        owner_type=owner_type,
        comments_complete=complete,
        comments=tuple(comments),
    )


def comment(record, *, cid=1, author="Blummer92"):
    return MergeAuthorizationCommentSnapshot(
        comment_id=cid,
        author_login=author,
        created_at="2026-07-26T14:31:00Z",
        body=serialize_merge_authorization_comment(record),
    )


def test_merge_authorization_transport_round_trip_is_identity_stable():
    record, _ = _authorized()
    rebuilt = reconstruct_merge_authorization_record(
        serialize_merge_authorization_record(record)
    )
    assert rebuilt == record
    assert rebuilt.authorization_id == record.authorization_id
    assert rebuilt.authorization_revision == record.authorization_revision


def test_owner_authored_authorized_record_is_current():
    record, _ = _authorized()
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(comment(record))),
        repository="blummer92/agent-os",
        pr_number=630,
        expected_authorization_id=record.authorization_id,
    )
    assert result.status is MergeAuthorizationSourceStatus.CURRENT
    assert result.records == (record,)
    assert result.source_comment_ids == (1,)


def test_non_owner_record_cannot_create_authority():
    record, _ = _authorized()
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(comment(record, author="github-actions[bot]"))),
        repository="blummer92/agent-os",
        pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.BLOCKED
    assert result.records == ()


def test_incomplete_source_fails_closed():
    record, _ = _authorized()
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(comment(record), complete=False)),
        repository="blummer92/agent-os",
        pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("source.incomplete",)


def test_consumed_latest_revision_is_not_current():
    record, bundle = _authorized()
    from scripts.agent_os_issue_acceptance.merge_authorization import (
        record_merge_authorization_decision,
    )
    consumed = record_merge_authorization_decision(
        record,
        state="invalidated",
        decision_id="revoke-before-merge",
        authorizer_id="repository-owner",
        decision_at="2026-07-26T14:35:00Z",
    )
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(comment(record), comment(consumed, cid=2))),
        repository="blummer92/agent-os",
        pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.STALE
    assert result.records == ()


def test_conflicting_same_revision_fails_closed():
    record, _ = _authorized()
    payload = json.loads(serialize_merge_authorization_record(record))
    payload["decision_id"] = "other-decision"
    body = AUTHORIZATION_MARKER + "\n" + json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    )
    forged = MergeAuthorizationCommentSnapshot(
        comment_id=2,
        author_login="Blummer92",
        created_at="2026-07-26T14:32:00Z",
        body=body,
    )
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(comment(record), forged)),
        repository="blummer92/agent-os",
        pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION
