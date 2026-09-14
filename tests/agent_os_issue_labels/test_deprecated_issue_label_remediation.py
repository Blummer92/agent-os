from scripts.agent_os_issue_labels.connected_issue_creation import managed_labels_for_create
from scripts.agent_os_issue_labels.issue_reconciler import LiveIssueSnapshot, reconcile_issue_labels

FORM = ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ".github/labeler/agent-os-issue-label-map.yml"
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
CANONICAL = {"agent-os", "owner:github-service-agent", "status:ready", "type:bug"}


class Provider:
    def __init__(self, labels=()):
        self.snapshot = LiveIssueSnapshot("Blummer92/agent-os", 2236, BODY, tuple(labels), "open")
        self.writes = []

    def read(self, repository, issue_number):
        return self.snapshot

    def available_labels(self, repository):
        # Deprecated labels may still exist in the repository label catalog. Their
        # availability must never make them part of the managed projection.
        return tuple(sorted(CANONICAL | {"tier:1-standard-implementation", "no-external-write"}))

    def add_label(self, repository, issue_number, label):
        self.writes.append(("add", label))
        self.snapshot = LiveIssueSnapshot(repository, issue_number, BODY, self.snapshot.labels + (label,), "open")

    def remove_label(self, repository, issue_number, label):
        self.writes.append(("remove", label))
        self.snapshot = LiveIssueSnapshot(repository, issue_number, BODY, tuple(x for x in self.snapshot.labels if x != label), "open")


def test_2236_shape_projects_only_current_managed_taxonomy():
    assert set(managed_labels_for_create(BODY, issue_form_path=FORM, label_map_path=MAP)) == CANONICAL


def test_tier_and_external_boundary_never_enter_managed_additions():
    result = reconcile_issue_labels(Provider(), "Blummer92/agent-os", 2236, issue_form_path=FORM, label_map_path=MAP)
    assert set(result.labels_to_add) == CANONICAL
    assert "tier:1-standard-implementation" not in result.labels_to_add
    assert "no-external-write" not in result.labels_to_add


def test_preexisting_legacy_labels_are_preserved_as_unmanaged_evidence():
    legacy = ("tier:1-standard-implementation", "no-external-write")
    result = reconcile_issue_labels(Provider(legacy), "Blummer92/agent-os", 2236, issue_form_path=FORM, label_map_path=MAP)
    assert set(result.unmanaged_labels_preserved) == set(legacy)
    assert not set(legacy).intersection(result.labels_to_remove)


def test_available_deprecated_labels_do_not_authorize_synthesis():
    provider = Provider()
    result = reconcile_issue_labels(provider, "Blummer92/agent-os", 2236, issue_form_path=FORM, label_map_path=MAP)
    assert set(result.desired_managed_labels) == CANONICAL
    assert set(result.labels_to_add) == CANONICAL
