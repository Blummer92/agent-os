"""Offline-only tests for the fixed Codespaces lifecycle ingress (#3345)."""
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from workflow_scheduler.governance import codespaces_remote_start as remote_start
from workflow_scheduler.governance.codespaces_remote_start import run_fixed_start
from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event
from workflow_scheduler.governance.dev_validation import REPOSITORY

NAME = "qualified-agent-os-codespace"


def _trusted_event(body="/agent-os codespace-start", issue=3345,
                   actor="Blummer92", comment_id=1001):
    return {
        "action": "created", "repository": {"full_name": REPOSITORY},
        "issue": {"number": issue},
        "comment": {"id": comment_id, "body": body,
                    "user": {"login": actor, "id": 32861845}},
        "sender": {"login": actor, "id": 32861845},
    }


def transport(body="/agent-os codespace-start", issue=3345, actor="Blummer92", attempt=1):
    event = _trusted_event(body, issue, actor)
    return admit_issue_comment_event(
        event, expected_repository=REPOSITORY, allowed_actor="Blummer92",
        run_attempt=attempt,
    ).to_dict()


class FakeRun:
    """Offline `gh` double. ``fail`` maps a phase to an exception raised there.

    Phases: ``discovery``/``recheck`` (first/second listing), ``prestate``
    (state read before any start), ``start`` (the POST itself),
    ``state_after_start`` and ``ssh``.
    """

    def __init__(self, *, listed=None, states=None, ssh_rc=0, start_rc=0, fail=None):
        self.listed = listed if listed is not None else [(NAME, "Shutdown")]
        self.states = iter(states or ["Shutdown", "Available"])
        self.ssh_rc = ssh_rc
        self.start_rc = start_rc
        self.fail = fail or {}
        self.calls = []
        self.listings = 0
        self.starts = 0

    def _maybe_fail(self, phase):
        if phase in self.fail:
            raise self.fail[phase]

    def __call__(self, argv, *, timeout, env):
        self.calls.append((tuple(argv), dict(env)))
        if argv[:3] == ("gh", "codespace", "ssh"):
            self._maybe_fail("ssh")
            return subprocess.CompletedProcess(argv, self.ssh_rc, "", "")
        assert argv[:3] == ("gh", "api", "--method")
        method, endpoint = argv[3], argv[-1]
        if endpoint.startswith("/repos/"):
            self.listings += 1
            self._maybe_fail("discovery" if self.listings == 1 else "recheck")
            data = [{"name": n, "state": st, "owner": {"login": "Blummer92"},
                     "repository": {"full_name": REPOSITORY}} for n, st in self.listed]
            return subprocess.CompletedProcess(argv, 0, json.dumps({"total_count": len(data), "codespaces": data}), "")
        if endpoint.endswith("/start"):
            self.starts += 1
            self._maybe_fail("start")
            return subprocess.CompletedProcess(argv, self.start_rc, "", "")
        if method == "GET" and endpoint.startswith("/user/codespaces/"):
            self._maybe_fail("state_after_start" if self.starts else "prestate")
            state = next(self.states)
            return subprocess.CompletedProcess(argv, 0, json.dumps({
                "name": NAME, "state": state, "owner": {"login": "Blummer92"},
                "repository": {"full_name": REPOSITORY},
            }), "")
        raise AssertionError((method, endpoint))


