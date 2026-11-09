"""DEEP-D08: duplicate comment IDs invalidate owner evidence provenance."""
from scripts.agent_os_issue_acceptance.merge_authorization_source import (
    MergeAuthorizationSourceStatus, reacquire_merge_authorization_source,
)
from tests.agent_os_issue_acceptance.test_merge_authorization import _authorized, _candidate
from tests.agent_os_issue_acceptance.test_merge_authorization_source import (
    Transport, comment, snapshot,
)


def test_deep_d08_duplicate_comment_ids_do_not_produce_current_authority():
    authorized, _ = _authorized()
    pending = _candidate()
    assert pending.authorization_revision == authorized.previous_revision
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(
            comment(pending, cid=17), comment(authorized, cid=17),
        )),
        repository="blummer92/agent-os", pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("source.ambiguous",)
    assert result.records == ()
