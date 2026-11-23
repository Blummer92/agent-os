"""Nov4 observation-1: omitted closure evidence must remain false."""
from tests.agent_os_issue_acceptance.test_merge_authorization import (
    _authorized, _evaluate, _pr, MERGE,
)
from scripts.agent_os_issue_acceptance.merge_authorization import (
    record_merge_execution_observation,
)


def test_nov4_observation_default_does_not_claim_issue_closure():
    authorization, _ = _authorized()
    observation, consumed = record_merge_execution_observation(
        authorization, _evaluate(authorization), _pr(),
        observed_merge_commit_sha=MERGE,
        observed_actor_id="repository-owner",
        observed_at="2026-07-26T14:45:00Z",
        audit_location="audit://merge/630",
        observed_merge_method="squash",
    )
    assert observation.linked_issue_closure_observed is False
    assert consumed.consumed_observation_id == observation.observation_id
    assert consumed.merge_authorized is False
