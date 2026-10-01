"""Tests for WSC0/#3200's ``process_group_containment`` preflight,
invocation process-group lifecycle, escalation, survivor scan, rlimits,
and the explicit attestation record.

Process-group tests run for real on any POSIX host with a listable
``/proc`` -- no cgroup delegation is required, which is the point of the
lighter variant. Only the cgroup-delegation field of the preflight is
asserted loosely (it is an honest probe, not a gate).
"""

from __future__ import annotations

import os
import resource
import signal
import sys
import time
import uuid
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(SCHEDULER_SRC) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SRC))

from workflow_scheduler.execution import process_group_containment as pg_module  # noqa: E402
from workflow_scheduler.execution.process_group_containment import (  # noqa: E402
    GUARANTEES_NOT_CLAIMED,
    InvocationProcessGroup,
    ProcessGroupContainmentError,
    ProcessGroupLaunchError,
    ProcessGroupPreflightError,
    ProcessGroupReapError,
    ProcessGroupSurvivorError,
    ProcessGroupTerminateError,
    pgid_live_survivors,
    preflight_check,
)

requires_posix_proc = pytest.mark.skipif(
    os.name != "posix" or not os.path.isdir("/proc"),
    reason="process-group containment tests need a POSIX host with /proc",
)


def _invocation_id() -> str:
    return f"test-{uuid.uuid4().hex}"


