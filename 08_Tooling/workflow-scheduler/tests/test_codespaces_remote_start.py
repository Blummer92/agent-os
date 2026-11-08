"""Offline-only tests for the fixed Codespaces lifecycle ingress (#3345)."""
import json
import subprocess

import pytest

from workflow_scheduler.governance.codespaces_remote_start import run_fixed_start
from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event
from workflow_scheduler.governance.dev_validation import REPOSITORY

NAME = "qualified-agent-os-codespace"


def transport(body="/agent-os codespace-start", issue=3345, actor="Blummer92", attempt=1):
    event = {
        "action": "created", "repository": {"full_name": REPOSITORY},
        "issue": {"number": issue},
        "comment": {"id": 1001, "body": body, "user": {"login": actor}},
        "sender": {"login": actor},
    }
    return admit_issue_comment_event(
        event, expected_repository=REPOSITORY, allowed_actor="Blummer92",
        run_attempt=attempt,
    ).to_dict()


class FakeRun:
    def __init__(self, *, listed=None, states=None, ssh_rc=0, start_rc=0):
        self.listed = listed if listed is not None else [(NAME, "Shutdown")]
        self.states = iter(states or ["Shutdown", "Available"])
        self.ssh_rc = ssh_rc
        self.start_rc = start_rc
        self.calls = []

    def __call__(self, argv, *, timeout, env):
        self.calls.append((tuple(argv), dict(env)))
        if argv[:3] == ("gh", "codespace", "ssh"):
            return subprocess.CompletedProcess(argv, self.ssh_rc, "", "")
        assert argv[:3] == ("gh", "api", "--method")
        method, endpoint = argv[3], argv[-1]
        if endpoint.startswith("/repos/"):
            data = [{"name": n, "state": st, "owner": {"login": "Blummer92"},
                     "repository": {"full_name": REPOSITORY}} for n, st in self.listed]
            return subprocess.CompletedProcess(argv, 0, json.dumps({"total_count": len(data), "codespaces": data}), "")
        if endpoint.endswith("/start"):
            return subprocess.CompletedProcess(argv, self.start_rc, "", "")
        if method == "GET" and endpoint.startswith("/user/codespaces/"):
            state = next(self.states)
            return subprocess.CompletedProcess(argv, 0, json.dumps({
                "name": NAME, "state": state, "owner": {"login": "Blummer92"},
                "repository": {"full_name": REPOSITORY},
            }), "")
        raise AssertionError((method, endpoint))


def run(fake, *, payload=None, read="read-token", lifecycle="lifecycle-token"):
    return run_fixed_start(
        transport=payload or transport(), read_token=read,
        lifecycle_token=lifecycle, run=fake, sleep=lambda _: None, wait_attempts=1,
    )


def test_credential_env_never_exposes_both_secret_names(monkeypatch):
    monkeypatch.setenv("AGENT_OS_CODESPACES_READ_TOKEN", "read-token")
    monkeypatch.setenv("AGENT_OS_CODESPACES_LIFECYCLE_TOKEN", "lifecycle-token")
    fake = FakeRun()
    result = run(fake)
    assert result["status"] == "success"
    assert fake.calls
    for _, env in fake.calls:
        assert "AGENT_OS_CODESPACES_READ_TOKEN" not in env
        assert "AGENT_OS_CODESPACES_LIFECYCLE_TOKEN" not in env
        assert "GITHUB_TOKEN" not in env


def test_shutdown_start_and_ssh_ready_never_stops():
    fake = FakeRun()
    result = run(fake)
    assert result["status"] == "success"
    assert result["start_issued"] and result["ssh_ready"]
    assert result["post_state"] == "Available"
    assert result["stop_issued"] is False
    assert sum(cmd[-1].endswith("/start") for cmd, _ in fake.calls) == 1
    assert all(not cmd[-1].endswith("/stop") for cmd, _ in fake.calls)
    assert all("lifecycle-token" not in " ".join(cmd) for cmd, _ in fake.calls)
    api = [(cmd, env) for cmd, env in fake.calls if cmd[:3] == ("gh", "api", "--method")]
    assert all(env["GH_TOKEN"] == ("read-token" if cmd[-1].startswith("/repos/") else "lifecycle-token") for cmd, env in api)
    assert all(env["GH_TOKEN"] == "read-token" for cmd, env in fake.calls if cmd[:3] == ("gh", "codespace", "ssh"))