def run(fake, *, payload=None, read="read-token", lifecycle="lifecycle-token",
        event=None, attempt=1):
    return run_fixed_start(
        transport=payload or transport(), read_token=read,
        lifecycle_token=lifecycle, run=fake,
        trusted_event=_trusted_event() if event is None else event,
        trusted_run_attempt=attempt,
        sleep=lambda _: None, wait_attempts=1,
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


# R1 (#3828 independent QA): a raise after a start request may have been sent
# must stay a truthful uncertain outcome, never "blocked / no start", and is
# never retried.

_FAULTS = [
    ValueError("bad"),
    TypeError("bad"),
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    KeyError("bad"),
    RuntimeError("bad"),
]


def _fault_id(error):
    return type(error).__name__


def _no_stop(fake):
    return all(not argv[-1].endswith("/stop") for argv, _ in fake.calls)


@pytest.mark.parametrize("phase", ["start", "state_after_start", "ssh"])
@pytest.mark.parametrize("error", _FAULTS, ids=_fault_id)
def test_any_failure_after_start_request_is_uncertain_and_never_retried(phase, error):
    fake = FakeRun(fail={phase: error})
    result = run(fake)
    assert result["status"] == "needs-decision"
    assert result["reason_codes"] == ["codespaces-start-outcome-uncertain"]
    assert result["start_issued"] is True
    assert fake.starts == 1
    assert _no_stop(fake)


@pytest.mark.parametrize("error", _FAULTS, ids=_fault_id)
def test_failure_while_verifying_available_target_never_claims_a_start(error):
    fake = FakeRun(listed=[(NAME, "Available")], states=["Available", "Available"],
                   fail={"ssh": error})
    result = run(fake)
    assert result["status"] == "needs-decision"
    assert result["reason_codes"] == ["codespaces-ssh-readiness-unverified"]
    assert result["start_issued"] is False
    assert fake.starts == 0
    assert _no_stop(fake)


@pytest.mark.parametrize("phase", ["discovery", "prestate", "recheck"])
@pytest.mark.parametrize("error", _FAULTS, ids=_fault_id)
def test_failure_before_any_start_request_is_blocked_without_start(phase, error):
    fake = FakeRun(fail={phase: error})
    result = run(fake)
    assert result["status"] == "blocked"
    expected = "codespaces-discovery-error" if phase == "discovery" else "codespaces-precheck-error"
    assert result["reason_codes"] == [expected]
    assert result["start_issued"] is False
    assert fake.starts == 0


def _invoke_main(tmp_path, monkeypatch, fake, transport_text):
    monkeypatch.setenv("AGENT_OS_CODESPACES_READ_TOKEN", "read-token")
    monkeypatch.setenv("AGENT_OS_CODESPACES_LIFECYCLE_TOKEN", "lifecycle-token")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_trusted_event()), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setattr(remote_start.subprocess, "run",
                        lambda argv, **kw: fake(argv, timeout=kw["timeout"], env=kw["env"]))
    source = tmp_path / "transport.json"
    source.write_text(transport_text, encoding="utf-8")
    output = tmp_path / "result.json"
    code = remote_start.main(["--transport", str(source), "--output", str(output)])
    return code, json.loads(output.read_text(encoding="utf-8"))


@pytest.mark.parametrize("phase", ["start", "state_after_start"])
@pytest.mark.parametrize("error", [
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"), KeyError("bad"),
], ids=_fault_id)
def test_main_records_uncertain_receipt_when_execution_raises_after_start(
    tmp_path, monkeypatch, phase, error,
):
    fake = FakeRun(fail={phase: error})
    code, receipt = _invoke_main(tmp_path, monkeypatch, fake, json.dumps(transport()))
    assert code == 1
    assert receipt["status"] == "needs-decision"
    assert receipt["reason_codes"] == ["codespaces-start-outcome-uncertain"]
    assert receipt["start_issued"] is True
    assert fake.starts == 1
    assert _no_stop(fake)


@pytest.mark.parametrize("text", ["not json", "[1]", "\"accepted\""])
def test_main_rejects_invalid_transport_before_any_call(tmp_path, monkeypatch, text):
    fake = FakeRun()
    code, receipt = _invoke_main(tmp_path, monkeypatch, fake, text)
    assert code == 1
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["codespaces-start-input-invalid"]
    assert fake.calls == []


def test_unusual_run_id_cannot_raise_outside_the_recorded_outcome(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "\u00b2")
    result = run(FakeRun())
    assert result["status"] == "success"
    assert result["workflow_run_id"] is None


# R2 (#3828 independent QA): typed narrowing is an explicit fail-closed check.

def test_qualified_target_without_a_name_fails_closed(monkeypatch):
    monkeypatch.setattr(remote_start, "_list_target",
                        lambda run, token: (None, "Shutdown", "qualified"))
    fake = FakeRun()
    result = run(fake)
    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["codespaces-discovery-invalid"]
    assert fake.calls == []


# R3 (#3828 independent QA): numeric transport fields require exact int.

@pytest.mark.parametrize("field, value", [
    ("run_attempt", True), ("run_attempt", 1.0),
    ("issue_number", 3345.0), ("issue_number", True),
    ("comment_id", True), ("comment_id", 1001.0),
])
def test_numeric_transport_fields_require_exact_int(field, value):
    payload = transport()
    payload[field] = value
    fake = FakeRun()
    result = run(fake, payload=payload)
    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["start-authorization-or-credential-unavailable"]
    assert fake.calls == []