def _pid_alive(pid: int) -> bool:
    """True only if the pid exists and is not a zombie.

    ``os.kill(pid, 0)`` succeeds for zombies, so the state is read from
    ``/proc`` too: a zombie is already dead and must not count as alive.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return True  # exists but unreadable: stay conservative
    tail = text.rsplit(")", 1)
    if len(tail) != 2:
        return True
    fields = tail[1].split()
    return not fields or fields[0] != "Z"


# --------------------------------------------------------------------------
# Preflight: fails closed, honest about cgroup delegation
# --------------------------------------------------------------------------


@requires_posix_proc
def test_preflight_usable_on_this_posix_host() -> None:
    result = preflight_check()
    assert result.usable is True
    assert result.setpgid_available is True
    assert result.rlimit_available is True
    assert result.reason == ""
    # An honest probe, not a gate: this field is a bool either way.
    assert isinstance(result.cgroup_delegation_available, bool)


def test_preflight_fails_closed_on_non_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    result = preflight_check()
    assert result.usable is False
    assert result.setpgid_available is False
    assert result.reason != ""


def test_preflight_fails_closed_when_resource_module_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pg_module, "_resource", None)
    result = preflight_check()
    assert result.usable is False
    assert result.rlimit_available is False
    assert "resource" in result.reason


def test_preflight_fails_closed_when_proc_unlistable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_path: str) -> list[str]:
        raise OSError("no /proc here")

    monkeypatch.setattr(pg_module.os, "listdir", _boom)
    result = preflight_check()
    assert result.usable is False
    assert "/proc" in result.reason


def test_preflight_result_is_immutable() -> None:
    result = preflight_check()
    with pytest.raises(AttributeError):
        result.usable = False  # type: ignore[misc]


def test_preflight_probes_cgroup_delegation_honestly() -> None:
    """The delegation field must match an independent create/remove probe.

    It is an honest measurement, not a hardcoded value: whatever this
    host allows, the preflight must report the same. (As root on this VM
    the probe genuinely succeeds; in a container venue it reports False.)
    """
    independent = False
    for candidate in ("/sys/fs/cgroup", "/sys/fs/cgroup/unified"):
        if not os.path.isfile(os.path.join(candidate, "cgroup.controllers")):
            continue
        probe = os.path.join(candidate, f".agentos-independent-probe-{os.getpid()}")
        try:
            os.mkdir(probe)
            os.rmdir(probe)
            independent = True
            break
        except OSError:
            continue
    result = preflight_check()
    assert result.cgroup_delegation_available is independent


# --------------------------------------------------------------------------
# Launch: one fresh process group per invocation
# --------------------------------------------------------------------------


@requires_posix_proc
def test_launch_creates_a_fresh_pgid_distinct_from_parent() -> None:
    with InvocationProcessGroup.launch(["/bin/sleep", "30"], invocation_id=_invocation_id()) as inv:
        assert inv.pgid == inv.pid
        assert inv.pgid != os.getpgid(0)
        assert os.getpgid(inv.pid) == inv.pgid


@requires_posix_proc
def test_two_invocations_get_distinct_pgids() -> None:
    with InvocationProcessGroup.launch(["/bin/sleep", "30"], invocation_id=_invocation_id()) as first:
        with InvocationProcessGroup.launch(["/bin/sleep", "30"], invocation_id=_invocation_id()) as second:
            assert first.pgid != second.pgid


def test_launch_rejects_unsafe_invocation_id() -> None:
    with pytest.raises(ProcessGroupLaunchError):
        InvocationProcessGroup.launch(["/bin/true"], invocation_id="../escape")
    with pytest.raises(ProcessGroupLaunchError):
        InvocationProcessGroup.launch(["/bin/true"], invocation_id="")


def test_launch_rejects_empty_argv() -> None:
    with pytest.raises(ProcessGroupLaunchError):
        InvocationProcessGroup.launch([], invocation_id=_invocation_id())


def test_launch_rejects_unknown_rlimit_key() -> None:
    with pytest.raises(ProcessGroupLaunchError):
        InvocationProcessGroup.launch(
            ["/bin/true"], rlimits={"RLIMIT_NO_SUCH_LIMIT": (1, 1)}, invocation_id=_invocation_id()
        )


def test_launch_rejects_malformed_rlimit_bounds() -> None:
    with pytest.raises(ProcessGroupLaunchError):
        InvocationProcessGroup.launch(
            ["/bin/true"], rlimits={"RLIMIT_NPROC": (1,)}, invocation_id=_invocation_id()
        )


def test_launch_wraps_spawn_failure() -> None:
    with pytest.raises(ProcessGroupLaunchError):
        InvocationProcessGroup.launch(
            ["/no/such/binary/agent-os"], invocation_id=_invocation_id()
        )


# --------------------------------------------------------------------------
# Termination: SIGTERM grace, SIGKILL escalation, survivor scan
# --------------------------------------------------------------------------


@requires_posix_proc
def test_graceful_sigterm_kills_a_multiprocess_group(tmp_path: Path) -> None:
    """Child spawns a grandchild; SIGTERM to the pgid must kill both."""
    grandchild_pid_file = tmp_path / "grandchild.pid"
    script = (
        "import os, subprocess, time\n"
        "grandchild = subprocess.Popen(['/bin/sleep', '30'])\n"
        f"open({str(grandchild_pid_file)!r}, 'w').write(str(grandchild.pid))\n"
        "time.sleep(30)\n"
    )
    with InvocationProcessGroup.launch(
        [sys.executable, "-c", script], invocation_id=_invocation_id()
    ) as inv:
        deadline = time.monotonic() + 5.0
        while not grandchild_pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        grandchild_pid = int(grandchild_pid_file.read_text())
        inv.terminate(grace_seconds=2.0)
        record = inv.containment_record()
        assert record["survivor_scan"] == 0
        assert record["sigkill_ts"] is None  # SIGTERM was enough
        assert not _pid_alive(grandchild_pid)
        assert not _pid_alive(inv.pid)


@requires_posix_proc
def test_sigkill_escalation_for_a_sigterm_ignorer(tmp_path: Path) -> None:
    """A child that ignores SIGTERM must still die via the bounded escalation.

    The child signals readiness only after installing SIG_IGN, so the
    SIGTERM cannot race interpreter startup and hit the default disposition.
    """
    ready_file = tmp_path / "ready"
    script = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(ready_file)!r}, 'w').write('ready')\n"
        "time.sleep(30)\n"
    )
    with InvocationProcessGroup.launch(
        [sys.executable, "-c", script], invocation_id=_invocation_id()
    ) as inv:
        deadline = time.monotonic() + 5.0
        while not ready_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready_file.exists(), "child never installed its SIGTERM handler"
        inv.terminate(grace_seconds=1.0)
        record = inv.containment_record()
        assert record["sigkill_ts"] is not None
        assert record["survivor_scan"] == 0
        assert not _pid_alive(inv.pid)
        assert record["reap_status"] == "reaped:signaled:9"


@requires_posix_proc
def test_sigkill_escalation_reaches_a_lingering_grandchild(tmp_path: Path) -> None:
    """Child exits at once; a SIGTERM-ignoring grandchild must still die.

    The SIGTERM grace finds the direct child already gone but the pgid
    still populated, so terminate() must escalate to SIGKILL rather than
    declare victory. The grandchild handshakes readiness after installing
    SIG_IGN so the first SIGTERM cannot race interpreter startup.
    """
    grandchild_pid_file = tmp_path / "grandchild.pid"
    grandchild_ready = tmp_path / "grandchild.ready"
    grandchild_code = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(grandchild_ready)!r}, 'w').write('ready')\n"
        "time.sleep(30)\n"
    )
    script = (
        "import subprocess, sys\n"
        f"grandchild = subprocess.Popen([sys.executable, '-c', {grandchild_code!r}])\n"
        f"open({str(grandchild_pid_file)!r}, 'w').write(str(grandchild.pid))\n"
    )
    with InvocationProcessGroup.launch(
        [sys.executable, "-c", script], invocation_id=_invocation_id()
    ) as inv:
        deadline = time.monotonic() + 5.0
        while not grandchild_ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert grandchild_ready.exists(), "grandchild never installed its SIGTERM handler"
        grandchild_pid = int(grandchild_pid_file.read_text())
        inv.terminate(grace_seconds=1.0)
        record = inv.containment_record()
        assert record["sigkill_ts"] is not None
        assert record["survivor_scan"] == 0
        assert not _pid_alive(grandchild_pid)


@requires_posix_proc
def test_terminate_is_idempotent() -> None:
    with InvocationProcessGroup.launch(["/bin/sleep", "30"], invocation_id=_invocation_id()) as inv:
        inv.terminate(grace_seconds=1.0)
        inv.terminate(grace_seconds=1.0)  # second call must not raise
        assert inv.containment_record()["survivor_scan"] == 0


@requires_posix_proc
def test_terminate_rejects_negative_grace() -> None:
    with InvocationProcessGroup.launch(["/bin/sleep", "30"], invocation_id=_invocation_id()) as inv:
        with pytest.raises(ProcessGroupTerminateError):
            inv.terminate(grace_seconds=-1.0)


@requires_posix_proc
def test_survivor_scan_returns_zero_after_clean_exit() -> None:
    inv = InvocationProcessGroup.launch(["/bin/true"], invocation_id=_invocation_id())
    with inv:
        # Deterministic: reap the clean exit here. Otherwise __exit__'s
        # SIGTERM could race the child's startup and signal it first.
        inv.reap()
    assert pgid_live_survivors(inv.pgid) == []
    assert inv.containment_record()["survivor_scan"] == 0
    assert inv.containment_record()["reap_status"] == "reaped:exited:0"


def test_fail_closed_on_survivor(monkeypatch: pytest.MonkeyPatch) -> None:
    """A survivor after SIGKILL raises ProcessGroupSurvivorError -- never ignored."""
    monkeypatch.setattr(pg_module, "pgid_live_survivors", lambda _pgid: [424242])
    inv = InvocationProcessGroup.launch(["/bin/sleep", "30"], invocation_id=_invocation_id())
    try:
        with pytest.raises(ProcessGroupSurvivorError) as excinfo:
            inv.terminate(grace_seconds=0.1, settle_seconds=0.1)
        assert "424242" in str(excinfo.value)
    finally:
        # The monkeypatched scan lied; really clean up.
        monkeypatch.undo()
        try:
            os.killpg(inv.pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        inv.reap()
        inv.drain()


# --------------------------------------------------------------------------
# Rlimits: actually applied in the child
# --------------------------------------------------------------------------


@requires_posix_proc
def test_rlimit_cpu_kills_a_spinner() -> None:
    """A tight RLIMIT_CPU must kill a CPU spinner without our terminate()."""
    script = "while True:\n    pass\n"
    with InvocationProcessGroup.launch(
        [sys.executable, "-c", script],
        rlimits={"RLIMIT_CPU": (1, 1)},
        invocation_id=_invocation_id(),
    ) as inv:
        # Give the kernel a moment to enforce the CPU limit on its own.
        deadline = time.monotonic() + 10.0
        while _pid_alive(inv.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _pid_alive(inv.pid)
        inv.reap()
        record = inv.containment_record()
        assert "signaled" in record["reap_status"]
        assert record["rlimits_applied"] == {"RLIMIT_CPU": [1, 1]}


def _uid_thread_count() -> int:
    """Threads (tasks), not processes: RLIMIT_NPROC counts threads."""
    uid = os.getuid()
    total = 0
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            if os.stat(f"/proc/{entry}").st_uid != uid:
                continue
            total += len(os.listdir(f"/proc/{entry}/task"))
        except OSError:
            continue
    return total


@requires_posix_proc
def test_rlimit_nproc_caps_fork(tmp_path: Path) -> None:
    """RLIMIT_NPROC must cap how many grandchildren the child can fork."""
    limit = _uid_thread_count() + 10
    result_file = tmp_path / "forks"
    script = (
        "import subprocess, time\n"
        "kids = []\n"
        "ok = 0\n"
        "for _ in range(30):\n"
        "    try:\n"
        "        kids.append(subprocess.Popen(['/bin/sleep', '30']))\n"
        "        ok += 1\n"
        "    except OSError:\n"
        "        break\n"
        f"open({str(result_file)!r}, 'w').write(str(ok))\n"
        "time.sleep(30)\n"
    )
    with InvocationProcessGroup.launch(
        [sys.executable, "-c", script],
        rlimits={resource.RLIMIT_NPROC: (limit, limit)},
        invocation_id=_invocation_id(),
    ) as inv:
        # Wait for the fork loop to finish before __exit__ terminates the
        # group; the count file is the deterministic handshake.
        deadline = time.monotonic() + 10.0
        while not result_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert result_file.exists(), "child never finished its fork loop"
    successful = int(result_file.read_text())
    assert 1 <= successful < 30
    record = inv.containment_record()
    assert record["rlimits_applied"] == {"RLIMIT_NPROC": [limit, limit]}
    assert record["survivor_scan"] == 0


@requires_posix_proc
def test_rlimit_names_resolve_to_constants() -> None:
    inv = InvocationProcessGroup.launch(
        ["/bin/true"],
        rlimits={"RLIMIT_AS": (2**30, 2**30), resource.RLIMIT_FSIZE: (2**20, 2**20)},
        invocation_id=_invocation_id(),
    )
    with inv:
        pass
    applied = inv.containment_record()["rlimits_applied"]
    assert applied["RLIMIT_AS"] == [2**30, 2**30]
    assert applied["RLIMIT_FSIZE"] == [2**20, 2**20]


# --------------------------------------------------------------------------
# Reap, drain, record, attestation
# --------------------------------------------------------------------------


@requires_posix_proc
def test_reap_observes_exit_status_and_drain_collects_output() -> None:
    script = "import sys; print('hello-stdout'); print('hello-stderr', file=sys.stderr); sys.exit(3)\n"
    with InvocationProcessGroup.launch(
        [sys.executable, "-c", script], invocation_id=_invocation_id()
    ) as inv:
        # Deterministic: reap the child's own exit here, so the record
        # cannot race __exit__'s SIGTERM against interpreter startup.
        inv.reap()
    assert inv.containment_record()["reap_status"] == "reaped:exited:3"
    assert inv.containment_record()["drain_status"] == "complete"
    assert b"hello-stdout" in inv._stdout_tail
    assert b"hello-stderr" in inv._stderr_tail


@requires_posix_proc
def test_attestation_block_states_what_is_not_claimed() -> None:
    with InvocationProcessGroup.launch(["/bin/true"], invocation_id=_invocation_id()) as inv:
        record = inv.containment_record()
    for key in (
        "invocation_id",
        "pgid",
        "pid",
        "rlimits_applied",
        "launch_ts",
        "sigterm_ts",
        "sigkill_ts",
        "survivor_scan",
        "reap_status",
        "drain_status",
        "attestation",
    ):
        assert key in record, f"record missing {key}"
    attestation = record["attestation"]
    assert attestation["venue"] == "process-group"
    assert attestation["cgroup_delegation"] == "unavailable"
    not_claimed = " ".join(attestation["guarantees_not_claimed"]).lower()
    assert "clone3" in not_claimed
    assert "cgroup.events" in not_claimed or "populated" in not_claimed
    assert "cgroup.kill" in not_claimed
    assert attestation["guarantees_not_claimed"] == list(GUARANTEES_NOT_CLAIMED)
    assert len(attestation["guarantees_claimed"]) > 0
    assert record["invocation_id"].startswith("test-")
    assert record["pgid"] == record["pid"]


@requires_posix_proc
def test_exit_runs_terminate_then_reap_then_drain_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    # Patch on the class: instances use __slots__, so per-instance
    # assignment is (correctly) refused.
    monkeypatch.setattr(
        InvocationProcessGroup, "terminate", lambda self, *a, **k: calls.append("terminate")
    )
    monkeypatch.setattr(
        InvocationProcessGroup, "reap", lambda self, *a, **k: calls.append("reap")
    )
    monkeypatch.setattr(
        InvocationProcessGroup, "drain", lambda self, *a, **k: calls.append("drain")
    )
    inv = InvocationProcessGroup.launch(["/bin/true"], invocation_id=_invocation_id())
    try:
        inv.__exit__(None, None, None)
        assert calls == ["terminate", "reap", "drain"]
    finally:
        # The stubbed __exit__ never terminated the real child: clean it up.
        try:
            os.kill(inv.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(inv.pid, 0)
        except ChildProcessError:
            pass


@requires_posix_proc
def test_no_cgroup_filesystem_access_during_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lighter variant must never touch the cgroup filesystem at all."""
    real_open = open

    def _guarded_open(path: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if isinstance(path, (str, os.PathLike)) and "cgroup" in os.fspath(path):
            raise AssertionError(f"cgroup filesystem access attempted: {path}")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _guarded_open)
    script = "import subprocess, time\nsubprocess.Popen(['/bin/sleep', '2'])\n"
    with InvocationProcessGroup.launch(
        [sys.executable, "-c", script], invocation_id=_invocation_id()
    ) as inv:
        inv.terminate(grace_seconds=2.0)
        record = inv.containment_record()
    assert record["survivor_scan"] == 0


@requires_posix_proc
def test_error_hierarchy_is_typed() -> None:
    for exc in (
        ProcessGroupPreflightError,
        ProcessGroupLaunchError,
        ProcessGroupTerminateError,
        ProcessGroupSurvivorError,
        ProcessGroupReapError,
    ):
        assert issubclass(exc, ProcessGroupContainmentError)
    assert issubclass(ProcessGroupContainmentError, RuntimeError)
    # The unused import of the preflight error keeps the hierarchy honest:
    assert ProcessGroupPreflightError.__name__ == "ProcessGroupPreflightError"
