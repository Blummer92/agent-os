"""TRUST3756-H4: valid revision IDs do not establish valid chronology."""
from dataclasses import replace

from scripts.agent_os_issue_acceptance.merge_authorization_source import (
    MergeAuthorizationSourceStatus, reacquire_merge_authorization_source,
)
from tests.agent_os_issue_acceptance.test_merge_authorization import _authorized, _candidate
from tests.agent_os_issue_acceptance.test_merge_authorization_source import (
    Transport, comment, snapshot,
)


def test_trust_h4_backward_authorization_revision_time_fails_closed():
    authorized, _ = _authorized()
    pending = _candidate()
    earlier = replace(
        authorized, decision_at="2026-07-26T14:24:00Z",
        authorization_revision="",
    )
    assert earlier.decision_at < pending.decision_at
    assert earlier.previous_revision == pending.authorization_revision
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(
            comment(pending, cid=1), comment(earlier, cid=2),
        )),
        repository="blummer92/agent-os", pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("authorization.chain-invalid",)
    assert result.records == ()
