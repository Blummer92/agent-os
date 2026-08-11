from dataclasses import replace

import pytest

from scripts.agent_os_issue_labels.pr_lifecycle import (
    lifecycle_invocation_reasons,
    reconcile_pull_request_lifecycle,
)
from scripts.agent_os_issue_labels.pr_planner import managed_labels
from scripts.agent_os_issue_labels.pr_reconciler import LivePullRequestSnapshot

SHA = "a" * 40
NEW_SHA = "b" * 40


class MutableProvider:
    def __init__(self, snapshot, *, fail_add=False, fail_remove=False):
        self.snapshot = snapshot
        self.available = tuple(managed_labels())
        self.fail_add = fail_add
        self.fail_remove = fail_remove
        self.labels = set(snapshot.labels)
        self.added = []
        self.removed = []
        self.read_count = 0

    def read(self, repository, pr_number):
        self.read_count += 1
        return replace(self.snapshot, labels=tuple(sorted(self.labels)))

    def available_labels(self, repository):
        return self.available

    def add_label(self, repository, pr_number, label):
        if self.fail_add:
            raise RuntimeError("add failed")
        self.added.append(label)
        self.labels.add(label)

    def remove_label(self, repository, pr_number, label):
        if self.fail_remove:
            raise RuntimeError("remove failed")
        self.removed.append(label)
        self.labels.remove(label)


def snap(**overrides):
    values = dict(
        repository="Blummer92/agent-os",
        pr_number=1038,
        head_sha=SHA,
        draft=True,
        mergeable=True,
        conflicted=False,
        behind=False,
        validation_state="pending",
        blocking_review_threads=0,
        labels=("human:keep",),
    )
    values.update(overrides)
    return LivePullRequestSnapshot(**values)


def invoke(provider, reason="draft-pr-created"):
    return reconcile_pull_request_lifecycle(
        provider,
        "Blummer92/agent-os",
        1038,
        invocation_reason=reason,
        caller_operation_evidence="operation:1038",
        caller_result_evidence="result:1038",
        dry_run=False,
        label_write_authorized=True,
    )


@pytest.mark.parametrize("reason", lifecycle_invocation_reasons())
def test_all_required_lifecycle_invocation_points_are_representable(reason):
    provider = MutableProvider(snap())
    result = reconcile_pull_request_lifecycle(provider, "Blummer92/agent-os", 1038, invocation_reason=reason)
    assert result.invocation_reason == reason
    assert result.reconciliation_status == "skipped"


def test_draft_pr_creation_reconciles_managed_labels_and_preserves_unmanaged():
    provider = MutableProvider(snap())
    result = invoke(provider)
    assert result.reconciliation_status == "converged"
    assert set(result.labels_added) == {"pr:draft", "validation:pending", "branch:current", "review:clear"}
    assert "human:keep" in provider.labels
    assert result.unmanaged_labels_preserved == ("human:keep",)


def test_head_move_before_mutation_recomputes_once_from_fresh_evidence():
    class MovingHeadProvider(MutableProvider):
        def read(self, repository, pr_number):
            self.read_count += 1
            head = SHA if self.read_count == 1 else NEW_SHA
            return replace(self.snapshot, head_sha=head, labels=tuple(sorted(self.labels)))

    provider = MovingHeadProvider(snap())
    result = invoke(provider, "head-sha-changed")
    assert result.recomputed_after_stale_head is True
    assert result.planned_head_sha == NEW_SHA
    assert result.verified_head_sha == NEW_SHA
    assert result.reconciliation_status == "converged"
    assert "head-recomputed-before-mutation" in result.reason_codes


def test_validation_transition_reconciles_failing_to_green():
    provider = MutableProvider(snap(draft=False, validation_state="failing"))
    first = invoke(provider, "validation-terminal")
    assert "validation:failing" in provider.labels
    assert first.reconciliation_status == "converged"

    provider.snapshot = replace(provider.snapshot, validation_state="green")
    second = invoke(provider, "validation-terminal")
    assert "validation:green" in provider.labels
    assert "validation:failing" not in provider.labels
    assert second.reconciliation_status == "converged"


