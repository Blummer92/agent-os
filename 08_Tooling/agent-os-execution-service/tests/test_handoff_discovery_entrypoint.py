from __future__ import annotations

from types import SimpleNamespace

import pytest

import agent_os_execution_service.handoff_discovery_entrypoint as discovery


def test_rejects_unapproved_repository() -> None:
    with pytest.raises(ValueError):
        discovery.run_discovery(repository="other/repo", issue_number=1284)


def test_rejects_nonpositive_issue() -> None:
    with pytest.raises(ValueError):
        discovery.run_discovery(repository="Blummer92/agent-os", issue_number=0)


def test_store_root_is_host_side_not_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_OS_CHECKPOINT_STORE_ROOT", "/trusted/store")
    assert str(discovery._store_root()) == "/trusted/store"


def test_found_result_remains_non_authorizing(monkeypatch: pytest.MonkeyPatch) -> None:
    result = SimpleNamespace(
        status=SimpleNamespace(value="found"),
        reason_codes=(SimpleNamespace(value="found"),),
        repository="Blummer92/agent-os",
        issue_number=1284,
        matching_descriptor_count=1,
        handoff_id="executor-handoff:" + "a" * 64,
        result_id="invocation-handoff-discovery:test",
    )
    monkeypatch.setattr(discovery, "discover_issue_handoff", lambda *a, **k: result)

    payload = discovery.run_discovery(
        repository="Blummer92/agent-os",
        issue_number=1284,
    )
    assert payload["status"] == "found"
    assert payload["execution_authorized"] is False
    assert payload["scheduler_invoked"] is False
    assert payload["side_effects_performed"] is False
