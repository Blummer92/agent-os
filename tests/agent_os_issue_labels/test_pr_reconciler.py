from dataclasses import replace

import pytest

from scripts.agent_os_issue_labels.pr_planner import managed_labels
from scripts.agent_os_issue_labels.pr_reconciler import (
    LivePullRequestSnapshot,
    reconcile_pull_request_batch,
    reconcile_pull_request_labels,
)

SHA = "a" * 40
NEW_SHA = "b" * 40


class FakeProvider:
    def __init__(self, snapshots, *, available=None, fail_add=False, fail_remove=False):
        self.snapshots = list(snapshots)
        self.available = tuple(available or managed_labels())
        self.fail_add = fail_add
        self.fail_remove = fail_remove
        self.added = []
        self.removed = []
        self.labels = set(self.snapshots[0].labels) if self.snapshots else set()
        self.read_count = 0

    def read(self, repository, pr_number):
        if not self.snapshots:
            raise RuntimeError("read failed")
        index = min(self.read_count, len(self.snapshots) - 1)
        base = self.snapshots[index]
        self.read_count += 1
        return replace(base, labels=tuple(sorted(self.labels)))

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
    values = dict(repository="Blummer92/agent-os", pr_number=1023, head_sha=SHA, draft=True,
                  mergeable=True, conflicted=False, behind=False, validation_state="pending",
                  blocking_review_threads=0, labels=("human:keep",))
    values.update(overrides)
    return LivePullRequestSnapshot(**values)


def test_dry_run_performs_zero_writes_and_preserves_unmanaged_labels():
    provider = FakeProvider([snap()])
    result = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023)
    assert result.convergence_status == "dry-run"
    assert not provider.added and not provider.removed
    assert result.unmanaged_labels_preserved == ("human:keep",)
    assert result.side_effects_performed is False


def test_converged_state_performs_zero_writes():
    labels = ("pr:draft", "validation:pending", "branch:current", "review:clear", "human:keep")
    provider = FakeProvider([snap(labels=labels)] * 3)
    result = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023, dry_run=False,
                                             label_write_authorized=True)
    assert result.convergence_status == "converged"
    assert not provider.added and not provider.removed


def test_add_remove_converges_without_touching_unmanaged_labels():
    labels = ("pr:ready-for-review", "validation:failing", "branch:behind", "review:needs-attention", "human:keep")
    provider = FakeProvider([snap(labels=labels)] * 3)
    result = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023, dry_run=False,
                                             label_write_authorized=True)
    assert result.convergence_status == "converged"
    assert set(result.labels_added) == {"pr:draft", "validation:pending", "branch:current", "review:clear"}
    assert set(result.labels_removed) == {"pr:ready-for-review", "validation:failing", "branch:behind", "review:needs-attention"}
    assert "human:keep" in provider.labels


def test_missing_managed_label_definition_fails_closed():
    provider = FakeProvider([snap()], available=tuple(managed_labels() - {"pr:draft"}))
    result = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023, dry_run=False,
                                             label_write_authorized=True)
    assert result.convergence_status == "blocked"
    assert result.reason_codes == ("managed-label-unavailable",)
    assert not provider.added


def test_write_requires_separate_label_authorization():
    provider = FakeProvider([snap()])
    result = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023, dry_run=False)
    assert result.reason_codes == ("label-write-authorization-required",)
    assert not provider.added


def test_moved_head_before_mutation_fails_closed():
    provider = FakeProvider([snap(), snap(head_sha=NEW_SHA)])
    result = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023, dry_run=False,
                                             label_write_authorized=True)
    assert result.convergence_status == "stale-head"
    assert result.reason_codes == ("head-moved-before-mutation",)
    assert not provider.added


def test_moved_head_on_readback_never_claims_convergence():
    provider = FakeProvider([snap(), snap(), snap(head_sha=NEW_SHA)])
    result = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023, dry_run=False,
                                             label_write_authorized=True)
    assert result.convergence_status == "stale-head"
    assert result.side_effects_performed is True


