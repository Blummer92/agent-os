"""M3: a CONSUMED-final valid chain is not current merge authority."""
from dataclasses import replace
import test_merge_authorization_source as fixture
from scripts.agent_os_issue_acceptance.merge_authorization import MergeAuthorizationState
from scripts.agent_os_issue_acceptance.merge_authorization_source import (
    MergeAuthorizationSourceStatus, reacquire_merge_authorization_source,
)


def test_m3_consumed_final_chain_is_stale_not_current():
    authorized, _ = fixture._authorized()
    pending = fixture._pending_for(authorized)
    consumed = replace(
        authorized, authorization_revision="", revision_number=3,
        previous_revision=authorized.authorization_revision,
        state=MergeAuthorizationState.CONSUMED,
        decision_id="merge-observation", authorizer_id="repository-owner",
        decision_at="2026-07-26T14:35:00Z",
        consumed_observation_id="merge-execution-observation:" + "e" * 64,
        reason_codes=("authorization.consumed",),
    )
    result = reacquire_merge_authorization_source(
        transport=fixture.Transport(fixture.snapshot(
            fixture.comment(pending, cid=1), fixture.comment(authorized, cid=2),
            fixture.comment(consumed, cid=3))),
        repository="blummer92/agent-os", pr_number=630,
        expected_authorization_id=authorized.authorization_id,
    )
    assert result.status is MergeAuthorizationSourceStatus.STALE
    assert result.reason_codes == ("authorization.consumed-or-not-current",)
    assert result.records == ()
