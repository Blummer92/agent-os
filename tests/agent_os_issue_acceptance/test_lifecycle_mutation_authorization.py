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
        pull_request_number=2200,
        requested_mutations=("close-issue",),
        authorizer_id="repository-owner",
        decision_id="request-interpretation:2149-release",
        decision_recorded=True,
    )
    data.update(changes)
    return LifecycleOwnerDecision(**data)


def pr_snapshot(**changes):
    data = dict(
        repository="Blummer92/agent-os",
        issue_number=None,
        pull_request_number=2200,
        source_head=HEAD,
        base_head=BASE,
        pr_state="ready",
        merged=False,
        issue_state=None,
        review_state="clear",
        unresolved_threads=0,
        lifecycle_labels=("status:ready",),
        observed_revision="pr-readback-1",
    )
    data.update(changes)
    return LifecycleStateSnapshot(**data)


def pr_decision(**changes):
    data = dict(
        repository="Blummer92/agent-os",
        issue_number=None,
        pull_request_number=2200,
        requested_mutations=("replace-lifecycle-labels",),
        authorizer_id="repository-owner",
        decision_id="pr-label-decision:2200",
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


def test_ordinary_lane_without_distinct_owner_decision_cannot_produce_authority():
    with pytest.raises(PermissionError):
        produce_lifecycle_mutation_authorization(decision(decision_recorded=False), snapshot())


@pytest.mark.parametrize("changes", [{"repository": "Other/repo"}, {"issue_number": 2150}, {"pull_request_number": 2201}])
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
    authorization = produce_lifecycle_mutation_authorization(decision(requested_mutations=("merge",)), observed)
    result = evaluate_lifecycle_mutation(authorization, observed, "close-issue")
    assert result.admitted is False
    assert "authorization-mutation-not-permitted" in result.reason_codes


def test_pr_only_label_mutation_uses_truthful_pr_identity_without_issue_identity():
    observed = pr_snapshot()
    authorization = produce_lifecycle_mutation_authorization(pr_decision(), observed)
    result = evaluate_lifecycle_mutation(authorization, observed, "replace-lifecycle-labels")
    assert result.admitted is True
    assert authorization.issue_number is None
    assert authorization.pull_request_number == 2200


def test_pr_only_authority_cannot_admit_issue_closure():
    observed = pr_snapshot()
    authorization = produce_lifecycle_mutation_authorization(pr_decision(requested_mutations=("close-issue",)), observed)
    result = evaluate_lifecycle_mutation(authorization, observed, "close-issue")
    assert result.admitted is False
    assert "mutation-precondition-not-met" in result.reason_codes


def test_wrong_pr_identity_fails_closed_without_fabricated_issue_identity():
    observed = pr_snapshot()
    authorization = produce_lifecycle_mutation_authorization(pr_decision(), observed)
    drifted = pr_snapshot(pull_request_number=2201)
    result = evaluate_lifecycle_mutation(authorization, drifted, "replace-lifecycle-labels")
    assert result.admitted is False
    assert "identity-pull-request-mismatch" in result.reason_codes


def test_pr_only_snapshot_requires_a_real_pr_identity():
    with pytest.raises(ValueError):
        pr_snapshot(pull_request_number=None)


def test_pr_only_issue_state_must_not_be_fabricated():
    with pytest.raises(ValueError):
        pr_snapshot(issue_state="open")


def test_pr_only_label_authority_stays_bound_to_head_review_labels_and_revision():
    observed = pr_snapshot()
    authorization = produce_lifecycle_mutation_authorization(pr_decision(), observed)
    drifted = pr_snapshot(
        source_head="c" * 40,
        review_state="blocked",
        unresolved_threads=1,
        lifecycle_labels=("status:blocked",),
        observed_revision="pr-readback-2",
    )
    result = evaluate_lifecycle_mutation(authorization, drifted, "replace-lifecycle-labels")
    assert result.admitted is False
    assert result.status is AdmissionStatus.STALE
    assert {"authorization-stale", "pull-request-head-changed", "review-state-changed", "review-thread-state-changed", "lifecycle-label-state-changed"}.issubset(result.reason_codes)