def test_already_available_is_idempotent():
    fake = FakeRun(listed=[(NAME, "Available")], states=["Available", "Available"])
    result = run(fake)
    assert result["status"] == "success"
    assert result["start_issued"] is False
    assert not any(cmd[-1].endswith("/start") for cmd, _ in fake.calls)


@pytest.mark.parametrize("payload", [
    transport(issue=3333), transport(actor="intruder"),
    transport(attempt=2), transport(body="/agent-os codespace-start extra"),
    {**transport(), "reason": "accepted-codespaces-diagnostic-envelope"},
])
def test_bad_ingress_never_calls_github(payload):
    fake = FakeRun()
    result = run(fake, payload=payload)
    assert result["status"] == "blocked"
    assert fake.calls == []


@pytest.mark.parametrize("listed", [[], [(NAME, "Shutdown"), ("other", "Shutdown")]])
def test_missing_or_ambiguous_target_never_starts(listed):
    fake = FakeRun(listed=listed)
    result = run(fake)
    assert result["status"] == "blocked"
    assert not any(cmd[-1].endswith("/start") for cmd, _ in fake.calls)


def test_state_mismatch_blocks_start():
    fake = FakeRun(states=["Available"])
    result = run(fake)
    assert result["reason_codes"] == ["codespaces-prestate-mismatch"]
    assert not any(cmd[-1].endswith("/start") for cmd, _ in fake.calls)


def test_recheck_detects_target_drift():
    class Drift(FakeRun):
        def __call__(self, argv, *, timeout, env):
            if argv[-1].startswith("/repos/") and any(c[-1].startswith("/repos/") for c, _ in self.calls):
                self.listed = [("other", "Shutdown")]
            return super().__call__(argv, timeout=timeout, env=env)
    fake = Drift()
    result = run(fake)
    assert result["reason_codes"] == ["codespaces-target-drift"]
    assert not any(cmd[-1].endswith("/start") for cmd, _ in fake.calls)


def test_ssh_not_ready_does_not_claim_success():
    fake = FakeRun(ssh_rc=1)
    result = run(fake)
    assert result["status"] == "needs-decision"
    assert result["reason_codes"] == ["codespaces-ssh-readiness-unverified"]


def test_failed_start_is_uncertain_not_retryable():
    fake = FakeRun(start_rc=1)
    result = run(fake)
    assert result["status"] == "needs-decision"
    assert result["reason_codes"] == ["codespaces-start-outcome-uncertain"]
    assert result["start_issued"] is True


def test_missing_or_reused_credentials_fail_closed():
    for read, lifecycle in [("", "lifecycle-token"), ("read-token", ""), ("same", "same")]:
        fake = FakeRun()
        result = run(fake, read=read, lifecycle=lifecycle)
        assert result["status"] == "blocked"
        assert fake.calls == []


def test_comment_id_binds_request_identity():
    a = transport()
    b = transport()
    assert a["logical_trigger_id_or_none"] == b["logical_trigger_id_or_none"]
    assert a["reason"] == "accepted-codespace-start-envelope"
    assert a["execution_authorized"] is False
    event = {
        "action": "created", "repository": {"full_name": REPOSITORY},
        "issue": {"number": 3345},
        "comment": {"id": 1002, "body": "/agent-os codespace-start",
                    "user": {"login": "Blummer92"}},
        "sender": {"login": "Blummer92"},
    }
    other = admit_issue_comment_event(
        event, expected_repository=REPOSITORY,
        allowed_actor="Blummer92", run_attempt=1,
    ).to_dict()
    assert other["logical_trigger_id_or_none"] != a["logical_trigger_id_or_none"]


def test_non_owner_and_rerun_are_rejected_by_parser():
    assert transport(actor="intruder")["reason"] == "actor-not-allowed"
    assert transport(attempt=2)["reason"] == "workflow-rerun"
    assert transport(issue=3333)["reason"] == "codespace-start-issue-mismatch"
