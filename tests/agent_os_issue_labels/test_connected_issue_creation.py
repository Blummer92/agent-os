from scripts.agent_os_issue_labels.connected_issue_creation import converge_connected_issue_creation, managed_labels_for_create
from scripts.agent_os_issue_labels.issue_reconciler import LiveIssueSnapshot
from tests.agent_os_issue_labels.lifecycle_admission import admitted_lifecycle_labels
from tests.agent_os_issue_labels.lifecycle_admission import refused_lifecycle_labels

FORM = ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ".github/labeler/agent-os-issue-label-map.yml"
BODY = """### Issue tier\n\ntier:1-standard-implementation\n\n### Primary owner\n\nowner:github-service-agent\n\n### Readiness candidate\n\nstatus:ready\n\n### Work type\n\ntype:bug\n\n### Source of truth\n\nGitHub\n\n### External write boundary\n\nno-external-write\n"""


class Provider:
    def __init__(self, labels=()):
        self.snapshot = LiveIssueSnapshot("Blummer92/agent-os", 2144, BODY, tuple(labels), "open")
        self.writes = []
    def read(self, repository, issue_number): return self.snapshot
    def available_labels(self, repository): return ("agent-os", "owner:github-service-agent", "status:ready", "type:bug")
    def add_label(self, repository, issue_number, label):
        self.writes.append(("add", label)); self.snapshot = LiveIssueSnapshot(repository, issue_number, BODY, self.snapshot.labels + (label,), "open")
    def remove_label(self, repository, issue_number, label):
        self.writes.append(("remove", label)); self.snapshot = LiveIssueSnapshot(repository, issue_number, BODY, tuple(x for x in self.snapshot.labels if x != label), "open")


def test_known_managed_labels_are_available_before_connected_create():
    assert set(managed_labels_for_create(BODY, issue_form_path=FORM, label_map_path=MAP)) == {"agent-os", "owner:github-service-agent", "status:ready", "type:bug"}


def test_connected_create_is_not_terminal_until_readback_converges():
    provider = Provider()
    result = converge_connected_issue_creation(provider, "Blummer92/agent-os", 2144, issue_form_path=FORM, label_map_path=MAP, lifecycle_admission=admitted_lifecycle_labels())
    assert result.terminal_success is True
    assert result.reconciliation.convergence_status == "converged"
    assert set(provider.snapshot.labels) == set(result.labels_for_create)


def test_missing_write_authority_cannot_claim_terminal_success():
    result = converge_connected_issue_creation(Provider(), "Blummer92/agent-os", 2144, issue_form_path=FORM, label_map_path=MAP, lifecycle_admission=refused_lifecycle_labels())
    assert result.terminal_success is False
    assert "connected-create-label-convergence-not-proven" in result.reason_codes
