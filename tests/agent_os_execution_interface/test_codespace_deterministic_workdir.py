"""#3333 Option B: deterministic Codespaces working-directory contract.

Focused regressions for the owner-approved deterministic contract that replaces
measurement of the incidental non-interactive SSH working directory:

- the validated repository root constant is pinned to the approved value;
- the transport pins the remote command under the validated root;
- any other workdir is rejected before any Codespace is contacted;
- ``workdir=None`` preserves the historical command shape;
- the fixed argv is unchanged and the command grammar is not widened;
- the on-host driver binds the production bootstrap and fails closed.

Only injected callbacks run. No SSH, credentials or network is used.
"""

from __future__ import annotations

import pytest

from scripts.agent_os_execution_interface import fixed_codespace_pilot as pilot_module
from scripts.agent_os_execution_interface.codespaces_orchestrator_transport import (
    VALIDATED_CODESPACE_REPOSITORY_ROOT,
    CodespaceCandidate,
    TransportReason,
    TransportRequest,
    TransportStatus,
    run_codespace_transport,
    validate_argv,
)
from scripts.agent_os_execution_interface.fixed_codespace_pilot import (
    FIXED_ARGV,
    drive_fixed_codespace_pilot_on_host,
)

REPOSITORY = "Blummer92/agent-os"
VALIDATED_ROOT = "/workspaces/agent-os"
HEAD_SHA = "f9b7001a79a42c422042bbc355bb4d86a7b9c39f"


def _candidate(name="happy-codespace"):
    return CodespaceCandidate(
        name=name,
        state="Available",
        repository_full_name=REPOSITORY,
        owner_login="Blummer92",
    )


def _request(**overrides):
    args = dict(
        repository=REPOSITORY,
        issue_identity="3333",
        admission_id="admission-1",
        argv=("git", "rev-parse", "HEAD"),
    )
    args.update(overrides)
    return TransportRequest(**args)


def _ok_run(seen):
    def _run(argv, timeout_seconds):
        seen.append(argv)
        return 0, HEAD_SHA + "\n", ""

    return _run


def test_validated_root_is_the_approved_constant():
    assert VALIDATED_CODESPACE_REPOSITORY_ROOT == "/workspaces/agent-os"


def test_transport_pins_remote_command_under_validated_root():
    seen = []
    result = run_codespace_transport(
        _request(workdir_or_none=VALIDATED_ROOT),
        list_candidates=lambda: (_candidate(),),
        run=_ok_run(seen),
    )
    assert result.status is TransportStatus.COMPLETED
    assert seen[0] == (
        "gh",
        "codespace",
        "ssh",
        "-c",
        "happy-codespace",
        "--",
        "cd",
        "/workspaces/agent-os",
        "&&",
        "git",
        "rev-parse",
        "HEAD",
    )
    # Recorded evidence keeps the fixed argv; the cd prefix is transport mechanics.
    assert result.argv == FIXED_ARGV
    assert tuple(result.argv) == ("git", "rev-parse", "HEAD")
    assert result.workdir_or_none == VALIDATED_ROOT


def test_workdir_none_preserves_historical_command_shape():
    seen = []
    result = run_codespace_transport(
        _request(),
        list_candidates=lambda: (_candidate(),),
        run=_ok_run(seen),
    )
    assert result.status is TransportStatus.COMPLETED
    assert seen[0] == (
        "gh",
        "codespace",
        "ssh",
        "-c",
        "happy-codespace",
        "--",
        "git",
        "rev-parse",
        "HEAD",
    )


@pytest.mark.parametrize(
    "bad",
    [
        "/workspaces/agent-os/",  # trailing slash
        "/workspaces/agent-os/.",  # dot segment
        "/workspaces/agent-os/../agent-os",  # dot-dot traversal
        "/workspaces/AGENT-OS",  # case difference
        "/workspaces/agent-os2",  # prefix extension
        "/other/dir",  # different absolute path
        "workspaces/agent-os",  # relative path
        "/workspaces/agent-os ",  # trailing whitespace
        "/workspaces/agent-os\n",  # control character
    ],
)
def test_malformed_workdirs_rejected_before_any_contact(bad):
    calls = []

    def _listed():
        calls.append("listed")
        return (_candidate(),)

    def _run(argv, timeout_seconds):
        calls.append("run")
        raise AssertionError("transport must not run")

    result = run_codespace_transport(
        _request(workdir_or_none=bad),
        list_candidates=_listed,
        run=_run,
    )
    assert result.status is TransportStatus.REJECTED
    assert result.reason_codes == (TransportReason.INVALID_REQUEST,)
    assert calls == []
    # Refusal happens before execution: no attempt timestamps.
    assert result.started_at_or_none is None
    assert result.ended_at_or_none is None


