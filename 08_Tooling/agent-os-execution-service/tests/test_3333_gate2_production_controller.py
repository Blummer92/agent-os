"""Focused tests for the Gate 2 (#3333) production-host controller.

All tests are offline: the pilot driver, the codespace selection resolver,
and the transport builder are injected fakes. No live codespace execution,
no network, and no credential use happens in this file. The happy path
composes the REAL ``build_production_host_bootstrap`` with fake transports
so the production composition seam itself is exercised.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_os_execution_service.gate2_production_controller import (
    Gate2ControllerError,
    _persist_receipt_atomically,
    main,
    run_gate2_fixed_pilot_controller,
)
from agent_os_execution_service.host_github_read_transport import (
    HostGitHubTransportUnavailable,
)
from agent_os_execution_service.production_host_bootstrap import (
    ProductionHostBootstrap,
)
from workflow_scheduler.governance.dev_validation_codespaces import (
    CodespaceSelection,
)

HANDOFF = "a" * 64
SHA = "b" * 40
OTHER_SHA = "c" * 40
BODY = f"/agent-os codespace-implementation executor-handoff:{HANDOFF} {SHA}"


def _event(
    body: str = BODY,
    *,
    actor: str = "Blummer92",
    repo: str = "Blummer92/agent-os",
    issue: int = 3333,
    action: str = "created",
) -> dict:
    return {
        "action": action,
        "repository": {"full_name": repo},
        "issue": {"number": issue},
        "comment": {"id": 101, "body": body, "user": {"login": actor}},
        "sender": {"login": actor},
    }


@pytest.fixture()
def host(tmp_path: Path) -> dict:
    store = tmp_path / "store"
    repo_root = tmp_path / "repo"
    workspace_parent = tmp_path / "ws"
    lease_dir = tmp_path / "leases"
    (store / "invocations").mkdir(parents=True)
    (repo_root / "scripts").mkdir(parents=True)
    (repo_root / "scripts" / "verify-repo-state.sh").write_text("#!/bin/sh\n")
    (repo_root / ".git").mkdir()
    workspace_parent.mkdir()
    lease_dir.mkdir()
    return {
        "AGENT_OS_CHECKPOINT_STORE_ROOT": str(store),
        "AGENT_OS_REPOSITORY_ROOT": str(repo_root),
        "AGENT_OS_WORKSPACE_PARENT": str(workspace_parent),
        "AGENT_OS_LEASE_DIRECTORY": str(lease_dir),
        "CODESPACE_NAME": "test-box",
        "store": store,
        "lease_dir": lease_dir,
    }


def _write_event(tmp_path: Path, event: dict) -> Path:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event))
    return path


def _selection(name: str = "test-box") -> CodespaceSelection:
    return CodespaceSelection(
        selected=True, reason="test", codespace_name=name, state="Available"
    )


class _FakeIssueTransport:
    def get_issue(self, repository: str, issue_number: int):  # pragma: no cover
        raise AssertionError("no network in tests")


class _FakeAuthTransport:
    def read_authorization_source(
        self, repository: str, issue_number: int
    ):  # pragma: no cover
        raise AssertionError("no network in tests")


class _FakeEvidenceReader:
    def read_dependency_evidence(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("no evidence reads in tests")

    def read_validation_evidence(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("no evidence reads in tests")


def _transports():
    return (
        _FakeIssueTransport(),
        _FakeAuthTransport(),
        _FakeEvidenceReader(),
        lambda invocation: "fake-verifier-stdout",
    )


def _completed_receipt() -> dict:
    return {
        "schema_version": "1.0",
        "operation_id": "codespace-implementation-pilot-v1",
        "status": "completed",
        "reason_codes": ["fixed-head-probe-passed"],
        "repository": "Blummer92/agent-os",
        "issue_number": 3333,
        "handoff_id": f"executor-handoff:{HANDOFF}",
        "expected_sha": SHA,
    }


def test_missing_event_document_fails_closed(tmp_path: Path, host: dict) -> None:
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=tmp_path / "nope.json",
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "event-document-unreadable"


def test_malformed_event_document_fails_closed(tmp_path: Path, host: dict) -> None:
    path = tmp_path / "event.json"
    path.write_text("{not json")
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "event-document-malformed"


def test_wrong_actor_envelope_never_drives(tmp_path: Path, host: dict) -> None:
    calls: list = []
    path = _write_event(tmp_path, _event(actor="mallory"))
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=lambda envelope, bootstrap: calls.append(envelope),
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "envelope-not-accepted"
    assert calls == []


def test_wrong_repository_envelope_rejected(tmp_path: Path, host: dict) -> None:
    path = _write_event(tmp_path, _event(repo="someone-else/agent-os"))
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "envelope-not-accepted"


def test_wrong_issue_envelope_rejected(tmp_path: Path, host: dict) -> None:
    path = _write_event(tmp_path, _event(issue=9999))
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "envelope-not-accepted"


def test_unrecognized_trigger_body_rejected(tmp_path: Path, host: dict) -> None:
    path = _write_event(tmp_path, _event(body="/agent-os do something else"))
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "envelope-not-accepted"


def test_missing_host_paths_fail_closed(tmp_path: Path) -> None:
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ={},
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "host-configuration-invalid"
    assert "AGENT_OS_CHECKPOINT_STORE_ROOT" in str(excinfo.value)


def test_missing_invocations_dir_fails_closed(tmp_path: Path, host: dict) -> None:
    (host["store"] / "invocations").rmdir()
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "checkpoint-store-not-initialized"


def test_missing_verifier_script_fails_closed(tmp_path: Path, host: dict) -> None:
    (
        Path(host["AGENT_OS_REPOSITORY_ROOT"]) / "scripts" / "verify-repo-state.sh"
    ).unlink()
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "repository-identity-unverified"


def test_unqualified_surface_fails_closed(tmp_path: Path, host: dict) -> None:
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: CodespaceSelection(selected=False, reason="nope"),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "execution-surface-unqualified"


def test_host_surface_identity_mismatch_fails_closed(
    tmp_path: Path, host: dict
) -> None:
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(name="other-box"),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "host-surface-identity-mismatch"


def test_missing_host_surface_identity_fails_closed(tmp_path: Path, host: dict) -> None:
    del host["CODESPACE_NAME"]
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "host-surface-identity-unavailable"


def test_conflicting_active_lease_fails_closed(tmp_path: Path, host: dict) -> None:
    (host["lease_dir"] / ("d" * 64 + ".active.json")).write_text("{}")
    calls: list = []
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=lambda envelope, bootstrap: calls.append(envelope),
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "conflicting-active-lease"
    assert calls == []


def test_symlink_in_lease_directory_fails_closed(tmp_path: Path, host: dict) -> None:
    target = tmp_path / "target"
    target.write_text("x")
    (host["lease_dir"] / "sneaky").symlink_to(target)
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "lease-directory-symlink-present"


def test_missing_credential_fails_closed(tmp_path: Path, host: dict) -> None:
    def _no_credential() -> tuple:
        raise HostGitHubTransportUnavailable("no token")

    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            resolve_selection=lambda: _selection(),
            build_transports=_no_credential,
        )
    assert excinfo.value.reason == "github-read-credential-unavailable"


def test_happy_path_persists_receipt_atomically(tmp_path: Path, host: dict) -> None:
    seen: dict = {}

    def _drive(envelope: dict, *, bootstrap: object) -> dict:
        assert type(bootstrap) is ProductionHostBootstrap
        seen["envelope"] = envelope
        return _completed_receipt()

    path = _write_event(tmp_path, _event())
    result = run_gate2_fixed_pilot_controller(
        event_path=path,
        environ=host,
        drive=_drive,
        resolve_selection=lambda: _selection(),
        build_transports=_transports,
    )
    assert result.status == "completed"
    assert result.reason_codes == ("fixed-head-probe-passed",)
    receipt_path = Path(result.receipt_path)
    receipts_dir = host["store"] / "invocations" / "receipts"
    assert receipt_path.parent == receipts_dir
    assert receipt_path.suffix == ".json"
    assert receipt_path.name.startswith("fixed-head-probe-")
    assert HANDOFF in receipt_path.name and SHA in receipt_path.name
    # The top-level invocations/*.json descriptor invariant is untouched: the
    # existing handoff discovery scans every top-level *.json as a descriptor.
    assert list((host["store"] / "invocations").glob("*.json")) == []
    # Atomicity: no temp file left behind, content is exactly the receipt.
    assert list(receipts_dir.glob("*.tmp")) == []
    assert json.loads(receipt_path.read_text()) == _completed_receipt()
    # Bounded reference for the existing authorized consumer.
    reference = result.receipt_reference
    assert reference["receipt_path"] == str(receipt_path)
    assert reference["handoff_id"] == f"executor-handoff:{HANDOFF}"
    assert reference["expected_sha"] == SHA
    assert reference["status"] == "completed"
    assert "stdout_tail" not in reference
    assert seen["envelope"]["codespace_implementation_sha_or_none"] == SHA


def test_blocked_receipt_is_persisted_as_blocked(tmp_path: Path, host: dict) -> None:
    blocked = dict(_completed_receipt())
    blocked.update(status="blocked", reason_codes=["canonical-invocation-not-admitted"])
    path = _write_event(tmp_path, _event())
    result = run_gate2_fixed_pilot_controller(
        event_path=path,
        environ=host,
        drive=lambda envelope, bootstrap: blocked,
        resolve_selection=lambda: _selection(),
        build_transports=_transports,
    )
    assert result.status == "blocked"
    assert result.reason_codes == ("canonical-invocation-not-admitted",)
    assert json.loads(Path(result.receipt_path).read_text())["status"] == "blocked"


def test_receipt_write_failure_fails_closed(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x")
    with pytest.raises(Gate2ControllerError) as excinfo:
        _persist_receipt_atomically(not_a_dir, "r.json", {"a": 1})
    assert excinfo.value.reason == "receipt-write-failed"


def test_receipt_name_collision_fails_closed(tmp_path: Path, host: dict) -> None:
    invocations = host["store"] / "invocations"
    (invocations / "fixed-head-probe-x.json").write_text("{}")
    with pytest.raises(Gate2ControllerError) as excinfo:
        _persist_receipt_atomically(invocations, "fixed-head-probe-x.json", {"a": 1})
    assert excinfo.value.reason == "receipt-already-exists"


def test_receipts_dir_created_private_on_demand(tmp_path: Path, host: dict) -> None:
    import stat

    path = _write_event(tmp_path, _event())
    result = run_gate2_fixed_pilot_controller(
        event_path=path,
        environ=host,
        drive=lambda envelope, bootstrap: _completed_receipt(),
        resolve_selection=lambda: _selection(),
        build_transports=_transports,
    )
    receipts_dir = host["store"] / "invocations" / "receipts"
    assert receipts_dir.is_dir()
    assert stat.S_IMODE(receipts_dir.stat().st_mode) == 0o700
    assert Path(result.receipt_path).parent == receipts_dir


def test_receipts_dir_symlink_fails_closed(tmp_path: Path, host: dict) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (host["store"] / "invocations" / "receipts").symlink_to(target)
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=lambda envelope, bootstrap: _completed_receipt(),
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipts-dir-is-symlink"


def test_handoff_discovery_unaffected_by_receipts(tmp_path: Path, host: dict) -> None:
    from scripts.agent_os_execution_checkpoint.handoff_discovery import (
        InvocationHandoffDiscoveryStatus,
        discover_issue_handoff,
    )

    path = _write_event(tmp_path, _event())
    run_gate2_fixed_pilot_controller(
        event_path=path,
        environ=host,
        drive=lambda envelope, bootstrap: _completed_receipt(),
        resolve_selection=lambda: _selection(),
        build_transports=_transports,
    )
    outcome = discover_issue_handoff(
        host["store"], repository="Blummer92/agent-os", issue_number=3333
    )
    # NOT_FOUND (empty descriptor store), never NEEDS_DECISION: the receipt
    # must not poison the existing descriptor discovery.
    assert outcome.status is InvocationHandoffDiscoveryStatus.NOT_FOUND


def test_receipts_dir_failure_precedes_drive(tmp_path: Path, host: dict) -> None:
    # The receipts home must exist before the pilot drives: a post-drive
    # failure would lose the receipt of an already-consumed probe.
    target = tmp_path / "target"
    target.mkdir()
    (host["store"] / "invocations" / "receipts").symlink_to(target)
    calls: list = []
    path = _write_event(tmp_path, _event())
    with pytest.raises(Gate2ControllerError) as excinfo:
        run_gate2_fixed_pilot_controller(
            event_path=path,
            environ=host,
            drive=lambda envelope, bootstrap: calls.append(envelope),
            resolve_selection=lambda: _selection(),
            build_transports=_transports,
        )
    assert excinfo.value.reason == "receipts-dir-is-symlink"
    assert calls == []


def test_main_cli_failure_contract(tmp_path: Path, capsys) -> None:
    code = main(["--event", str(tmp_path / "missing.json")])
    assert code == 1
    err = json.loads(capsys.readouterr().err)
    assert err["status"] == "failed"
    assert err["reason_codes"] == ["event-document-unreadable"]


def test_main_cli_success_contract(
    tmp_path: Path, host: dict, capsys, monkeypatch
) -> None:
    for key, value in host.items():
        if isinstance(value, str):
            monkeypatch.setenv(key, value)
    path = _write_event(tmp_path, _event())

    import agent_os_execution_service.gate2_production_controller as controller

    monkeypatch.setattr(
        controller,
        "read_canonical_codespace_selection",
        lambda resolve_selection=None: _selection(),
    )
    monkeypatch.setattr(controller, "_default_transports", _transports)
    monkeypatch.setattr(
        controller,
        "drive_fixed_codespace_pilot_on_host",
        lambda envelope, bootstrap: _completed_receipt(),
    )
    code = main(["--event", str(path)])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["status"] == "completed"
    assert out["consumer"] == "github-service-agent-governed-publication-path"
    assert Path(out["receipt_path"]).is_file()
