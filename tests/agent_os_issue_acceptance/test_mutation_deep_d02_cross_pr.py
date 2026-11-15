"""DEEP-D02: cross-PR authorization records cannot become source authority."""
from dataclasses import replace

from scripts.agent_os_issue_acceptance.merge_authorization import record_merge_authorization_decision
from scripts.agent_os_issue_acceptance.merge_authorization_source import (
    MergeAuthorizationSourceStatus, reacquire_merge_authorization_source,
)
from tests.agent_os_issue_acceptance.test_merge_authorization import AUTHORIZED, _candidate
from tests.agent_os_issue_acceptance.test_merge_authorization_source import Transport, comment, snapshot


def test_deep_d02_cross_pr_chain_rejected_at_source():
    pending = _candidate()
    other = replace(pending, binding=replace(pending.binding, pull_request_number=999),
                    authorization_id="", authorization_revision="")
    approved = record_merge_authorization_decision(
        other, state="authorized", decision_id="other-pr-approved",
        authorizer_id="repository-owner", decision_at=AUTHORIZED,
    )
    result = reacquire_merge_authorization_source(
        transport=Transport(snapshot(comment(other, cid=10), comment(approved, cid=11))),
        repository="blummer92/agent-os", pr_number=630,
    )
    assert result.status is MergeAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("source.trusted-record-malformed",)
    assert result.records == ()
