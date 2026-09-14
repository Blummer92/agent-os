from __future__ import annotations

import pytest

from agent_os_execution_service.connected_issue_creation_facade import plan_connected_issue_creation_for_host


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


def test_host_projection_reuses_canonical_connected_creation_labels() -> None:
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
    )
    assert set(result["proposed_labels"]) == {
        "agent-os",
        "owner:github-service-agent",
        "status:ready",
        "type:bug",
    }
    assert result["next_operation"] == "create-then-canonical-readback-and-converge"
    assert result["reconciliation_owner"] == "#1962"


def test_host_projection_never_creates_authority() -> None:
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
    )
    assert result["implementation_authorized"] is False
    assert result["merge_authorized"] is False
    assert result["closure_authorized"] is False
    assert result["external_write_authorized"] is False
    assert result["side_effects_performed"] is False


def test_missing_canonical_metadata_fails_closed() -> None:
    with pytest.raises(ValueError, match="canonical tiered metadata"):
        plan_connected_issue_creation_for_host(
            repository="Blummer92/agent-os",
            issue_body="Source of truth: GitHub",
        )


def test_repository_identity_is_bounded() -> None:
    with pytest.raises(ValueError, match="owner/name"):
        plan_connected_issue_creation_for_host(repository="agent-os", issue_body=BODY)
