from __future__ import annotations

import dataclasses
import json
import os
import subprocess

import pytest

from workflow_scheduler.governance.codespaces_lifecycle import (
    LifecycleAuthorization,
    _api,
    _ssh_ready,
    run_authorized_lifecycle,
)
from workflow_scheduler.governance.dev_validation import REPOSITORY
from workflow_scheduler.governance.dev_validation_codespaces import CodespaceSelection

NAME = "qualified-agent-os-codespace"


def _auth(**overrides):
    values = dict(
        repository=REPOSITORY,
        codespace_name=NAME,
        authorization_reference="issue-3345:test",
        operation_id="registered-test-operation",
    )
    values.update(overrides)
    return LifecycleAuthorization(**values)


class FakeRun:
    def __init__(self, states, *, ssh=0, start=0, stop=0):
        self.states = iter(states)
        self.ssh = ssh
        self.start = start
        self.stop = stop
        self.calls = []

    def __call__(self, argv, *, timeout, env):
        self.calls.append((tuple(argv), dict(env)))
        if argv[:3] == ("gh", "api", "--method"):
            method, endpoint = argv[3], argv[-1]
            if method == "POST":
                code = self.start if endpoint.endswith("/start") else self.stop
                return subprocess.CompletedProcess(argv, code, stdout="", stderr="")
            state = next(self.states)
            payload = {
                "name": NAME,
                "state": state,
                "owner": {"login": "Blummer92"},
                "repository": {"full_name": REPOSITORY},
            }
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")
        if argv[:3] == ("gh", "codespace", "ssh"):
            return subprocess.CompletedProcess(argv, self.ssh, stdout="", stderr="")
        raise AssertionError(argv)


def test_shutdown_start_ready_operation_stop_shutdown() -> None:
    run = FakeRun(["Shutdown", "Available", "Shutdown"])
    seen = []
    evidence = run_authorized_lifecycle(
        _auth(),
        lifecycle_token="lifecycle-test-value",
        transport_token="transport-test-value",
        run=run,
        operation=lambda name: seen.append(name) is None,
        consume_authorization=lambda _: True,
        resolve_codespace=lambda: __import__("workflow_scheduler.governance.dev_validation_codespaces", fromlist=["CodespaceSelection"]).CodespaceSelection(False, "codespaces-not-available", NAME, "Shutdown"),
        sleep=lambda _: None,
    )
    assert evidence.status == "success"
    assert evidence.reason == "operation-complete"
    assert evidence.ssh_ready is True
    assert evidence.cleanup_complete is True
    assert evidence.final_state == "Shutdown"
    assert seen == [NAME]
    endpoints = [call[0][-1] for call in run.calls if call[0][:2] == ("gh", "api")]
    assert f"/user/codespaces/{NAME}/start" in endpoints
    assert f"/user/codespaces/{NAME}/stop" in endpoints
    api_envs = [
        env for argv, env in run.calls if argv[:3] == ("gh", "api", "--method")
    ]
    ssh_envs = [
        env for argv, env in run.calls if argv[:3] == ("gh", "codespace", "ssh")
    ]
    assert api_envs and all(env["GH_TOKEN"] == "lifecycle-test-value" for env in api_envs)
    assert [env["GH_TOKEN"] for env in ssh_envs] == ["transport-test-value"]


def test_child_env_inherits_parent_and_replaces_only_github_credentials(
    monkeypatch,
) -> None:
    parent = {
        "PATH": "/opt/test-bin:/usr/bin",
        "HOME": "/home/test-user",
        "HTTPS_PROXY": "http://proxy.test:3128",
        "https_proxy": "http://proxy.test:3128",
        "SSL_CERT_FILE": "/etc/test/ca-bundle.crt",
        "GH_CONFIG_DIR": "/home/test-user/.config/gh",
    }
    for key, value in parent.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GH_TOKEN", "stale-ambient-test-value")
    monkeypatch.setenv("GITHUB_TOKEN", "stale-github-test-value")
    run = FakeRun(["Shutdown", "Available", "Shutdown"])
    evidence = run_authorized_lifecycle(
        _auth(),
        lifecycle_token="lifecycle-test-value",
        transport_token="transport-test-value",
        run=run,
        operation=lambda _: True,
        consume_authorization=lambda _: True,
        resolve_codespace=lambda: CodespaceSelection(False, "codespaces-not-available", NAME, "Shutdown"),
        sleep=lambda _: None,
    )
    assert evidence.status == "success"
    api_envs = [env for argv, env in run.calls if argv[:3] == ("gh", "api", "--method")]
    ssh_envs = [env for argv, env in run.calls if argv[:3] == ("gh", "codespace", "ssh")]
    assert api_envs and ssh_envs
    for env, selected, other in [
        *((env, "lifecycle-test-value", "transport-test-value") for env in api_envs),
        *((env, "transport-test-value", "lifecycle-test-value") for env in ssh_envs),
    ]:
        assert {key: env.get(key) for key in parent} == parent
        assert env["GH_TOKEN"] == selected
        assert "GITHUB_TOKEN" not in env
        assert "stale-ambient-test-value" not in env.values()
        assert other not in env.values()


