from __future__ import annotations

import os
import stat
from types import SimpleNamespace

import scripts.agent_os_github_issue_provider.scanner_proof_host_bridge as bridge
from scripts.agent_os_github_issue_provider.scanner_proof import ScannerProofEvidence


def _stat(mode: int = stat.S_IFREG | 0o500, uid: int = 0):
    return SimpleNamespace(st_mode=mode, st_uid=uid)


def test_secret_provider_is_fixed_and_has_no_caller_selected_scope():
    assert bridge.SECRET_PROVIDER_ENTRYPOINT == "/usr/local/libexec/agent-os-github-app-secret-provider"
    assert bridge.VALIDATOR_PRINCIPAL == "agent-os-github-app-validator@agent-os-502614.iam.gserviceaccount.com"
    assert bridge.SECRET_RESOURCE == "projects/agent-os-502614/secrets/agent-os-github-app-private-key"
    assert bridge.EXPECTED_PERMISSIONS == {"issues": "read", "metadata": "read"}


def test_secret_provider_fails_closed_before_execution_when_entrypoint_unavailable():
    called = False

    def run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("must remain unreachable")

    provider = bridge.FixedHostGitHubAppSecretProvider(
        run_command=run,
        lstat=lambda path: (_ for _ in ()).throw(FileNotFoundError(path)),
    )
    try:
        provider.private_key()
    except bridge.ScannerProofHostBridgeError as error:
        assert error.reason_code == "scanner-proof-secret-provider-unavailable"
    else:
        raise AssertionError("expected fail closed")
    assert called is False


def test_secret_provider_rejects_unsafe_entrypoint_and_malformed_key():
    for metadata in (
        _stat(stat.S_IFREG | 0o522),
        _stat(stat.S_IFREG | 0o500, uid=1000),
        _stat(stat.S_IFDIR | 0o500),
    ):
        provider = bridge.FixedHostGitHubAppSecretProvider(
            run_command=lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="unused"),
            lstat=lambda path, metadata=metadata: metadata,
        )
        try:
            provider.private_key()
        except bridge.ScannerProofHostBridgeError as error:
            assert error.reason_code == "scanner-proof-secret-provider-unavailable"
        else:
            raise AssertionError("expected fail closed")

    provider = bridge.FixedHostGitHubAppSecretProvider(
        run_command=lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="not-a-private-key"),
        lstat=lambda path: _stat(),
    )
    try:
        provider.private_key()
    except bridge.ScannerProofHostBridgeError as error:
        assert error.reason_code == "scanner-proof-secret-provider-invalid"
    else:
        raise AssertionError("expected fail closed")


def test_secret_provider_command_has_no_secret_or_caller_data():
    calls = []
    key = "-----BEGIN PRIVATE KEY-----\n" + "A" * 256 + "\n-----END PRIVATE KEY-----\n"

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=key, stderr="")

    provider = bridge.FixedHostGitHubAppSecretProvider(
        run_command=run,
        lstat=lambda path: _stat(),
    )
    assert provider.private_key() == key
    argv, kwargs = calls[0]
    assert argv == (bridge.SECRET_PROVIDER_ENTRYPOINT,)
    assert kwargs["env"] == bridge._safe_provider_env()
    serialized = repr((argv, kwargs["env"]))
    for forbidden in (
        bridge.SECRET_RESOURCE,
        str(bridge.APP_ID),
        str(bridge.INSTALLATION_ID),
        bridge.REPOSITORY,
        "Authorization",
        "private_key",
    ):
        assert forbidden not in serialized


def _client(installation, repositories, repo_headers=None):
    class Requester:
        def requestJsonAndCheck(self, method, path, parameters, headers):
            if path == "/installation":
                return {}, installation
            if path == "/installation/repositories":
                return repo_headers or {}, repositories
            raise AssertionError(path)

    return SimpleNamespace(requester=Requester())


