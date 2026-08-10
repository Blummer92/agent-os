import pytest

from scripts.agent_os_issue_labels.pr_planner import (
    PullRequestLabelEvidence,
    managed_label_families,
    plan_matches_head,
    plan_pull_request_labels,
)


def evidence(**changes):
    values = dict(
        repository="Blummer92/agent-os",
        pr_number=1021,
        head_sha="abcdef1234567890",
        draft=True,
        mergeable=True,
        conflicted=False,
        behind=False,
        validation_state="pending",
        blocking_review_threads=0,
        current_labels=("agent-os",),
    )
    values.update(changes)
    return PullRequestLabelEvidence(**values)


def test_draft_pending_current_clear_preserves_unmanaged_label():
    plan = plan_pull_request_labels(evidence())
    assert plan.desired_managed_labels == (
        "branch:current",
        "pr:draft",
        "review:clear",
        "validation:pending",
    )
    assert plan.unmanaged_labels_preserved == ("agent-os",)
    assert plan.external_write_authorized is False
    assert plan.side_effects_performed is False


def test_failing_replaces_stale_green_and_marks_blocked():
    plan = plan_pull_request_labels(evidence(
        validation_state="failing",
        current_labels=("validation:green", "pr:draft", "custom:keep"),
    ))
    assert "validation:failing" in plan.labels_to_add
    assert "pr:blocked" in plan.labels_to_add
    assert "validation:green" in plan.labels_to_remove
    assert "pr:draft" in plan.labels_to_remove
    assert plan.unmanaged_labels_preserved == ("custom:keep",)


def test_ready_green_mergeable_current_is_merge_ready():
    plan = plan_pull_request_labels(evidence(draft=False, validation_state="green"))
    assert "pr:merge-ready" in plan.desired_managed_labels


def test_behind_prevents_merge_ready_and_replaces_current():
    plan = plan_pull_request_labels(evidence(
        draft=False,
        validation_state="green",
        behind=True,
        current_labels=("branch:current", "pr:merge-ready"),
    ))
    assert "branch:behind" in plan.labels_to_add
    assert "branch:current" in plan.labels_to_remove
    assert "pr:ready-for-review" in plan.desired_managed_labels
    assert "pr:merge-ready" in plan.labels_to_remove


def test_conflict_marks_branch_and_lifecycle_blocked():
    plan = plan_pull_request_labels(evidence(conflicted=True))
    assert "branch:conflicted" in plan.desired_managed_labels
    assert "pr:blocked" in plan.desired_managed_labels


def test_blocking_review_marks_attention_and_blocked():
    plan = plan_pull_request_labels(evidence(blocking_review_threads=2))
    assert "review:needs-attention" in plan.desired_managed_labels
    assert "pr:blocked" in plan.desired_managed_labels


def test_idempotent_when_desired_labels_are_already_present():
    current = (
        "agent-os",
        "branch:current",
        "pr:draft",
        "review:clear",
        "validation:pending",
    )
    first = plan_pull_request_labels(evidence(current_labels=current))
    second = plan_pull_request_labels(evidence(current_labels=current))
    assert first == second
    assert first.labels_to_add == ()
    assert first.labels_to_remove == ()


def test_moved_head_invalidates_plan_binding():
    plan = plan_pull_request_labels(evidence())
    assert plan_matches_head(plan, "abcdef1234567890") is True
    assert plan_matches_head(plan, "1234567abcdef") is False


def test_managed_families_are_mutually_exclusive_and_unique():
    families = managed_label_families()
    labels = [label for family in families.values() for label in family]
    assert len(labels) == len(set(labels))


@pytest.mark.parametrize("state", ["", "success", "unknown"])
def test_unknown_validation_state_fails_closed(state):
    with pytest.raises(ValueError):
        evidence(validation_state=state)
