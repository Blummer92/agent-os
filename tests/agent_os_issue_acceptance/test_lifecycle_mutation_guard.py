from dataclasses import replace

import pytest

from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    AdmissionStatus,
    LifecycleMutationAuthorization,
    LifecycleStateSnapshot,
    evaluate_lifecycle_mutation,
)

HEAD = "a" * 40
BASE = "b" * 40


def snapshot(**changes):
    data = dict(repository="Blummer92/agent-os", issue_number=768, pull_request_number=800, source_head=HEAD, base_head=BASE, pr_state="draft", merged=False, issue_state="open", review_state="clear", unresolved_threads=0, lifecycle_labels=("status:ready",), observed_revision="observation-1")
    data.update(changes)
    return LifecycleStateSnapshot(**data)


def authorization(**changes):
    data = dict(schema_version="1.0", repository="Blummer92/agent-os", issue_number=768, pull_request_number=800, authorized_mutations=("mark-ready",), expected_source_head=HEAD, expected_base_head=BASE, expected_pr_state="draft", expected_merged=False, expected_issue_state="open", expected_review_state="clear", expected_unresolved_threads=0, expected_lifecycle_labels=("status:ready",), observed_at_revision="observation-1", state="authorized", authorizer_id="repository-owner", decision_id="decision-1")
    data.update(changes)
    return LifecycleMutationAuthorization(**data)


@pytest.mark.parametrize(("mutation", "snapshot_changes", "auth_changes"), [("mark-ready", {}, {}), ("mark-draft", {"pr_state": "ready"}, {"expected_pr_state": "ready"}), ("merge", {"pr_state": "ready"}, {"expected_pr_state": "ready"})])
def test_valid_admissions(mutation, snapshot_changes, auth_changes):
    auth = authorization(authorized_mutations=(mutation,), **auth_changes)
    result = evaluate_lifecycle_mutation(auth, snapshot(**snapshot_changes), mutation)
    assert result.admitted is True
    assert result.status is AdmissionStatus.ADMITTED
    assert not result.reason_codes


def test_ready_does_not_authorize_merge():
    result = evaluate_lifecycle_mutation(authorization(), snapshot(), "merge")
    assert result.admitted is False
    assert "authorization-mutation-not-permitted" in result.reason_codes


def test_merge_does_not_authorize_close():
    auth = authorization(authorized_mutations=("merge",), expected_pr_state="ready")
    result = evaluate_lifecycle_mutation(auth, snapshot(pr_state="ready"), "close-issue")
    assert "authorization-mutation-not-permitted" in result.reason_codes


@pytest.mark.parametrize(("snapshot_changes", "reason"), [({"repository": "Other/repo"}, "identity-repository-mismatch"), ({"issue_number": 769}, "identity-issue-mismatch"), ({"pull_request_number": 801}, "identity-pull-request-mismatch"), ({"source_head": "c" * 40}, "pull-request-head-changed"), ({"base_head": "d" * 40}, "pull-request-base-changed"), ({"pr_state": "ready"}, "pull-request-ready-state-changed"), ({"merged": True}, "pull-request-merged-state-changed"), ({"issue_state": "closed"}, "issue-state-changed"), ({"review_state": "blocked"}, "review-state-changed"), ({"unresolved_threads": 1}, "review-thread-state-changed"), ({"lifecycle_labels": ("status:blocked",)}, "lifecycle-label-state-changed"), ({"observed_revision": "observation-2"}, "authorization-stale")])
def test_state_movement_fails_closed(snapshot_changes, reason):
    result = evaluate_lifecycle_mutation(authorization(), snapshot(**snapshot_changes), "mark-ready")
    assert result.admitted is False
    assert reason in result.reason_codes


@pytest.mark.parametrize("state", ["pending", "rejected", "expired", "invalidated", "consumed", "superseded"])
def test_non_authorized_lifecycle_states_fail_closed(state):
    result = evaluate_lifecycle_mutation(authorization(state=state), snapshot(), "mark-ready")
    assert result.admitted is False
    assert "authorization-not-authorized" in result.reason_codes


@pytest.mark.parametrize(("mutation", "snapshot_changes", "auth_changes"), [("mark-ready", {"pr_state": "ready"}, {"expected_pr_state": "ready"}), ("mark-draft", {}, {}), ("merge", {}, {}), ("close-issue", {"issue_state": "closed"}, {"expected_issue_state": "closed"}), ("reopen-issue", {}, {})])
def test_logically_incompatible_mutations_fail_closed(mutation, snapshot_changes, auth_changes):
    auth = authorization(authorized_mutations=(mutation,), **auth_changes)
    result = evaluate_lifecycle_mutation(auth, snapshot(**snapshot_changes), mutation)
    assert result.admitted is False
    assert "mutation-precondition-not-met" in result.reason_codes


def test_duplicate_evaluation_is_deterministic_and_inputs_unchanged():
    auth = authorization()
    observed = snapshot()
    before_auth = auth.to_dict()
    before_snapshot = observed.to_dict()
    first = evaluate_lifecycle_mutation(auth, observed, "mark-ready")
    second = evaluate_lifecycle_mutation(auth, observed, "mark-ready")
    assert first == second
    assert first.result_id == second.result_id
    assert auth.to_dict() == before_auth
    assert observed.to_dict() == before_snapshot


def test_content_identity_changes_when_governed_input_changes():
    assert snapshot().snapshot_id != snapshot(lifecycle_labels=("status:ready", "type:implementation")).snapshot_id


class EvilStr(str):
    def __str__(self):
        raise AssertionError("must not coerce")


class EvilTuple(tuple):
    def __iter__(self):
        raise AssertionError("must not iterate subclass")


def test_hostile_subclasses_fail_before_behavior():
    with pytest.raises(TypeError):
        authorization(repository=EvilStr("Blummer92/agent-os"))
    with pytest.raises(TypeError):
        authorization(authorized_mutations=EvilTuple(("mark-ready",)))


def test_collection_bounds_and_duplicate_labels():
    with pytest.raises((TypeError, ValueError)):
        authorization(authorized_mutations=tuple(f"x-{i}" for i in range(9)))
    with pytest.raises(ValueError):
        snapshot(lifecycle_labels=("status:ready", "status:ready"))


def test_identity_reconstruction_rejects_tampering():
    auth = authorization()
    with pytest.raises(ValueError):
        replace(auth, authorization_id="lifecycle-authorization:" + "0" * 64)
    observed = snapshot()
    with pytest.raises(ValueError):
        replace(observed, snapshot_id="lifecycle-state-snapshot:" + "0" * 64)


def test_no_mutation_or_io_surface_is_exposed():
    for value in (authorization(), snapshot()):
        assert not hasattr(value, "execute")
        assert not hasattr(value, "run")
        assert not hasattr(value, "write")
        assert not hasattr(value, "callback")
