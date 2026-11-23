"""Nov4-auth-109: revision progression must not skip numbers."""
from scripts.agent_os_issue_acceptance.merge_authorization import (
    MergeAuthorizationState, record_merge_authorization_decision,
)
from tests.agent_os_issue_acceptance.test_merge_authorization import (
    _candidate, AUTHORIZED,
)


def test_nov4_auth_109_revision_increments_exactly_once():
    pending = _candidate()
    authorized = record_merge_authorization_decision(
        pending, state="authorized", decision_id="approve",
        authorizer_id="repository-owner", decision_at=AUTHORIZED,
    )
    assert authorized.revision_number == pending.revision_number + 1
    assert authorized.revision_number == 2
    assert authorized.previous_revision == pending.authorization_revision
    assert authorized.state is MergeAuthorizationState.AUTHORIZED
    assert authorized.authorization_id == pending.authorization_id