def test_draft_ready_transition_reconciles_lifecycle_projection():
    provider = MutableProvider(snap())
    invoke(provider)
    provider.snapshot = replace(provider.snapshot, draft=False)
    result = invoke(provider, "draft-ready-transition")
    assert "pr:ready-for-review" in provider.labels
    assert "pr:draft" not in provider.labels
    assert result.reconciliation_status == "converged"


def test_review_attention_transition_round_trips():
    provider = MutableProvider(snap(draft=False))
    invoke(provider, "review-thread-state-changed")
    provider.snapshot = replace(provider.snapshot, blocking_review_threads=1)
    invoke(provider, "review-thread-state-changed")
    assert "review:needs-attention" in provider.labels
    assert "pr:blocked" in provider.labels

    provider.snapshot = replace(provider.snapshot, blocking_review_threads=0)
    result = invoke(provider, "review-thread-state-changed")
    assert "review:clear" in provider.labels
    assert result.reconciliation_status == "converged"


def test_branch_freshness_and_conflict_transitions_are_representable():
    provider = MutableProvider(snap(draft=False))
    invoke(provider, "branch-state-rechecked")
    provider.snapshot = replace(provider.snapshot, behind=True)
    invoke(provider, "branch-state-rechecked")
    assert "branch:behind" in provider.labels

    provider.snapshot = replace(provider.snapshot, behind=False, conflicted=True)
    invoke(provider, "branch-state-rechecked")
    assert "branch:conflicted" in provider.labels
    assert "pr:blocked" in provider.labels

    provider.snapshot = replace(provider.snapshot, conflicted=False)
    result = invoke(provider, "branch-state-rechecked")
    assert "branch:current" in provider.labels
    assert result.reconciliation_status == "converged"


def test_repeated_unchanged_invocation_performs_zero_writes():
    provider = MutableProvider(snap())
    invoke(provider)
    provider.added.clear()
    provider.removed.clear()
    result = invoke(provider, "final-state-readback")
    assert result.reconciliation_required is False
    assert result.side_effects_performed is False
    assert not provider.added and not provider.removed
    assert "managed-labels-unchanged" in result.reason_codes


def test_head_move_after_mutation_stays_stale_and_is_not_retried():
    class MoveOnReadbackProvider(MutableProvider):
        def read(self, repository, pr_number):
            self.read_count += 1
            head = NEW_SHA if self.read_count >= 3 else SHA
            return replace(self.snapshot, head_sha=head, labels=tuple(sorted(self.labels)))

    provider = MoveOnReadbackProvider(snap())
    result = invoke(provider, "head-sha-changed")
    assert result.reconciliation_status == "stale"
    assert result.recomputed_after_stale_head is False
    assert result.side_effects_performed is True


def test_item_local_failure_is_visible_and_later_invocation_can_succeed():
    provider = MutableProvider(snap(), fail_add=True)
    failed = invoke(provider)
    assert failed.reconciliation_status == "failed"
    assert failed.side_effects_performed is False

    provider.fail_add = False
    recovered = invoke(provider, "final-state-readback")
    assert recovered.reconciliation_status == "converged"


def test_invalid_invocation_reason_fails_closed():
    provider = MutableProvider(snap())
    with pytest.raises(ValueError, match="supported PR lifecycle event"):
        reconcile_pull_request_lifecycle(provider, "Blummer92/agent-os", 1038, invocation_reason="merge")


def test_result_preserves_caller_evidence_and_never_grants_lifecycle_authority():
    provider = MutableProvider(snap())
    result = invoke(provider)
    assert result.caller_operation_evidence == "operation:1038"
    assert result.caller_result_evidence == "result:1038"
    assert result.ready_for_review_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False
    assert result.review_resolution_authorized is False
    assert result.protected_setting_authorized is False
    assert result.production_authorized is False
    assert result.external_system_write_authorized is False
