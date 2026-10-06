from __future__ import annotations

import json
import subprocess

import pytest

from workflow_scheduler.governance.codespaces_lifecycle import (
    LifecycleAuthorization,
    run_authorized_lifecycle,
)
from workflow_scheduler.governance.dev_validation import REPOSITORY

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
        lifecycle_token="redacted",
        run=run,
        operation=lambda name: seen.append(name) is None,
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
    assert all(env == {"GH_TOKEN": "redacted"} for _, env in run.calls)


def test_available_but_ssh_not_ready_still_stops() -> None:
    run = FakeRun(["Available"] + ["Available"] * 12 + ["Shutdown"], ssh=1)
    evidence = run_authorized_lifecycle(
        _auth(), lifecycle_token="redacted", run=run, operation=lambda _: True, sleep=lambda _: None
    )
    assert evidence.status == "needs-decision"
    assert evidence.reason == "codespace-ssh-not-ready"
    assert evidence.cleanup_complete is True
    assert evidence.final_state == "Shutdown"


def test_operation_failure_still_stops() -> None:
    run = FakeRun(["Available", "Available", "Shutdown"])
    evidence = run_authorized_lifecycle(
        _auth(), lifecycle_token="redacted", run=run, operation=lambda _: False, sleep=lambda _: None
    )
    assert evidence.status == "failure"
    assert evidence.reason == "operation-failed"
    assert evidence.cleanup_complete is True


def test_stop_failure_overrides_success() -> None:
    run = FakeRun(["Available", "Available"], stop=1)
    evidence = run_authorized_lifecycle(
        _auth(), lifecycle_token="redacted", run=run, operation=lambda _: True, sleep=lambda _: None
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
        run_authorized_lifecycle(auth, lifecycle_token=token, run=run, operation=lambda _: True)
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
        _auth(), lifecycle_token="redacted", run=run, operation=lambda _: True
    )
    assert evidence.status == "needs-decision"
    assert evidence.reason == "codespace-prestate-invalid"
    assert len(calls) == 1
