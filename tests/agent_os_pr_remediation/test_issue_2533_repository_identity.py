import pytest

from scripts.agent_os_pr_remediation.models import EvidenceValidationError
from scripts.agent_os_pr_remediation.normalization import normalize_pr_snapshot


def _payload(repository: str) -> dict[str, object]:
    return {
        "repository": repository,
        "pr_number": 2533,
        "base_branch": "main",
        "base_sha": "a" * 40,
        "head_branch": "agent/2533-repository-identity",
        "head_sha": "b" * 40,
        "state": "open",
        "merged": False,
        "draft": True,
        "changed_files": [],
        "captured_at": "2026-09-16T20:00:00Z",
        "source_revision": "test",
    }


def test_valid_repository_identity_is_preserved() -> None:
    assert normalize_pr_snapshot(_payload("Blummer92/agent-os")).repository == "Blummer92/agent-os"


@pytest.mark.parametrize("repository", ("/agent-os", "Blummer92/", "a/b/c"))
def test_incomplete_repository_identity_fails_closed(repository: str) -> None:
    with pytest.raises(EvidenceValidationError, match="repository must be owner/name"):
        normalize_pr_snapshot(_payload(repository))
