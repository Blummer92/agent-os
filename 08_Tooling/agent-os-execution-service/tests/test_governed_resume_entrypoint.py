import functools
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

from agent_os_execution_service.governed_resume_entrypoint import (
    GovernedResumeBindings,
    build_governed_resume_bindings,
    main,
    parse_handoff_argv,
    run_governed_resume,
)
from agent_os_execution_service.invocation_reconstruction import (
    reconstruct_governed_invocation,
)
from workflow_scheduler.execution.single_issue_pilot import run_single_issue_pilot

H = "executor-handoff:" + "a" * 64
PACKAGE_SRC = Path(__file__).parents[1] / "src"
REPOSITORY_ROOT = Path(__file__).parents[3]


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


def test_main_module_entrypoint_preserves_reconstruction_before_dispatch(capsys):
    calls = []
    pilot = object()

    def reconstruct(handoff_id):
        calls.append(("reconstruct", handoff_id))
        return Result(Status.ADMITTED, ("admitted",), pilot)

    def dispatch(value):
        calls.append(("dispatch", value))

    exit_code = main(
        ["--handoff-id", H],
        bindings=GovernedResumeBindings(reconstruct, dispatch),
    )
    assert exit_code == 0
    assert calls == [("reconstruct", H), ("dispatch", pilot)]
    output = json.loads(capsys.readouterr().out)
    assert output["scheduler_dispatch_count"] == 1


@pytest.mark.parametrize("status", [Status.BLOCKED, Status.STALE, Status.NEEDS_DECISION])
def test_main_nonadmitted_input_never_dispatches(status, capsys):
    dispatched = []
    result = Result(status, ("example-reason",), None)
    exit_code = main(
        ["--handoff-id", H],
        bindings=GovernedResumeBindings(lambda _: result, dispatched.append),
    )
    assert exit_code == 0
    assert dispatched == []
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == status.value
    assert payload["scheduler_dispatch_count"] == 0


def test_main_malformed_argv_fails_before_reconstruction():
    reconstruct_calls = []

    def reconstruct(handoff_id):
        reconstruct_calls.append(handoff_id)
        return Result(Status.ADMITTED, ("admitted",), object())

    with pytest.raises(ValueError):
        main(
            ["--command", "echo pwned"],
            bindings=GovernedResumeBindings(reconstruct, lambda _: None),
        )
    assert reconstruct_calls == []


def test_main_rejects_arbitrary_shell_payload_in_handoff_position():
    with pytest.raises(ValueError):
        main(
            ["--handoff-id", H + "; echo pwned"],
            bindings=GovernedResumeBindings(lambda _: None, lambda _: None),
        )


def test_build_governed_resume_bindings_reuses_canonical_functions_without_duplication():
    bindings = build_governed_resume_bindings(
        descriptor_loader=lambda handoff_id: None,
        resolver=None,
        lease_reader=None,
        evaluated_at="2026-08-18T00:00:00Z",
        lease=None,
        workspace=None,
        executor=None,
        validator=None,
        cancelled=lambda: False,
    )
    assert isinstance(bindings.reconstruct, functools.partial)
    assert bindings.reconstruct.func is reconstruct_governed_invocation
    assert bindings.reconstruct.keywords["evaluated_at"] == "2026-08-18T00:00:00Z"

    assert isinstance(bindings.dispatch, functools.partial)
    assert bindings.dispatch.func is run_single_issue_pilot


def test_module_invoked_as_cli_actually_executes_and_fails_closed_without_composition():
    """Genuine ``python3 -m ...`` invocation, proving the module entrypoint runs.

    With no host-supplied composition, this must fail closed (nonzero exit,
    no silent success) rather than executing a no-op, which was the original
    bug: the installed host command could exit 0 without performing governed
    resume at all.
    """
    env = os.environ | {"PYTHONPATH": str(PACKAGE_SRC)}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_os_execution_service.governed_resume_entrypoint",
            "--handoff-id",
            H,
        ],
        env=env,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "host-supplied" in proc.stderr


def test_module_invoked_as_cli_rejects_malformed_argv_before_any_composition():
    env = os.environ | {"PYTHONPATH": str(PACKAGE_SRC)}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_os_execution_service.governed_resume_entrypoint",
            "--command",
            "echo pwned",
        ],
        env=env,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "echo" not in proc.stdout
    assert "expected exactly --handoff-id" in proc.stderr


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