# R4 (#3828 independent QA): lifecycle_authorized is explicit evidence that
# every owner, credential, target and pre-state check passed for this target.

@pytest.mark.parametrize("label, fake, payload_override, expected", [
    ("gate-blocked", FakeRun(), {"actor": "intruder"}, ("blocked", False)),
    ("discovery-blocked", FakeRun(listed=[]), None, ("blocked", False)),
    ("discovery-raises", FakeRun(fail={"discovery": OSError("x")}), None, ("blocked", False)),
    ("prestate-mismatch", FakeRun(states=["Available"]), None, ("blocked", False)),
    ("prestate-raises", FakeRun(fail={"prestate": OSError("x")}), None, ("blocked", False)),
    ("target-drift", FakeRun(fail={"recheck": OSError("x")}), None, ("blocked", False)),
    ("success-after-start", FakeRun(), None, ("success", True)),
    ("success-already-available",
     FakeRun(listed=[(NAME, "Available")], states=["Available", "Available"]), None, ("success", True)),
    ("start-uncertain", FakeRun(start_rc=1), None, ("needs-decision", True)),
    ("start-raises", FakeRun(fail={"start": RuntimeError("x")}), None, ("needs-decision", True)),
    ("readiness-unverified", FakeRun(ssh_rc=1), None, ("needs-decision", True)),
])
def test_lifecycle_authorized_is_explicit_per_path(label, fake, payload_override, expected):
    payload = transport()
    payload.update(payload_override or {})
    result = run(fake, payload=payload)
    assert (result["status"], result["lifecycle_authorized"]) == expected, label


# R5 (#3828 independent QA): the log line and the uploaded receipt agree.

def test_logged_receipt_matches_uploaded_receipt(tmp_path, monkeypatch, capsys):
    code, receipt = _invoke_main(tmp_path, monkeypatch, FakeRun(), json.dumps(transport()))
    logged = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0
    assert logged == receipt
    assert receipt["codespace_name"] == NAME


# Workflow conditions (#3828): the lifecycle lane is reachable only by the
# exact owner command on #3345, with least privilege and two separate secrets.

_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "agent-os-governed-invocation.yml"
_COMMAND = "/agent-os codespace-start"


def _jobs():
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _conjuncts(expression):
    inner = expression.strip()
    assert inner.startswith("${{") and inner.endswith("}}")
    return {" ".join(part.split()) for part in inner[3:-2].split("&&")}


def test_lifecycle_job_condition_is_exact():
    job = _jobs()["codespace_start"]
    assert _conjuncts(job["if"]) == {
        "github.event.issue.pull_request == null",
        "github.ref == 'refs/heads/main'",
        "github.event.issue.number == 3345",
        "github.event.comment.user.id == 32861845",
        "github.event.sender.id == 32861845",
        f"github.event.comment.body == '{_COMMAND}'",
        "github.run_attempt == 1",
    }


def test_ordinary_ingress_excludes_the_lifecycle_command():
    assert f"github.event.comment.body != '{_COMMAND}'" in _conjuncts(_jobs()["ingress"]["if"])


def test_no_other_job_condition_admits_the_lifecycle_command():
    for name, job in _jobs().items():
        if name in {"codespace_start", "ingress"}:
            continue
        positive = [c for c in _conjuncts(job.get("if", "${{ true }}")) if not c.startswith("!")]
        for prefix in re.findall(r"startsWith\(github\.event\.comment\.body, '([^']*)'\)", " ".join(positive)):
            assert not _COMMAND.startswith(prefix), (name, prefix)
        assert f"github.event.comment.body == '{_COMMAND}'" not in positive, name


def test_lifecycle_job_least_privilege_and_credential_separation():
    job = _jobs()["codespace_start"]
    assert job["permissions"] == {"contents": "read"}
    assert job["concurrency"] == {
        "group": "agent-os-codespace-lifecycle-${{ github.repository_id }}",
        "cancel-in-progress": False,
    }
    steps = job["steps"]
    checkout = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert len(checkout) == 1 and checkout[0]["with"]["persist-credentials"] is False
    with_secrets = [s for s in steps if "secrets." in json.dumps(s)]
    assert len(with_secrets) == 1
    assert with_secrets[0]["env"] == {
        "AGENT_OS_CODESPACES_READ_TOKEN": "${{ secrets.AGENT_OS_CODESPACES_TOKEN }}",
        "AGENT_OS_CODESPACES_LIFECYCLE_TOKEN": "${{ secrets.AGENT_OS_CODESPACES_LIFECYCLE_TOKEN }}",
    }
    for step in steps:
        assert "github.event.comment" not in step.get("run", ""), step.get("name")


