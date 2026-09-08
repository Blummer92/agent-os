"""Terminal lifecycle regression coverage for #2007."""
from pathlib import Path

from scripts.agent_os_issue_labels.issue_reconciler import LiveIssueSnapshot, reconcile_issue_labels

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"

BODY = """### Issue tier

tier:1-standard-implementation

### Primary owner

owner:github-service-agent

### Readiness candidate

status:ready

### Work type

type:bug

### Source of truth

GitHub

### External write boundary

no-external-write
"""


class Provider:
    def __init__(self, label):
        self.snapshot = LiveIssueSnapshot(
            "Blummer92/agent-os", 1, BODY,
            ("agent-os", "owner:github-service-agent", label, "type:bug", "human-note"),
            "closed",
        )
        self.writes = []

    def read(self, repository, issue_number):
        return self.snapshot

    def available_labels(self, repository):
        return ("agent-os", "owner:github-service-agent", "status:ready", "status:blocked", "status:needs-decision", "type:bug")

    def add_label(self, repository, issue_number, label):
        self.writes.append(("add", label))

    def remove_label(self, repository, issue_number, label):
        self.snapshot = LiveIssueSnapshot(
            self.snapshot.repository, self.snapshot.issue_number, self.snapshot.body,
            tuple(item for item in self.snapshot.labels if item != label), self.snapshot.state,
        )
        self.writes.append(("remove", label))


def reconcile(provider):
    return reconcile_issue_labels(
        provider, "Blummer92/agent-os", 1,
        issue_form_path=FORM, label_map_path=MAP,
        dry_run=False, label_write_authorized=True,
    )


def test_closed_completed_projection_removes_active_status_labels_and_preserves_human_labels() -> None:
    for stale in ("status:ready", "status:blocked", "status:needs-decision"):
        provider = Provider(stale)
        result = reconcile(provider)
        assert result.convergence_status == "converged"
        assert ("remove", stale) in provider.writes
        assert "human-note" in provider.snapshot.labels
        assert not any(label.startswith("status:") for label in provider.snapshot.labels)


def test_terminal_reconciliation_is_idempotent_after_active_status_removal() -> None:
    provider = Provider("status:blocked")
    first = reconcile(provider)
    assert first.convergence_status == "converged"
    provider.writes.clear()
    second = reconcile(provider)
    assert second.convergence_status == "already-current"
    assert provider.writes == []