def test_empty_workdir_rejected_at_construction():
    with pytest.raises(ValueError):
        _request(workdir_or_none="")


def test_fixed_argv_still_admitted_and_unchanged():
    assert validate_argv(FIXED_ARGV) is None
    assert FIXED_ARGV == ("git", "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "argv",
    [
        ("git", "rev-parse", "HEAD", "&&", "id"),
        ("git", "rev-parse", "HEAD;id"),
        ("sh", "-c", "cd /workspaces/agent-os && git rev-parse HEAD"),
        ("git", "push", "origin", "main"),
    ],
)
def test_command_grammar_not_widened_by_workdir_contract(argv):
    calls = []
    result = run_codespace_transport(
        _request(argv=argv, workdir_or_none=VALIDATED_ROOT),
        list_candidates=lambda: (_candidate(),),
        run=lambda *a, **k: calls.append("run") or (0, "", ""),
    )
    assert result.status is TransportStatus.REJECTED
    assert result.reason_codes[0] in (
        TransportReason.INVALID_REQUEST,
        TransportReason.FORBIDDEN_COMMAND,
    )
    assert calls == []


def test_driver_rejects_missing_bootstrap():
    receipt = drive_fixed_codespace_pilot_on_host({"schema_version": "1.0"})
    assert receipt["status"] == "needs-decision"
    assert receipt["reason_codes"] == ["canonical-admission-provider-unavailable"]
    assert receipt["operation_id"] == "codespace-implementation-pilot-v1"


def test_driver_rejects_wrong_type_bootstrap():
    receipt = drive_fixed_codespace_pilot_on_host(
        {"schema_version": "1.0"}, bootstrap=object()
    )
    assert receipt["status"] == "needs-decision"
    assert receipt["reason_codes"] == ["canonical-admission-provider-unavailable"]


def test_driver_rejects_non_dict_transport():
    receipt = drive_fixed_codespace_pilot_on_host(None, bootstrap=object())
    assert receipt["status"] == "needs-decision"
    assert receipt["reason_codes"] == ["canonical-admission-provider-unavailable"]


def test_driver_delegates_to_on_host(monkeypatch):
    from agent_os_execution_service.production_host_bootstrap import (
        ProductionHostBootstrap,
    )

    bootstrap = ProductionHostBootstrap(
        configuration=None,
        evaluated_at=None,
        sources=None,
        authorization_transport=None,
    )
    sentinel_providers = object()
    monkeypatch.setattr(
        ProductionHostBootstrap, "admission_providers", lambda self: sentinel_providers
    )
    seen = {}

    def fake_on_host(transport, **kwargs):
        seen["transport"] = transport
        seen["providers"] = kwargs.get("providers")
        return {"delegated": True}

    monkeypatch.setattr(
        pilot_module, "consume_fixed_codespace_pilot_on_host", fake_on_host
    )
    result = drive_fixed_codespace_pilot_on_host({"t": 1}, bootstrap=bootstrap)
    assert seen["transport"] == {"t": 1}
    assert seen["providers"] is sentinel_providers
    assert result == {"delegated": True}


def test_driver_converts_bootstrap_error_to_receipt(monkeypatch):
    from agent_os_execution_service.production_host_bootstrap import (
        ProductionHostBootstrap,
        ProductionHostBootstrapError,
    )

    bootstrap = ProductionHostBootstrap(
        configuration=None,
        evaluated_at=None,
        sources=None,
        authorization_transport=None,
    )

    def _raise(self):
        raise ProductionHostBootstrapError("store root not bound")

    monkeypatch.setattr(ProductionHostBootstrap, "admission_providers", _raise)
    receipt = drive_fixed_codespace_pilot_on_host(
        {"schema_version": "1.0"}, bootstrap=bootstrap
    )
    assert receipt["status"] == "needs-decision"
    assert receipt["reason_codes"] == ["canonical-admission-provider-unavailable"]