# Copilot review 5820268180: mutation adapter must bind its transport to the
# runner-provided event, not merely accept self-consistent JSON authority.
@pytest.mark.parametrize("field, value", [
    ("logical_trigger_id_or_none", None),
    ("logical_trigger_id_or_none", "issue-comment-trigger:" + "a" * 64),
    ("execution_authorized", True),
    ("scheduler_invoked", True),
    ("side_effects_performed", True),
    ("handoff_id_or_none", "forged"),
    ("status", "ignored"),
])
def test_forged_transport_claims_never_reach_github(field, value):
    payload = transport()
    payload[field] = value
    fake = FakeRun()
    result = run(fake, payload=payload)
    assert result["status"] == "blocked"
    assert fake.calls == []


@pytest.mark.parametrize("change", [
    lambda event: event["comment"].update(id=1002),
    lambda event: event["comment"].update(body="/agent-os codespace-start extra"),
    lambda event: event["comment"]["user"].update(login="intruder"),
    lambda event: event["comment"]["user"].update(id=7),
    lambda event: event["sender"].update(id=7),
    lambda event: event["issue"].update(number=3333),
    lambda event: event.update(action="edited"),
    lambda event: event["issue"].update(pull_request={}),
    lambda event: event["repository"].update(full_name="elsewhere/repo"),
])
def test_trusted_event_mismatch_never_reaches_github(change):
    event = _trusted_event()
    change(event)
    fake = FakeRun()
    result = run(fake, event=event)
    assert result["status"] == "blocked"
    assert fake.calls == []


def test_trusted_attempt_rerun_never_reaches_github():
    fake = FakeRun()
    result = run(fake, attempt=2)
    assert result["status"] == "blocked"
    assert fake.calls == []


def test_no_event_evidence_cannot_authorize_mutation():
    fake = FakeRun()
    result = run_fixed_start(
        transport=transport(), trusted_event=None, trusted_run_attempt=1,
        read_token="read-token", lifecycle_token="lifecycle-token", run=fake,
        sleep=lambda _: None, wait_attempts=1,
    )
    assert result["status"] == "blocked"
    assert fake.calls == []


@pytest.mark.parametrize("state", [None, "", False])
def test_unreadable_prestate_gets_precheck_error_not_mismatch(monkeypatch, state):
    monkeypatch.setattr(remote_start, "_state", lambda *_: state)
    fake = FakeRun()
    result = run(fake)
    if state is None:
        assert result["reason_codes"] == ["codespaces-precheck-error"]
    else:
        assert result["reason_codes"] == ["codespaces-prestate-mismatch"]
    assert result["lifecycle_authorized"] is False
    assert result["start_issued"] is False
    assert fake.starts == 0


def test_main_missing_event_fails_closed_before_github(tmp_path, monkeypatch):
    fake = FakeRun()
    monkeypatch.setenv("AGENT_OS_CODESPACES_READ_TOKEN", "read-token")
    monkeypatch.setenv("AGENT_OS_CODESPACES_LIFECYCLE_TOKEN", "lifecycle-token")
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(remote_start.subprocess, "run",
                        lambda argv, **kw: fake(argv, timeout=kw["timeout"], env=kw["env"]))
    inp, out = tmp_path / "transport.json", tmp_path / "result.json"
    inp.write_text(json.dumps(transport()), encoding="utf-8")
    assert remote_start.main(["--transport", str(inp), "--output", str(out)]) == 1
    assert json.loads(out.read_text())["status"] == "blocked"
    assert fake.calls == []


def test_self_consistent_forged_comment_id_cannot_authorize_start():
    # The hash is public and deterministic: a forged JSON envelope can carry
    # the *correct* hash for the wrong comment. The trusted event still wins.
    forged = admit_issue_comment_event(
        _trusted_event(comment_id=1002), expected_repository=REPOSITORY,
        allowed_actor="Blummer92", run_attempt=1,
    ).to_dict()
    assert forged["logical_trigger_id_or_none"] != transport()["logical_trigger_id_or_none"]
    fake = FakeRun()
    result = run(fake, payload=forged)
    assert result["status"] == "blocked"
    assert fake.calls == []
