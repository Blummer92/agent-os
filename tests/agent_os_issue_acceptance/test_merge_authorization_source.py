from __future__ import annotations

import json
from dataclasses import replace

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
    github_comment_snapshot,
    reacquire_merge_authorization_source,
    serialize_merge_authorization_comment,
)
from tests.agent_os_issue_acceptance.test_merge_authorization import _authorized, _candidate


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


def _pending_for(record):
    pending = _candidate()
    assert pending.authorization_revision == record.previous_revision
    return pending


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
        transport=Transport(snapshot(comment(_pending_for(record), cid=0), comment(record))),
        repository="blummer92/agent-os",
        pr_number=630,
        expected_authorization_id=record.authorization_id,
    )
    assert result.status is MergeAuthorizationSourceStatus.CURRENT
    assert result.records == (record,)
    assert result.source_comment_ids == (0, 1)


def test_non_owner_record_cannot_create_authority():
    record, _ = _authorized()
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(comment(record, author="github-actions[bot]"))),
        repository="blummer92/agent-os",
        pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.BLOCKED
    assert result.records == ()


def test_app_performed_owner_comment_cannot_authorize():
    """S2 (#3734, live-verified): PR #3734 comments 6400749120 and
    6400951989 display author Blummer92 yet carry
    performed_via_github_app.slug == "chatgpt-codex-connector". An
    owner-login record performed through an app must fail closed,
    even when its revision chain is otherwise complete."""
    record, _ = _authorized()
    pending = comment(_pending_for(record), cid=0)
    authorized = MergeAuthorizationCommentSnapshot(
        comment_id=1,
        author_login="Blummer92",
        created_at="2026-07-26T14:31:00Z",
        body=serialize_merge_authorization_comment(record),
        performed_via_github_app_slug="chatgpt-codex-connector",
    )
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(pending, authorized)),
        repository="blummer92/agent-os",
        pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("source.app-performed-record",)
    assert result.records == ()


def test_github_comment_snapshot_captures_app_performance():
    from types import SimpleNamespace
    from datetime import datetime, timezone

    def fake(app):
        comment = SimpleNamespace(
            id=7,
            user=SimpleNamespace(login="Blummer92"),
            created_at=datetime(2026, 7, 26, 14, 31, tzinfo=timezone.utc),
            body="body",
        )
        if app is not None:
            comment.performed_via_github_app = app
        return comment

    assert github_comment_snapshot(fake(SimpleNamespace(slug="chatgpt-codex-connector"))).performed_via_github_app_slug == "chatgpt-codex-connector"
    assert github_comment_snapshot(fake(SimpleNamespace())).performed_via_github_app_slug == "app-performed"
    assert github_comment_snapshot(fake(None)).performed_via_github_app_slug is None


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
        transport=Transport(snapshot(comment(_pending_for(record), cid=0), comment(record), comment(consumed, cid=2))),
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
        transport=Transport(snapshot(comment(_pending_for(record), cid=0), comment(record), forged)),
        repository="blummer92/agent-os",
        pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION


_CLAUDE_CODE_ATTRIBUTION_FOOTER = (
    "\n\n---\n_Generated by [Claude Code](https://claude.ai/code)_"
)


def _footed_comment(record, footer=_CLAUDE_CODE_ATTRIBUTION_FOOTER, *, cid=1, author="Blummer92"):
    return MergeAuthorizationCommentSnapshot(
        comment_id=cid,
        author_login=author,
        created_at="2026-07-26T14:31:00Z",
        body=serialize_merge_authorization_comment(record) + footer,
    )


def test_exact_connector_footer_is_rejected_not_stripped():
    """S2 (#3734): a Claude Code footer is agent-generation evidence.

    Stripping it would erase that evidence and promote an agent-generated
    comment into owner authority. Footer-bearing trusted records now
    fail closed as malformed; a direct owner decision carries no footer.
    """
    record, _ = _authorized()
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(comment(_pending_for(record), cid=0), _footed_comment(record))),
        repository="blummer92/agent-os",
        pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("source.trusted-record-malformed",)
    assert result.records == ()


_LEGACY_CLAUDE_CODE_FOOTER = (
    "\n\n---\n_Generated by [Claude Code](https://claude.ai)_"
)


