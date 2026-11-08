"""D2 Change B: host-local Codespaces transport safety and compatibility.

No real Codespaces, network or subprocess invocation in these tests.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

import pytest

from scripts.agent_os_execution_interface import codespaces_orchestrator_transport as tr

ROOT = "/workspaces/agent-os"
NAME = "happy-codespace"
SHA = "c1101391123c48ff28e91dc8ba0aa31b88598ef2"


def candidate(name=NAME):
    return tr.CodespaceCandidate(
        name=name, state="Available",
        repository_full_name="Blummer92/agent-os", owner_login="Blummer92",
    )


def request(**kwargs):
    values = dict(
        repository="Blummer92/agent-os", issue_identity="3333",
        admission_id="admission-1", argv=("git", "rev-parse", "HEAD"),
        codespace_name_or_none=NAME, base_sha_or_none=SHA,
        workdir_or_none=ROOT, timeout_seconds=90,
        execution_mode_or_none="codespace-host-local",
    )
    values.update(kwargs)
    return tr.TransportRequest(**values)


def run_local_spy(result=(0, SHA + "\n", "")):
    calls = []

    def run(argv, *, cwd, env, timeout_seconds):
        calls.append((argv, cwd, env, timeout_seconds))
        if len(calls) == 1:
            return 0, ROOT + "\n", ""
        if isinstance(result, Exception):
            raise result
        return result

    return calls, run


def execute(monkeypatch, *, req=None, run_local=None, listed=None, run=None):
    monkeypatch.setenv("CODESPACE_NAME", NAME)
    calls, local = run_local_spy()
    return tr.run_codespace_transport(
        req or request(), list_candidates=listed or (lambda: (candidate(),)),
        run_local=run_local or local,
        run=run or (lambda *a, **k: pytest.fail("unexpected SSH fallback")),
    ), calls


def test_local_executes_gate_then_fixed_argv_no_ssh(monkeypatch):
    result, calls = execute(monkeypatch)
    assert result.exit_status_or_none == 0
    assert result.stdout_tail == SHA + "\n"
    assert result.argv == ("git", "rev-parse", "HEAD")
    assert result.execution_surface == "codespaces"
    assert [x[0] for x in calls] == [tr.IDENTITY_GATE_ARGV, ("git", "rev-parse", "HEAD")]
    assert all(x[1] == ROOT and 0 < x[3] <= 90 for x in calls)
    assert calls[1][3] <= calls[0][3]
    assert all(x[2]["PATH"] == "/usr/bin:/bin" for x in calls)
    assert all(x[2]["HOME"] == "/nonexistent" and x[2]["GIT_CONFIG_NOSYSTEM"] == "1" for x in calls)


@pytest.mark.parametrize("gate_rc,gate_stdout", [(1, ""), (0, "/foreign/repo\n")])
def test_gate_failure_never_executes_payload(monkeypatch, gate_rc, gate_stdout):
    monkeypatch.setenv("CODESPACE_NAME", NAME)
    calls = []

    def local(argv, **kwargs):
        calls.append(argv)
        return gate_rc, gate_stdout, "gate-failed"

    result = tr.run_codespace_transport(
        request(), list_candidates=lambda: (candidate(),),
        run_local=local, run=lambda *a, **k: pytest.fail("SSH fallback"),
    )
    assert calls == [tr.IDENTITY_GATE_ARGV]
    assert result.exit_status_or_none != 0
    assert result.stdout_tail == ""
    assert result.stderr_tail == "gate-failed"


@pytest.mark.parametrize("host", [None, "different-codespace", ""])
def test_missing_or_foreign_host_never_runs(monkeypatch, host):
    if host is None:
        monkeypatch.delenv("CODESPACE_NAME", raising=False)
    else:
        monkeypatch.setenv("CODESPACE_NAME", host)
    result = tr.run_codespace_transport(
        request(), list_candidates=lambda: (candidate(),),
        run_local=lambda *a, **k: pytest.fail("local execution"),
        run=lambda *a, **k: pytest.fail("SSH execution"),
    )
    assert result.reason_codes == (tr.TransportReason.CODESPACE_IDENTITY_MISMATCH,)
    assert result.started_at_or_none is None


@pytest.mark.parametrize("overrides", [
    {"workdir_or_none": None},
    {"workdir_or_none": "/other/repo"},
])
def test_invalid_local_workdir_never_lists(monkeypatch, overrides):
    result = tr.run_codespace_transport(
        request(**overrides), list_candidates=lambda: pytest.fail("listing"),
        run_local=lambda *a, **k: pytest.fail("local"),
    )
    assert result.reason_codes == (tr.TransportReason.INVALID_REQUEST,)


def test_missing_requested_codespace_name_fails_before_listing(monkeypatch):
    result = tr.run_codespace_transport(
        request(codespace_name_or_none=None),
        list_candidates=lambda: pytest.fail("listing"),
        run_local=lambda *a, **k: pytest.fail("local"),
    )
    assert result.reason_codes == (tr.TransportReason.CODESPACE_IDENTITY_MISMATCH,)


def test_user_git_configuration_cannot_leak_to_local_probe(monkeypatch):
    monkeypatch.setenv("HOME", "/home/attacker-controlled")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/tmp/attacker.gitconfig")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "/tmp/attacker-hooks")
    env = tr._local_child_env(os.environ["HOME"])
    assert env["HOME"] == "/nonexistent"
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_COUNT"] == "0"
    assert "GIT_CONFIG_KEY_0" not in env
    assert "GIT_CONFIG_VALUE_0" not in env


def test_clean_env_drops_git_and_credentials(monkeypatch):
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GH_TOKEN", "GITHUB_TOKEN", "AGENT_OS_X", "PYTHONPATH", "SSH_AUTH_SOCK"):
        monkeypatch.setenv(key, "poison")
    monkeypatch.setenv("PATH", "/workspaces/agent-os/.venv/bin:/tmp/hostile")
    env = tr._local_child_env("/home/codespace")
    assert env == {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8", "TZ": "UTC", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_COUNT": "0"}


@pytest.mark.parametrize("listed", [(), (candidate("one"), candidate("two"))])
def test_unqualified_selection_never_executes(monkeypatch, listed):
    result = tr.run_codespace_transport(
        request(), list_candidates=lambda: listed,
        run_local=lambda *a, **k: pytest.fail("local"),
        run=lambda *a, **k: pytest.fail("SSH"),
    )
    assert result.started_at_or_none is None


def test_forbidden_argv_fails_before_listing(monkeypatch):
    result = tr.run_codespace_transport(
        request(argv=("git", "push", "origin", "main")),
        list_candidates=lambda: pytest.fail("listing"),
        run_local=lambda *a, **k: pytest.fail("local"),
    )
    assert result.reason_codes == (tr.TransportReason.FORBIDDEN_COMMAND,)


def test_local_timeout_is_uncertain_with_timestamps(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME", NAME)
    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 90)
    result = tr.run_codespace_transport(
        request(), list_candidates=lambda: (candidate(),), run_local=timeout,
        run=lambda *a, **k: pytest.fail("SSH fallback"),
    )
    assert result.reason_codes == (tr.TransportReason.TRANSPORT_TIMEOUT,)
    assert result.started_at_or_none and result.ended_at_or_none


def test_local_oserror_is_uncertain_with_timestamps(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME", NAME)
    def fail(argv, **kwargs):
        raise OSError("local process error")
    result = tr.run_codespace_transport(
        request(), list_candidates=lambda: (candidate(),), run_local=fail,
        run=lambda *a, **k: pytest.fail("SSH fallback"),
    )
    assert result.reason_codes == (tr.TransportReason.TRANSPORT_ERROR,)
    assert result.started_at_or_none and result.ended_at_or_none


def test_request_mode_domain_separation_and_legacy_digest():
    local = request()
    ssh = request(execution_mode_or_none=None)
    assert local.request_id != ssh.request_id
    fields = [
        "Blummer92/agent-os", "3333", "admission-1",
        ["git", "rev-parse", "HEAD"], NAME, SHA, ROOT, 90,
    ]
    expected = hashlib.sha256(json.dumps(fields, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
    assert expected == "298c402f1fcd844ce90b738ee7bac2de14d6ee582a39ed3ddb5f28f1e6b90c88"
    assert ssh.request_id == expected
    assert "execution_mode_or_none" not in ssh.to_dict()
    assert local.to_dict()["execution_mode_or_none"] == "codespace-host-local"


def test_unknown_mode_rejected():
    with pytest.raises(ValueError, match="unsupported execution mode"):
        request(execution_mode_or_none="ssh-fallback")


def test_ssh_mode_never_calls_local(monkeypatch):
    result = tr.run_codespace_transport(
        request(execution_mode_or_none=None),
        list_candidates=lambda: (candidate(),),
        run=lambda *a, **k: (0, SHA, ""),
        run_local=lambda *a, **k: pytest.fail("unexpected local fallback"),
    )
    assert result.exit_status_or_none == 0


def test_local_runner_uses_process_group_and_no_stdin(monkeypatch):
    seen = {}
    class FakePopen:
        pid = 2001
        returncode = 0
        def __init__(self, argv, **kwargs):
            seen["argv"] = argv
            seen["kwargs"] = kwargs
        def communicate(self, timeout=None):
            return "ok", ""
    monkeypatch.setattr(tr.subprocess, "Popen", FakePopen)
    rc, stdout, stderr = tr.default_run_local(
        ("git", "rev-parse", "HEAD"), cwd=ROOT,
        env=tr._local_child_env("/home/codespace"), timeout_seconds=90,
    )
    assert (rc, stdout, stderr) == (0, "ok", "")
    assert seen["kwargs"]["process_group"] == 0
    assert seen["kwargs"]["stdin"] == subprocess.DEVNULL
    assert seen["kwargs"]["shell"] is False


def test_timeout_kills_process_group_and_reaps(monkeypatch):
    seen = []
    class FakePopen:
        pid = 2001
        returncode = -9
        def __init__(self, argv, **kwargs):
            pass
        def communicate(self, timeout=None):
            seen.append(("communicate", timeout))
            if timeout is not None:
                raise subprocess.TimeoutExpired("git", timeout)
            return "", ""
    monkeypatch.setattr(tr.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(tr.os, "killpg", lambda pid, sig: seen.append(("killpg", pid, sig)))
    with pytest.raises(subprocess.TimeoutExpired):
        tr.default_run_local(
            ("git", "rev-parse", "HEAD"), cwd=ROOT,
            env=tr._local_child_env("/home/codespace"), timeout_seconds=90,
        )
    assert seen == [("communicate", 90), ("killpg", 2001, tr.signal.SIGKILL), ("communicate", 2)]

def test_gate_and_payload_share_single_deadline(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME", NAME)
    now = iter([10.0, 10.0, 10.0, 60.0, 60.0])
    monkeypatch.setattr(tr.time, "monotonic", lambda: next(now))
    budgets = []

    def local(argv, *, cwd, env, timeout_seconds):
        budgets.append((argv, timeout_seconds))
        if argv == tr.IDENTITY_GATE_ARGV:
            return 0, ROOT + "\\n", ""
        return 0, SHA + "\\n", ""

    result = tr.run_codespace_transport(
        request(), list_candidates=lambda: (candidate(),),
        run_local=local, run=lambda *a, **k: pytest.fail("SSH fallback"),
    )
    assert result.exit_status_or_none == 0
    assert budgets == [(tr.IDENTITY_GATE_ARGV, 90.0), (("git", "rev-parse", "HEAD"), 40.0)]


def test_exhausted_budget_never_starts_payload(monkeypatch):
    monkeypatch.setenv("CODESPACE_NAME", NAME)
    now = iter([10.0, 10.0, 10.0, 100.0, 100.0])
    monkeypatch.setattr(tr.time, "monotonic", lambda: next(now))
    calls = []

    def local(argv, *, cwd, env, timeout_seconds):
        calls.append(argv)
        return 0, ROOT + "\\n", ""

    result = tr.run_codespace_transport(
        request(), list_candidates=lambda: (candidate(),),
        run_local=local, run=lambda *a, **k: pytest.fail("SSH fallback"),
    )
    assert calls == [tr.IDENTITY_GATE_ARGV]
    assert result.reason_codes == (tr.TransportReason.TRANSPORT_TIMEOUT,)
    assert result.started_at_or_none and result.ended_at_or_none


def test_timeout_reaping_is_bounded_even_when_pipes_stay_open(monkeypatch):
    seen = []
    class FakeStream:
        def close(self):
            seen.append("closed")
    class FakePopen:
        pid = 2001
        stdout = FakeStream()
        stderr = FakeStream()
        def __init__(self, argv, **kwargs):
            pass
        def communicate(self, timeout=None):
            seen.append(("communicate", timeout))
            raise subprocess.TimeoutExpired("git", timeout)
        def kill(self):
            seen.append("kill")
        def wait(self, timeout=None):
            seen.append(("wait", timeout))
            return -9
    monkeypatch.setattr(tr.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(tr.os, "killpg", lambda pid, sig: seen.append(("killpg", pid, sig)))
    with pytest.raises(subprocess.TimeoutExpired):
        tr.default_run_local(("git", "rev-parse", "HEAD"), cwd=ROOT,
                             env=tr._local_child_env(None), timeout_seconds=90)
    assert seen == [("communicate", 90), ("killpg", 2001, tr.signal.SIGKILL),
                    ("communicate", 2), "kill", ("wait", 1), "closed", "closed"]
