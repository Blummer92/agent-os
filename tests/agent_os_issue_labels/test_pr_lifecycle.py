from dataclasses import replace

import pytest

from scripts.agent_os_issue_labels.pr_lifecycle import (
    PullRequestCreationExpectation,
    lifecycle_invocation_reasons,
    reconcile_pull_request_lifecycle,
    verify_pull_request_creation,
)
from scripts.agent_os_issue_labels.pr_planner import managed_labels
from scripts.agent_os_issue_labels.pr_reconciler import LivePullRequestSnapshot

SHA = "a" * 40
NEW_SHA = "b" * 40


class MutableProvider:
    def __init__(self, snapshot, *, fail_add=False, fail_remove=False, fail_read=False):
        self.snapshot = snapshot
        self.available = tuple(managed_labels())
        self.fail_add = fail_add
        self.fail_remove = fail_remove
        self.fail_read = fail_read
        self.labels = set(snapshot.labels)
        self.added = []
        self.removed = []
        self.read_count = 0

    def read(self, repository, pr_number):
        self.read_count += 1
        if self.fail_read:
            raise RuntimeError("read failed")
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
        state="open",
        merged=False,
        base_ref="main",
        head_ref="agent/1038-test",
    )
    values.update(overrides)
    return LivePullRequestSnapshot(**values)


def creation_expectation(**overrides):
    values = dict(
        repository="Blummer92/agent-os",
        pr_number=1038,
        base_ref="main",
        head_ref="agent/1038-test",
        head_sha=SHA,
        draft_requested=True,
        merge_authorized=False,
    )
    values.update(overrides)
    return PullRequestCreationExpectation(**values)


def invoke(provider, reason="draft-pr-created", *, verify_creation=False, discoverable=True):
    kwargs = {}
    if verify_creation:
        kwargs = {
            "creation_expectation": creation_expectation(),
            "creation_discoverable": discoverable,
        }
    return reconcile_pull_request_lifecycle(
        provider,
        "Blummer92/agent-os",
        1038,
        invocation_reason=reason,
        caller_operation_evidence="operation:1038",
        caller_result_evidence="result:1038",
        dry_run=False,
        label_write_authorized=True,
        **kwargs,
    )


@pytest.mark.parametrize("reason", lifecycle_invocation_reasons())
def test_all_required_lifecycle_invocation_points_are_representable(reason):
    provider = MutableProvider(snap())
    result = reconcile_pull_request_lifecycle(provider, "Blummer92/agent-os", 1038, invocation_reason=reason)
    assert result.invocation_reason == reason
    assert result.reconciliation_status == "skipped"


def test_post_create_exact_readback_verifies_draft_before_label_followup():
    provider = MutableProvider(snap())
    result = invoke(provider, verify_creation=True)
    assert result.creation_verification.status == "verified"
    assert result.creation_verification.reportable_state == "draft"
    assert result.reconciliation_status == "converged"
    assert "canonical-readback-verified" in result.reason_codes


def test_post_create_ready_drift_blocks_all_followup_mutation():
    provider = MutableProvider(snap(draft=False))
    result = invoke(provider, verify_creation=True)
    assert result.reconciliation_status == "blocked"
    assert result.creation_verification.status == "state-drift"
    assert result.creation_verification.reportable_state == "ready-for-review"
    assert "draft-ready-state-drift" in result.reason_codes
    assert not provider.added and not provider.removed


def test_post_create_unauthorized_merge_is_terminal_incident_and_blocks_mutation():
    provider = MutableProvider(snap(draft=False, state="closed", merged=True))
    result = invoke(provider, verify_creation=True)
    assert result.reconciliation_status == "blocked"
    assert result.creation_verification.status == "unauthorized-terminal-state"
    assert result.creation_verification.reportable_state == "merged"
    assert "unauthorized-terminal-state" in result.reason_codes
    assert result.merge_authorized is False
    assert not provider.added and not provider.removed


def test_post_create_missing_canonical_readback_is_uncertain_and_never_retried_as_create():
    provider = MutableProvider(snap(), fail_read=True)
    verification = verify_pull_request_creation(provider, creation_expectation(), discoverable=False)
    assert verification.status == "uncertain"
    assert verification.mutation_allowed is False
    assert verification.reportable_state == "creation-uncertain"
    assert verification.reason_codes == ("canonical-readback-failed:RuntimeError",)
    assert provider.read_count == 1


def test_exact_canonical_lookup_can_establish_discoverability_despite_secondary_list_lag():
    provider = MutableProvider(snap())
    verified = verify_pull_request_creation(provider, creation_expectation(), discoverable=True)
    assert verified.status == "verified"
    assert verified.discoverable is True

    unproven = verify_pull_request_creation(provider, creation_expectation(), discoverable=False)
    assert unproven.status == "state-drift"
    assert "canonical-discoverability-unproven" in unproven.reason_codes


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"repository": "other/repo"}, "repository-mismatch"),
        ({"pr_number": 999}, "pr-number-mismatch"),
        ({"head_sha": NEW_SHA}, "head-sha-mismatch"),
        ({"base_ref": "release"}, "base-ref-mismatch"),
        ({"head_ref": "agent/other"}, "head-ref-mismatch"),
    ],
)
def test_post_create_identity_mismatch_fails_closed(override, reason):
    provider = MutableProvider(snap(**override))
    verification = verify_pull_request_creation(provider, creation_expectation(), discoverable=True)
    assert verification.status == "state-drift"
    assert reason in verification.reason_codes
    assert verification.mutation_allowed is False


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


def test_creation_verification_requires_explicit_discoverability_evidence():
    provider = MutableProvider(snap())
    with pytest.raises(ValueError, match="canonical discoverability evidence"):
        reconcile_pull_request_lifecycle(
            provider,
            "Blummer92/agent-os",
            1038,
            invocation_reason="draft-pr-created",
            creation_expectation=creation_expectation(),
        )
    assert provider.read_count == 0


@pytest.mark.parametrize("evidence_field", ["caller_operation_evidence", "caller_result_evidence"])
def test_invalid_caller_evidence_fails_before_provider_reads_or_writes(evidence_field):
    provider = MutableProvider(snap())
    kwargs = {
        "caller_operation_evidence": "operation:1038",
        "caller_result_evidence": "result:1038",
        evidence_field: "   ",
    }
    with pytest.raises(ValueError, match="caller evidence identifiers"):
        reconcile_pull_request_lifecycle(
            provider,
            "Blummer92/agent-os",
            1038,
            invocation_reason="draft-pr-created",
            dry_run=False,
            label_write_authorized=True,
            **kwargs,
        )
    assert provider.read_count == 0
    assert not provider.added and not provider.removed


def test_result_preserves_caller_evidence_and_never_grants_lifecycle_authority():
    provider = MutableProvider(snap())
    result = invoke(provider, verify_creation=True)
    assert result.caller_operation_evidence == "operation:1038"
    assert result.caller_result_evidence == "result:1038"
    assert result.ready_for_review_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False
    assert result.review_resolution_authorized is False
    assert result.protected_setting_authorized is False
    assert result.production_authorized is False
    assert result.external_system_write_authorized is False
    assert result.creation_verification.merge_authorized is False
    assert result.creation_verification.issue_closure_authorized is False
