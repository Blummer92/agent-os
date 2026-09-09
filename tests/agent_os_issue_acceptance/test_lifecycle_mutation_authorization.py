import pytest

from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
    produce_lifecycle_mutation_authorization,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    AdmissionStatus,
    LifecycleStateSnapshot,
    evaluate_lifecycle_mutation,
)

HEAD = "a" * 40
BASE = "b" * 40


def snapshot(**changes):
    data = dict(
        repository="Blummer92/agent-os",
        issue_number=2149,
        pull_request_number=2200,
        source_head=HEAD,
        base_head=BASE,
        pr_state="ready",
        merged=True,
        issue_state="open",
        review_state="clear",
        unresolved_threads=0,
        lifecycle_labels=("status:ready",),
        observed_revision="terminal-readback-1",
    )
    data.update(changes)
    return LifecycleStateSnapshot(**data)


def decision(**changes):
    data = dict(
        repository="Blummer92/agent-os",
        issue_number=2149,
        requested_mutations=("close-issue",),
        authorizer_id="repository-owner",
        decision_id="request-interpretation:2149-release",
        decision_recorded=True,
    )
    data.update(changes)
    return LifecycleOwnerDecision(**data)


def test_recorded_owner_decision_produces_content_bound_close_authorization():
    observed = snapshot()
    authorization = produce_lifecycle_mutation_authorization(decision(), observed)
    result = evaluate_lifecycle_mutation(authorization, observed, "close-issue")

    assert result.status is AdmissionStatus.ADMITTED
    assert result.admitted is True
    assert result.authorization_id == authorization.authorization_id
    assert result.snapshot_id == observed.snapshot_id
    assert authorization.decision_id == "request-interpretation:2149-release"


def test_ordinary_lane_without_distinct_owner_decision_cannot_produce_authority():
    with pytest.raises(PermissionError):
        produce_lifecycle_mutation_authorization(
            decision(decision_recorded=False), snapshot()
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"repository": "Other/repo"},
        {"issue_number": 2150},
    ],
)
def test_wrong_owner_decision_target_fails_closed(changes):
    with pytest.raises(ValueError):
        produce_lifecycle_mutation_authorization(decision(**changes), snapshot())


def test_authorization_is_bound_to_snapshot_and_drift_is_refused():
    observed = snapshot()
    authorization = produce_lifecycle_mutation_authorization(decision(), observed)
    drifted = snapshot(source_head="c" * 40, observed_revision="terminal-readback-2")

    result = evaluate_lifecycle_mutation(authorization, drifted, "close-issue")
    assert result.admitted is False
    assert result.status is AdmissionStatus.STALE
    assert "pull-request-head-changed" in result.reason_codes
    assert "authorization-stale" in result.reason_codes


def test_merge_decision_does_not_implicitly_authorize_closure():
    observed = snapshot()
    authorization = produce_lifecycle_mutation_authorization(
        decision(requested_mutations=("merge",)), observed
    )
    result = evaluate_lifecycle_mutation(authorization, observed, "close-issue")
    assert result.admitted is False
    assert "authorization-mutation-not-permitted" in result.reason_codes


def test_producer_supports_existing_label_mutation_contract_without_second_model():
    observed = snapshot(merged=False)
    authorization = produce_lifecycle_mutation_authorization(
        decision(requested_mutations=("replace-lifecycle-labels",)), observed
    )
    result = evaluate_lifecycle_mutation(
        authorization, observed, "replace-lifecycle-labels"
    )
    assert result.admitted is True