def test_legacy_connector_footer_is_rejected_like_other_footers():
    """S2 (#3734): the bare Claude Code footer is rejected for the same
    reason as the /code footer -- approval_source parity does not apply
    to merge authorization, whose provenance bar is owner-direct."""
    record, _ = _authorized()
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(comment(_pending_for(record), cid=0), _footed_comment(record, _LEGACY_CLAUDE_CODE_FOOTER))),
        repository="blummer92/agent-os",
        pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("source.trusted-record-malformed",)
    assert result.records == ()
    for footer in (
        _LEGACY_CLAUDE_CODE_FOOTER + _CLAUDE_CODE_ATTRIBUTION_FOOTER,
        _CLAUDE_CODE_ATTRIBUTION_FOOTER + _LEGACY_CLAUDE_CODE_FOOTER,
        _LEGACY_CLAUDE_CODE_FOOTER + _LEGACY_CLAUDE_CODE_FOOTER,
    ):
        result = reacquire_merge_authorization_source(
            transport=Transport(snapshot(_footed_comment(record, footer))),
            repository="blummer92/agent-os",
            pr_number=630,
        )
        assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION, footer
        assert result.reason_codes == ("source.trusted-record-malformed",), footer


def test_mutated_footer_or_extra_lines_still_fail_closed():
    record, _ = _authorized()
    mutated = [
        _CLAUDE_CODE_ATTRIBUTION_FOOTER.replace("https://claude.ai/code", "https://claude.com"),
        _CLAUDE_CODE_ATTRIBUTION_FOOTER.replace("Claude Code", "Claude"),
        "\nextra line",
        _CLAUDE_CODE_ATTRIBUTION_FOOTER + "\ntrailing prose",
        _CLAUDE_CODE_ATTRIBUTION_FOOTER + _CLAUDE_CODE_ATTRIBUTION_FOOTER,
        _CLAUDE_CODE_ATTRIBUTION_FOOTER + " ",
    ]
    for footer in mutated:
        result = reacquire_merge_authorization_source(
            transport=Transport(snapshot(_footed_comment(record, footer))),
            repository="blummer92/agent-os",
            pr_number=630,
        )
        assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION, footer
        assert result.reason_codes == ("source.trusted-record-malformed",), footer


def test_footed_non_owner_comment_still_cannot_authorize():
    record, _ = _authorized()
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(_footed_comment(record, author="github-actions[bot]"))),
        repository="blummer92/agent-os",
        pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.BLOCKED
    assert result.records == ()

def test_missing_predecessor_refuses_authorization():
    record, _ = _authorized()
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(comment(record))),
        repository="blummer92/agent-os", pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("authorization.chain-invalid",)


def test_revision_gap_and_wrong_predecessor_fail_closed():
    record, _ = _authorized()
    pending = _pending_for(record)
    gap = replace(
        record, revision_number=3, authorization_revision="",
        previous_revision=record.authorization_revision,
        decision_at="2026-07-26T14:35:00Z",
    )
    wrong = replace(
        record, authorization_revision="",
        previous_revision="merge-authorization-revision:" + "1" * 64,
    )
    for later in (gap, wrong):
        result = reacquire_merge_authorization_source(
            transport=Transport(snapshot(comment(pending), comment(later, cid=2))),
            repository="blummer92/agent-os", pr_number=630,
        )
        assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION
        assert result.reason_codes == ("authorization.chain-invalid",)


def test_invalidated_authorization_cannot_be_revived():
    record, _ = _authorized()
    from scripts.agent_os_issue_acceptance.merge_authorization import record_merge_authorization_decision
    invalidated = record_merge_authorization_decision(
        record, state="invalidated", decision_id="revoke",
        authorizer_id="repository-owner", decision_at="2026-07-26T14:35:00Z",
    )
    forged = replace(
        invalidated, authorization_revision="", revision_number=4,
        previous_revision=invalidated.authorization_revision,
        state=MergeAuthorizationState.AUTHORIZED,
        revoked_authorization_id=None, reason_codes=(),
        decision_at="2026-07-26T14:36:00Z",
    )
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(
            comment(_pending_for(record)), comment(record, cid=2),
            comment(invalidated, cid=3), comment(forged, cid=4),
        )), repository="blummer92/agent-os", pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("authorization.chain-invalid",)


def test_consumed_authorization_cannot_be_revived():
    record, _ = _authorized()
    consumed = replace(
        record, authorization_revision="", revision_number=3,
        previous_revision=record.authorization_revision,
        state=MergeAuthorizationState.CONSUMED,
        decision_id="merge-observation", authorizer_id="repository-owner",
        decision_at="2026-07-26T14:35:00Z",
        consumed_observation_id="merge-execution-observation:" + "e" * 64,
        reason_codes=("authorization.consumed",),
    )
    forged = replace(
        consumed, authorization_revision="", revision_number=4,
        previous_revision=consumed.authorization_revision,
        state=MergeAuthorizationState.AUTHORIZED,
        consumed_observation_id=None, reason_codes=(),
        decision_at="2026-07-26T14:36:00Z",
    )
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(
            comment(_pending_for(record)), comment(record, cid=2),
            comment(consumed, cid=3), comment(forged, cid=4),
        )), repository="blummer92/agent-os", pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("authorization.chain-invalid",)
