from pathlib import Path

from scripts.agent_os_issue_labels.issue_reconciler import LiveIssueSnapshot, reconcile_issue_batch, reconcile_issue_labels

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
    def __init__(self, snapshots, available=None, fail_write=False):
        self.snapshots = dict(snapshots)
        self.available = tuple(available or ("agent-os", "owner:github-service-agent", "status:ready", "type:bug"))
        self.fail_write = fail_write
        self.writes = []

    def read(self, repository, issue_number):
        return self.snapshots[issue_number]

    def available_labels(self, repository):
        return self.available

    def add_label(self, repository, issue_number, label):
        if self.fail_write:
            raise RuntimeError("boom")
        snap = self.snapshots[issue_number]
        self.snapshots[issue_number] = LiveIssueSnapshot(snap.repository, snap.issue_number, snap.body, tuple((*snap.labels, label)), snap.state)
        self.writes.append(("add", issue_number, label))

    def remove_label(self, repository, issue_number, label):
        if self.fail_write:
            raise RuntimeError("boom")
        snap = self.snapshots[issue_number]
        self.snapshots[issue_number] = LiveIssueSnapshot(snap.repository, snap.issue_number, snap.body, tuple(x for x in snap.labels if x != label), snap.state)
        self.writes.append(("remove", issue_number, label))


def snap(number=1, labels=(), body=BODY):
    return LiveIssueSnapshot("Blummer92/agent-os", number, body, tuple(labels))


def reconcile(provider, number=1, **kwargs):
    return reconcile_issue_labels(provider, "Blummer92/agent-os", number, issue_form_path=FORM, label_map_path=MAP, **kwargs)


def test_zero_label_issue_dry_run_bootstraps_without_writes():
    provider = Provider({1: snap()})
    result = reconcile(provider)
    assert result.convergence_status == "would-change"
    assert set(result.labels_to_add) == {"agent-os", "owner:github-service-agent", "status:ready", "type:bug"}
    assert provider.writes == []


def test_stale_managed_label_removed_but_human_label_preserved():
    provider = Provider({1: snap(labels=("agent-os", "owner:github-service-agent", "status:blocked", "human-note"))})
    result = reconcile(provider, dry_run=False, label_write_authorized=True)
    assert result.convergence_status == "converged"
    assert ("remove", 1, "status:blocked") in provider.writes
    assert "human-note" in provider.snapshots[1].labels


def test_ambiguous_or_incomplete_metadata_routes_to_manual_review():
    provider = Provider({1: snap(body="### Primary owner\n\nowner:github-service-agent\n")})
    assert reconcile(provider).convergence_status == "manual-review"


def test_missing_repository_label_blocks():
    provider = Provider({1: snap()}, available=("agent-os",))
    assert reconcile(provider).convergence_status == "blocked"


def test_write_requires_explicit_authorization():
    provider = Provider({1: snap()})
    result = reconcile(provider, dry_run=False)
    assert result.convergence_status == "blocked"
    assert provider.writes == []


def test_provider_failure_is_explicit():
    provider = Provider({1: snap()}, fail_write=True)
    result = reconcile(provider, dry_run=False, label_write_authorized=True)
    assert result.convergence_status == "blocked"
    assert result.reason_codes == ("provider-write-failure:RuntimeError",)


def test_unchanged_issue_is_idempotent():
    labels = ("agent-os", "owner:github-service-agent", "status:ready", "type:bug")
    provider = Provider({1: snap(labels=labels)})
    result = reconcile(provider, dry_run=False, label_write_authorized=True)
    assert result.convergence_status == "already-current"
    assert provider.writes == []


def test_batch_continues_past_item_local_failure():
    provider = Provider({1: snap(1, body="bad"), 2: snap(2)})
    results = reconcile_issue_batch(provider, "Blummer92/agent-os", (1, 2), issue_form_path=FORM, label_map_path=MAP)
    assert results[0].convergence_status == "manual-review"
    assert results[1].convergence_status == "would-change"
