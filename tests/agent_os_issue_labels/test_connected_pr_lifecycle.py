from dataclasses import replace

import pytest

from scripts.agent_os_issue_labels.connected_pr_lifecycle import converge_connected_pull_request_lifecycle
from scripts.agent_os_issue_labels.pr_lifecycle import PullRequestTerminalExpectation
from scripts.agent_os_issue_labels.pr_planner import managed_labels
from scripts.agent_os_issue_labels.pr_reconciler import LivePullRequestSnapshot
from tests.agent_os_issue_labels.lifecycle_admission import admitted_lifecycle_labels
from tests.agent_os_issue_labels.lifecycle_admission import refused_lifecycle_labels

SHA = "a" * 40


class Provider:
    def __init__(self):
        self.snapshot = LivePullRequestSnapshot(repository="Blummer92/agent-os", pr_number=2145, head_sha=SHA, draft=True, mergeable=True, conflicted=False, behind=False, validation_state="pending", blocking_review_threads=0, labels=("human:keep",), state="open", merged=False, base_ref="main", head_ref="agent/2145-test")
        self.labels = set(self.snapshot.labels)
    def read(self, repository, pr_number): return replace(self.snapshot, labels=tuple(sorted(self.labels)))
    def available_labels(self, repository): return tuple(managed_labels())
    def add_label(self, repository, pr_number, label): self.labels.add(label)
    def remove_label(self, repository, pr_number, label): self.labels.remove(label)


def test_connected_draft_creation_converges_managed_labels_before_terminal_success():
    provider = Provider()
    result = converge_connected_pull_request_lifecycle(provider, "Blummer92/agent-os", 2145, invocation_reason="draft-pr-created", lifecycle_admission=admitted_lifecycle_labels())
    assert result.terminal_success is True
    assert "pr:draft" in provider.labels
    assert "validation:pending" in provider.labels
    assert "human:keep" in provider.labels


def test_connected_lifecycle_without_label_write_authority_is_not_terminal():
    result = converge_connected_pull_request_lifecycle(Provider(), "Blummer92/agent-os", 2145, invocation_reason="draft-pr-created", lifecycle_admission=refused_lifecycle_labels())
    assert result.terminal_success is False
    assert "connected-pr-label-convergence-not-proven" in result.reason_codes


def test_connected_ready_transition_reconciles_managed_labels_before_terminal_success():
    provider = Provider()
    created = converge_connected_pull_request_lifecycle(
        provider,
        "Blummer92/agent-os",
        2145,
        invocation_reason="draft-pr-created",
        lifecycle_admission=admitted_lifecycle_labels(),
    )
    assert created.terminal_success is True
    assert "pr:draft" in provider.labels

    provider.snapshot = replace(provider.snapshot, draft=False)
    ready = converge_connected_pull_request_lifecycle(
        provider,
        "Blummer92/agent-os",
        2145,
        invocation_reason="draft-ready-transition",
        lifecycle_admission=admitted_lifecycle_labels(),
    )
    assert ready.terminal_success is True
    assert "pr:ready-for-review" in provider.labels
    assert "pr:draft" not in provider.labels
    assert "connected-pr-label-convergence-proven" in ready.reason_codes


def test_connected_ready_transition_without_label_admission_is_not_terminal():
    provider = Provider()
    provider.snapshot = replace(provider.snapshot, draft=False)
    result = converge_connected_pull_request_lifecycle(
        provider,
        "Blummer92/agent-os",
        2145,
        invocation_reason="draft-ready-transition",
        lifecycle_admission=refused_lifecycle_labels(),
    )
    assert result.terminal_success is False
    assert "connected-pr-label-convergence-not-proven" in result.reason_codes


def closed_draft_expectation(**overrides):
    values = dict(repository="Blummer92/agent-os", pr_number=2145, head_sha=SHA)
    values.update(overrides)
    return PullRequestTerminalExpectation(**values)


def test_connected_final_state_readback_requires_terminal_expectation():
    with pytest.raises(ValueError, match="terminal expectation"):
        converge_connected_pull_request_lifecycle(
            Provider(), "Blummer92/agent-os", 2145,
            invocation_reason="final-state-readback",
            lifecycle_admission=admitted_lifecycle_labels(),
        )


def test_2705_interrupted_close_is_not_terminal_and_safe_reentry_converges():
    # #2789: #2705 stayed open and Ready although its closure was expected.
    provider = Provider()
    provider.snapshot = replace(provider.snapshot, draft=False)
    provider.labels = {"human:keep", "pr:ready-for-review"}

    interrupted = converge_connected_pull_request_lifecycle(
        provider, "Blummer92/agent-os", 2145,
        invocation_reason="final-state-readback",
        lifecycle_admission=admitted_lifecycle_labels(),
        terminal_expectation=closed_draft_expectation(),
    )
    assert interrupted.terminal_success is False
    assert "terminal-state-mismatch" in interrupted.reason_codes
    assert "connected-pr-label-convergence-not-proven" in interrupted.reason_codes
    assert provider.labels == {"human:keep", "pr:ready-for-review"}

    provider.snapshot = replace(provider.snapshot, state="closed", draft=True)
    reentry = converge_connected_pull_request_lifecycle(
        provider, "Blummer92/agent-os", 2145,
        invocation_reason="final-state-readback",
        lifecycle_admission=admitted_lifecycle_labels(),
        terminal_expectation=closed_draft_expectation(),
    )
    assert reentry.terminal_success is True
    assert "canonical-terminal-readback-verified" in reentry.reason_codes
    assert "pr:ready-for-review" not in provider.labels
    assert "human:keep" in provider.labels


def test_connected_terminal_readback_without_label_authority_is_not_terminal():
    provider = Provider()
    provider.snapshot = replace(provider.snapshot, state="closed", draft=True)
    provider.labels = {"human:keep", "pr:ready-for-review"}
    result = converge_connected_pull_request_lifecycle(
        provider, "Blummer92/agent-os", 2145,
        invocation_reason="final-state-readback",
        lifecycle_admission=refused_lifecycle_labels(),
        terminal_expectation=closed_draft_expectation(),
    )
    assert result.terminal_success is False
    assert "canonical-terminal-readback-verified" in result.reason_codes
