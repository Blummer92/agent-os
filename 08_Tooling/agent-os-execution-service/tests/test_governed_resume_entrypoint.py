import json
from dataclasses import dataclass
from enum import Enum

import pytest

from agent_os_execution_service.governed_resume_entrypoint import (
    GovernedResumeBindings,
    parse_handoff_argv,
    run_governed_resume,
)

H = "executor-handoff:" + "a" * 64


class Status(str, Enum):
    ADMITTED = "admitted"
    BLOCKED = "blocked"
    STALE = "stale"
    NEEDS_DECISION = "needs-decision"


@dataclass
class Result:
    status: Status
    reason_codes: tuple[str, ...]
    pilot_input: object | None


def test_accepts_only_exact_canonical_handoff_argv():
    assert parse_handoff_argv(["--handoff-id", H]) == H
    bad = [
        [], ["--handoff-id"], [H], ["--handoff-id", H, "echo pwned"],
        ["--command", "echo pwned"],
        ["--handoff-id", "executor-handoff:" + "A" * 64],
        ["--handoff-id", "executor-handoff:123"],
    ]
    for argv in bad:
        with pytest.raises(ValueError):
            parse_handoff_argv(argv)


def test_reconstruction_precedes_single_dispatch():
    calls = []
    pilot = object()

    def reconstruct(handoff_id):
        calls.append(("reconstruct", handoff_id))
        return Result(Status.ADMITTED, ("admitted",), pilot)

    def dispatch(value):
        calls.append(("dispatch", value))

    output = run_governed_resume(
        ["--handoff-id", H],
        bindings=GovernedResumeBindings(reconstruct, dispatch),
    )
    assert calls == [("reconstruct", H), ("dispatch", pilot)]
    assert json.loads(output)["scheduler_dispatch_count"] == 1


@pytest.mark.parametrize("status", [Status.BLOCKED, Status.STALE, Status.NEEDS_DECISION])
def test_nonadmitted_result_never_dispatches(status):
    dispatched = []
    result = Result(status, ("example-reason",), None)
    output = run_governed_resume(
        ["--handoff-id", H],
        bindings=GovernedResumeBindings(lambda _: result, dispatched.append),
    )
    payload = json.loads(output)
    assert dispatched == []
    assert payload["status"] == status.value
    assert payload["scheduler_dispatch_count"] == 0


def test_admitted_without_pilot_input_fails_closed():
    dispatched = []
    result = Result(Status.ADMITTED, ("admitted",), None)
    payload = json.loads(
        run_governed_resume(
            ["--handoff-id", H],
            bindings=GovernedResumeBindings(lambda _: result, dispatched.append),
        )
    )
    assert dispatched == []
    assert payload["status"] == "needs-decision"


def test_bounded_evidence_does_not_echo_command_text():
    result = Result(Status.BLOCKED, ("blocked",), None)
    payload = run_governed_resume(
        ["--handoff-id", H],
        bindings=GovernedResumeBindings(lambda _: result, lambda _: None),
    )
    assert "echo" not in payload
    assert set(json.loads(payload)) == {
        "handoff_id", "reason_codes", "scheduler_dispatch_count", "schema", "status"
    }


def test_installer_contract_is_fixed_and_idempotent(tmp_path):
    import hashlib
    import os
    import pathlib
    import stat
    import subprocess

    installer = pathlib.Path(__file__).parents[1] / "scripts" / "install-governed-resume"
    target = tmp_path / "agent-os-governed-resume"
    env = os.environ | {
        "TARGET": str(target),
        "OWNER": subprocess.check_output(["id", "-un"], text=True).strip(),
        "GROUP": subprocess.check_output(["id", "-gn"], text=True).strip(),
        "MODE": "0755",
    }
    subprocess.run([str(installer)], check=True, env=env)
    first = target.read_bytes()
    digest = hashlib.sha256(first).hexdigest()
    subprocess.run([str(installer)], check=True, env=env)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    text = target.read_text()
    assert "systemd-run --user --scope -p Delegate=yes --quiet" in text
    assert "python3 -m agent_os_execution_service.governed_resume_entrypoint" in text
    assert '"$@"' in text


def test_installer_refuses_unrelated_target(tmp_path):
    import os
    import pathlib
    import subprocess

    installer = pathlib.Path(__file__).parents[1] / "scripts" / "install-governed-resume"
    proc = subprocess.run(
        [str(installer)],
        env=os.environ | {"TARGET": str(tmp_path / "not-the-entrypoint")},
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 64
    assert "refusing unexpected target" in proc.stderr