def test_secret_material_never_emitted() -> None:
    run = FakeRun(["Shutdown", "Available", "Shutdown"])
    evidence = run_authorized_lifecycle(
        _auth(),
        lifecycle_token="lifecycle-test-value",
        transport_token="transport-test-value",
        run=run,
        operation=lambda _: True,
        consume_authorization=lambda _: True,
        resolve_codespace=lambda: CodespaceSelection(False, "codespaces-not-available", NAME, "Shutdown"),
        sleep=lambda _: None,
    )
    emitted = json.dumps(dataclasses.asdict(evidence)) + json.dumps([argv for argv, _ in run.calls])
    assert "lifecycle-test-value" not in emitted
    assert "transport-test-value" not in emitted


_FAKE_GH = """#!/bin/sh
printf '%s|%s|%s\\n' "$HTTPS_PROXY" "${GITHUB_TOKEN-unset}" "$GH_TOKEN" > "$AGENT_OS_TEST_PROBE_OUT"
printf '{}'
"""


@pytest.mark.skipif(os.name != "posix", reason="POSIX shell fake gh executable")
@pytest.mark.parametrize("probe", ["api", "ssh"])
def test_real_subprocess_finds_gh_via_inherited_path_and_proxy(
    probe, tmp_path, monkeypatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(_FAKE_GH, encoding="utf-8")
    fake_gh.chmod(0o755)
    probe_out = tmp_path / "probe.txt"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:3128")
    monkeypatch.setenv("AGENT_OS_TEST_PROBE_OUT", str(probe_out))
    monkeypatch.setenv("GH_TOKEN", "stale-ambient-test-value")
    monkeypatch.setenv("GITHUB_TOKEN", "stale-github-test-value")

    def run(argv, *, timeout, env):
        return subprocess.run(
            argv, timeout=timeout, env=env, capture_output=True, text=True, check=False
        )

    if probe == "api":
        assert _api(run, "GET", f"/user/codespaces/{NAME}", "selected-test-value").returncode == 0
    else:
        assert _ssh_ready(run, NAME, "selected-test-value") is True
    assert probe_out.read_text(encoding="utf-8") == (
        "http://proxy.test:3128|unset|selected-test-value\n"
    )


def test_available_but_ssh_not_ready_still_stops() -> None:
    run = FakeRun(["Available"] + ["Available"] * 12 + ["Shutdown"], ssh=1)
    evidence = run_authorized_lifecycle(
        _auth(), lifecycle_token="lifecycle-test-value", transport_token="transport-test-value", run=run, operation=lambda _: True, consume_authorization=lambda _: True, resolve_codespace=lambda: __import__("workflow_scheduler.governance.dev_validation_codespaces", fromlist=["CodespaceSelection"]).CodespaceSelection(True, "codespaces-capable", NAME, "Available"), sleep=lambda _: None
    )
    assert evidence.status == "needs-decision"
    assert evidence.reason == "codespace-ssh-not-ready"
    assert evidence.cleanup_complete is True
    assert evidence.final_state == "Shutdown"


def test_operation_failure_still_stops() -> None:
    run = FakeRun(["Available", "Available", "Shutdown"])
    evidence = run_authorized_lifecycle(
        _auth(), lifecycle_token="lifecycle-test-value", transport_token="transport-test-value", run=run, operation=lambda _: False, consume_authorization=lambda _: True, resolve_codespace=lambda: __import__("workflow_scheduler.governance.dev_validation_codespaces", fromlist=["CodespaceSelection"]).CodespaceSelection(True, "codespaces-capable", NAME, "Available"), sleep=lambda _: None
    )
    assert evidence.status == "failure"
    assert evidence.reason == "operation-failed"
    assert evidence.cleanup_complete is True


def test_stop_failure_overrides_success() -> None:
    run = FakeRun(["Available"] * 14, stop=1)
    evidence = run_authorized_lifecycle(
        _auth(), lifecycle_token="lifecycle-test-value", transport_token="transport-test-value", run=run, operation=lambda _: True, consume_authorization=lambda _: True, resolve_codespace=lambda: __import__("workflow_scheduler.governance.dev_validation_codespaces", fromlist=["CodespaceSelection"]).CodespaceSelection(True, "codespaces-capable", NAME, "Available"), sleep=lambda _: None
    )
    assert evidence.status == "needs-decision"
    assert evidence.reason == "codespace-cleanup-failed"
    assert evidence.cleanup_complete is False


@pytest.mark.parametrize(
    "auth,token",
    [
        (_auth(repository="other/repo"), "x"),
        (_auth(codespace_name="bad name"), "x"),
        (_auth(authorization_reference=""), "x"),
        (_auth(operation_id=""), "x"),
        (_auth(one_shot=False), "x"),
        (_auth(final_state="Available"), "x"),
        (_auth(), ""),
    ],
)
def test_invalid_authorization_never_calls_provider(auth, token) -> None:
    calls = []
    def run(argv, *, timeout, env):
        calls.append(argv)
        raise AssertionError("provider must not run")
    with pytest.raises(ValueError):
        run_authorized_lifecycle(auth, lifecycle_token=token, transport_token="transport-test-value", run=run, operation=lambda _: True, consume_authorization=lambda _: True)
    assert calls == []


def test_identity_mismatch_fails_before_mutation() -> None:
    calls = []
    def run(argv, *, timeout, env):
        calls.append(tuple(argv))
        payload = {
            "name": NAME,
            "state": "Shutdown",
            "owner": {"login": "someone-else"},
            "repository": {"full_name": REPOSITORY},
        }
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")
    evidence = run_authorized_lifecycle(
        _auth(), lifecycle_token="lifecycle-test-value", transport_token="transport-test-value", run=run, operation=lambda _: True, consume_authorization=lambda _: True, resolve_codespace=lambda: __import__("workflow_scheduler.governance.dev_validation_codespaces", fromlist=["CodespaceSelection"]).CodespaceSelection(False, "codespaces-not-available", NAME, "Shutdown")
    )
    assert evidence.status == "needs-decision"
    assert evidence.reason == "codespace-prestate-invalid"
    assert len(calls) == 1


def test_canonical_target_mismatch_never_mutates() -> None:
    from workflow_scheduler.governance.dev_validation_codespaces import CodespaceSelection
    calls = []
    def run(argv, *, timeout, env):
        calls.append(argv)
        raise AssertionError("provider must not run")
    evidence = run_authorized_lifecycle(
        _auth(),
        lifecycle_token="lifecycle-test-value",
        transport_token="transport-test-value",
        run=run,
        operation=lambda _: True,
        consume_authorization=lambda _: True,
        resolve_codespace=lambda: CodespaceSelection(False, "codespaces-not-available", "different-codespace", "Shutdown"),
    )
    assert evidence.reason == "codespace-canonical-target-mismatch"
    assert evidence.authorization_consumed is False
    assert calls == []


def test_replayed_authorization_rejected_before_mutation() -> None:
    from workflow_scheduler.governance.dev_validation_codespaces import CodespaceSelection
    run = FakeRun(["Shutdown"])
    evidence = run_authorized_lifecycle(
        _auth(),
        lifecycle_token="lifecycle-test-value",
        transport_token="transport-test-value",
        run=run,
        operation=lambda _: True,
        consume_authorization=lambda _: False,
        resolve_codespace=lambda: CodespaceSelection(False, "codespaces-not-available", NAME, "Shutdown"),
    )
    assert evidence.reason == "codespace-authorization-replay-blocked"
    assert evidence.authorization_consumed is False
    assert len(run.calls) == 1


def test_lifecycle_and_transport_credentials_must_be_distinct() -> None:
    from workflow_scheduler.governance.dev_validation_codespaces import CodespaceSelection
    with pytest.raises(ValueError):
        run_authorized_lifecycle(
            _auth(),
            lifecycle_token="same-test-value",
            transport_token="same-test-value",
            run=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
            operation=lambda _: True,
            consume_authorization=lambda _: True,
            resolve_codespace=lambda: CodespaceSelection(False, "codespaces-not-available", NAME, "Shutdown"),
        )