@pytest.mark.parametrize("failure", ["add", "remove"])
def test_provider_write_failure_is_visible(failure):
    labels = ("pr:ready-for-review", "validation:pending", "branch:current", "review:clear", "human:keep")
    provider = FakeProvider([snap(labels=labels)] * 3, fail_add=failure == "add", fail_remove=failure == "remove")
    result = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023, dry_run=False,
                                             label_write_authorized=True)
    assert result.convergence_status in {"write-failure", "partial-failure"}
    assert not result.convergence_status == "converged"


def test_readback_mismatch_is_not_success():
    class IgnoringProvider(FakeProvider):
        def add_label(self, repository, pr_number, label):
            self.added.append(label)
    provider = IgnoringProvider([snap()] * 3)
    result = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023, dry_run=False,
                                             label_write_authorized=True)
    assert result.convergence_status == "readback-mismatch"


def test_lifecycle_validation_branch_and_review_projection_comes_from_canonical_planner():
    provider = FakeProvider([snap(draft=False, validation_state="green", blocking_review_threads=0)] * 3)
    result = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023)
    assert set(result.desired_managed_labels) == {"pr:merge-ready", "validation:green", "branch:current", "review:clear"}

    blocked = FakeProvider([snap(draft=False, validation_state="green", blocking_review_threads=1)] * 3)
    result = reconcile_pull_request_labels(blocked, "Blummer92/agent-os", 1023)
    assert "pr:blocked" in result.desired_managed_labels
    assert "review:needs-attention" in result.desired_managed_labels


def test_batch_continues_after_item_local_read_failure():
    good = snap(pr_number=2)
    class BatchProvider(FakeProvider):
        def read(self, repository, pr_number):
            if pr_number == 1:
                raise RuntimeError("one item failed")
            return good
    provider = BatchProvider([good])
    batch = reconcile_pull_request_batch(provider, "Blummer92/agent-os", (1, 2))
    assert len(batch.results) == 2
    assert batch.results[0].convergence_status == "blocked"
    assert batch.results[1].convergence_status == "dry-run"


class FlakyOnceProvider(FakeProvider):
    """Raises on a single named label's first add, then behaves normally.

    Models a transient provider failure mid-mutation: the label is not
    added on that call, but earlier labels in the same batch already
    succeeded and must not be re-added on a later re-invocation.
    """

    def __init__(self, *args, fail_label, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_label = fail_label
        self._has_failed = False

    def add_label(self, repository, pr_number, label):
        if label == self.fail_label and not self._has_failed:
            self._has_failed = True
            raise RuntimeError("transient add failure")
        super().add_label(repository, pr_number, label)


def test_second_invocation_after_partial_failure_converges_without_duplicate_adds():
    # labels_to_add for this evidence, sorted: branch:current, pr:draft,
    # review:clear, validation:pending. Failing on "pr:draft" guarantees
    # "branch:current" is already added (and live) before the failure.
    labels = ("pr:ready-for-review", "validation:failing", "branch:behind", "review:needs-attention", "human:keep")
    provider = FlakyOnceProvider([snap(labels=labels)] * 6, fail_label="pr:draft")

    first = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023, dry_run=False,
                                           label_write_authorized=True)
    assert first.convergence_status == "partial-failure"
    assert first.labels_added == ("branch:current",)
    assert "branch:current" in provider.labels

    second = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023, dry_run=False,
                                            label_write_authorized=True)
    assert second.convergence_status == "converged"
    # The label already applied by the first (partial) attempt must not be
    # re-added: the retry boundary re-plans from live state instead of
    # blindly repeating the prior batch.
    assert "branch:current" not in second.labels_added
    assert set(second.labels_added) == {"pr:draft", "review:clear", "validation:pending"}
    assert provider.added.count("branch:current") == 1
    assert "human:keep" in provider.labels


def test_result_never_grants_lifecycle_merge_production_or_external_authority():
    provider = FakeProvider([snap()])
    result = reconcile_pull_request_labels(provider, "Blummer92/agent-os", 1023)
    assert result.ready_for_review_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False
    assert result.production_authorized is False
    assert result.external_system_write_authorized is False
