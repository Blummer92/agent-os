"""NC04 secondary probe (Wave 3, DISPOSABLE — not a permanent test): comment
arrival order must not matter.

Same M3 chain (pending rev 1, authorized rev 2, consumed rev 3) with the
comments supplied in reverse cid order. Clean source still reports STALE
(revisions are ordered by revision_number, not arrival); the NC04 mutant
still selects the older AUTHORIZED revision as current.
"""
from dataclasses import replace

import test_merge_authorization_source as fixture
from scripts.agent_os_issue_acceptance.merge_authorization import (
    MergeAuthorizationState,
)
from scripts.agent_os_issue_acceptance.merge_authorization_source import (
    MergeAuthorizationSourceStatus,
    reacquire_merge_authorization_source,
)


def test_nc04_reordered_comments_consumed_final_still_stale():
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
            fixture.comment(consumed, cid=3), fixture.comment(authorized, cid=2),
            fixture.comment(pending, cid=1))),
        repository="blummer92/agent-os", pr_number=630,
        expected_authorization_id=authorized.authorization_id,
    )
    assert result.status is MergeAuthorizationSourceStatus.STALE
    assert result.reason_codes == ("authorization.consumed-or-not-current",)
    assert result.records == ()