def _installation(**overrides):
    payload = {
        "id": bridge.INSTALLATION_ID,
        "app_id": bridge.APP_ID,
        "repository_selection": "selected",
        "permissions": dict(bridge.EXPECTED_PERMISSIONS),
    }
    payload.update(overrides)
    return payload


def _repositories(*names):
    return {
        "total_count": len(names),
        "repositories": [
            {"id": index + 1, "full_name": name}
            for index, name in enumerate(names)
        ],
    }


def test_installation_reader_accepts_only_exact_singleton_read_scope():
    reader = bridge.FixedInstallationSnapshotReader()
    snapshot, complete, terminal, installation_id = reader.read(
        _client(_installation(), _repositories(bridge.REPOSITORY))
    )
    assert snapshot["repository_selection"] == "selected"
    assert [item["full_name"] for item in snapshot["repositories"]] == [bridge.REPOSITORY]
    assert (complete, terminal, installation_id) == (True, True, bridge.INSTALLATION_ID)


def test_installation_reader_fails_closed_on_scope_or_permission_drift():
    cases = (
        (_installation(repository_selection="all"), _repositories(bridge.REPOSITORY), "scanner-proof-repository-scope-mismatch"),
        (_installation(permissions={"issues": "write", "metadata": "read"}), _repositories(bridge.REPOSITORY), "scanner-proof-permission-drift"),
        (_installation(), _repositories(bridge.REPOSITORY, "Blummer92/other"), "scanner-proof-repository-scope-mismatch"),
        (_installation(), _repositories("Blummer92/other"), "scanner-proof-repository-scope-mismatch"),
    )
    for installation, repositories, reason in cases:
        try:
            bridge.FixedInstallationSnapshotReader().read(_client(installation, repositories))
        except bridge.ScannerProofHostBridgeError as error:
            assert error.reason_code == reason
        else:
            raise AssertionError("expected fail closed")


def test_installation_reader_rejects_unproven_continuation():
    headers = {"Link": '<https://api.github.com/installation/repositories?page=2&per_page=2>; rel="next"'}
    try:
        bridge.FixedInstallationSnapshotReader().read(
            _client(_installation(), _repositories(bridge.REPOSITORY), headers)
        )
    except bridge.ScannerProofHostBridgeError as error:
        assert error.reason_code == "scanner-proof-installation-pagination-unproven"
    else:
        raise AssertionError("expected fail closed")


def test_host_bridge_reuses_existing_scanner_composition(monkeypatch):
    marker = ScannerProofEvidence(status="blocked", reason="scanner-proof-failed")
    calls = []

    def run_scanner_proof(*, secrets, installation_snapshot_reader):
        calls.append((secrets, installation_snapshot_reader))
        return marker

    monkeypatch.setattr(bridge, "run_scanner_proof", run_scanner_proof)
    secrets = object()
    reader = object()
    assert bridge.run_host_scanner_proof(
        secrets=secrets, installation_snapshot_reader=reader
    ) is marker
    assert calls == [(secrets, reader)]


def test_main_rejects_all_caller_arguments_without_running_scanner(monkeypatch, capsys):
    monkeypatch.setattr(
        bridge,
        "run_host_scanner_proof",
        lambda: (_ for _ in ()).throw(AssertionError("must remain unreachable")),
    )
    assert bridge.main(["--repo", "other/repo"]) == 0
    output = capsys.readouterr().out
    assert "scanner-proof-host-argv-invalid" in output
    for forbidden in ("Authorization", "PRIVATE KEY", "github.com/"):
        assert forbidden not in output


def test_bridge_creates_no_authority_or_retry_surface():
    result = ScannerProofEvidence(status="blocked", reason="scanner-proof-failed")
    assert result.external_side_effects_performed is False
    assert result.production_state_mutated is False
    assert result.execution_authorized is False
    assert result.publication_authorized is False
    assert result.complete_scan_authorized is False
    assert result.automatic_retry is False
    assert not hasattr(bridge, "merge")
    assert not hasattr(bridge, "publish")
    assert not hasattr(bridge, "schedule")
