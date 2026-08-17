"""Tests for the WSC5B2A bounded POSIX process adapter.

All child processes are the current Python interpreter (``sys.executable``)
invoked with small, deterministic ``-c`` scripts. No arbitrary sleeps are
used for synchronization; timeouts/grace periods are small but real, because
exercising the timeout/escalation machinery inherently requires a live
process and a bounded wait -- never a bare ``time.sleep()`` standing in for
test coordination.
"""

from __future__ import annotations

import ast
import inspect
import os
import signal
import subprocess
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

from workflow_scheduler.execution import cgroup_v2_containment  # noqa: E402
from workflow_scheduler.execution import posix_process_adapter as adapter_module  # noqa: E402
from workflow_scheduler.execution.posix_process_adapter import (  # noqa: E402
    MAX_ARGUMENT_BYTES,
    MAX_ARGV_ITEMS,
    MAX_COMMAND_BYTES,
    ContainmentConfig,
    PosixProcessAdapterError,
    PosixProcessExecutor,
    PosixProcessExecutorConfig,
    run_bounded_posix_process,
)
from workflow_scheduler.execution.single_issue_pilot import (  # noqa: E402
    PilotExecutionObservation,
    PilotExecutionRequest,
    PilotExecutor,
)

MODULE_PATH = SCHEDULER_SRC / "workflow_scheduler" / "execution" / "posix_process_adapter.py"

PY = sys.executable


def _request(**changes: object) -> PilotExecutionRequest:
    values: dict[str, object] = {
        "invocation_id": "invocation-594",
        "repository": "Blummer92/agent-os",
        "issue_number": 594,
        "branch": "agent/594-posix-process-adapter",
        "workspace_identity": "workspace-594",
        "source_head_sha": "a" * 40,
        "allowed_files": (),
        "forbidden_paths": (),
        "required_tests": (),
    }
    values.update(changes)
    return PilotExecutionRequest(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Argv rejection before spawn
# --------------------------------------------------------------------------


def _assert_never_spawns(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("subprocess.Popen must not be called for rejected input")

    monkeypatch.setattr(adapter_module.subprocess, "Popen", _fail_if_called)


def test_rejects_string_argv_before_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_never_spawns(monkeypatch)
    with pytest.raises(PosixProcessAdapterError):
        run_bounded_posix_process("echo hi")  # type: ignore[arg-type]


def test_rejects_empty_argv_before_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_never_spawns(monkeypatch)
    with pytest.raises(PosixProcessAdapterError):
        run_bounded_posix_process([])


def test_rejects_nul_byte_in_argument_before_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_never_spawns(monkeypatch)
    with pytest.raises(PosixProcessAdapterError):
        run_bounded_posix_process([PY, "-c", "print(1)\x00"])


def test_rejects_excessive_argument_count_before_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_never_spawns(monkeypatch)
    with pytest.raises(PosixProcessAdapterError):
        run_bounded_posix_process(["arg"] * (MAX_ARGV_ITEMS + 1))


def test_rejects_oversized_single_argument_before_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_never_spawns(monkeypatch)
    with pytest.raises(PosixProcessAdapterError):
        run_bounded_posix_process([PY, "x" * (MAX_ARGUMENT_BYTES + 1)])


def test_rejects_oversized_aggregate_command_before_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_never_spawns(monkeypatch)
    per_arg = MAX_ARGUMENT_BYTES  # each individually legal
    count = (MAX_COMMAND_BYTES // per_arg) + 2  # aggregate now illegal
    with pytest.raises(PosixProcessAdapterError):
        run_bounded_posix_process(["x" * per_arg for _ in range(count)])


def test_rejects_non_posix_runtime_before_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter_module, "POSIX_SUPPORTED", False)
    _assert_never_spawns(monkeypatch)
    with pytest.raises(PosixProcessAdapterError):
        run_bounded_posix_process([PY, "-c", "print(1)"])


def test_config_rejects_bad_argv_at_construction_time() -> None:
    with pytest.raises(PosixProcessAdapterError):
        PosixProcessExecutorConfig(argv=())


# --------------------------------------------------------------------------
# Ordinary completion
# --------------------------------------------------------------------------


def test_ordinary_completion_returns_final_return_code() -> None:
    result = run_bounded_posix_process([PY, "-c", "import sys; sys.exit(7)"])
    assert result.started is True
    assert result.return_code == 7
    assert result.termination_confirmed is True
    assert result.possible_partial_effects is False
    assert result.timeout_observed is False
    assert result.cancellation_requested is False


def test_successful_completion_return_code_zero() -> None:
    result = run_bounded_posix_process([PY, "-c", "print('hello')"])
    assert result.return_code == 0
    assert result.stdout_text == "hello\n"
    assert result.termination_confirmed is True


# --------------------------------------------------------------------------
# Concurrent bounded stdout/stderr draining
# --------------------------------------------------------------------------


def test_large_concurrent_stdout_and_stderr_do_not_deadlock() -> None:
    script = (
        "import sys\n"
        "sys.stdout.write('A' * 200000)\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('B' * 200000)\n"
        "sys.stderr.flush()\n"
    )
    started = time.monotonic()
    result = run_bounded_posix_process(
        [PY, "-c", script], timeout_seconds=10.0, max_output_bytes=4096
    )
    elapsed = time.monotonic() - started

    assert result.termination_confirmed is True
    assert result.return_code == 0
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert len(result.stdout_text) <= 4096
    assert len(result.stderr_text) <= 4096
    # No pipe deadlock: this completes in well under the 10s timeout.
    assert elapsed < 5.0


def test_explicit_output_truncation_retains_bounded_head_and_tail() -> None:
    max_bytes = 64
    script = f"import sys; sys.stdout.write('x' * {max_bytes + 1})"
    result = run_bounded_posix_process([PY, "-c", script], max_output_bytes=max_bytes)
    assert result.stdout_truncated is True
    assert len(result.stdout_text) <= max_bytes


def test_output_within_bound_is_not_marked_truncated() -> None:
    result = run_bounded_posix_process(
        [PY, "-c", "import sys; sys.stdout.write('x' * 10)"], max_output_bytes=4096
    )
    assert result.stdout_truncated is False
    assert result.stdout_text == "x" * 10


# --------------------------------------------------------------------------
# Timeout with graceful process-group termination
# --------------------------------------------------------------------------


def test_timeout_with_live_child_sends_sigterm_and_confirms_exit() -> None:
    result = run_bounded_posix_process(
        [PY, "-c", "import time; time.sleep(30)"],
        timeout_seconds=0.2,
        grace_period_seconds=1.0,
    )
    assert result.timeout_observed is True
    assert result.signal_dispatched == "SIGTERM"
    assert result.escalation_dispatched is False
    assert result.child_exit_observed is True
    assert result.communication_completed is True
    assert result.termination_confirmed is True
    assert result.return_code == -signal.SIGTERM.value


# --------------------------------------------------------------------------
# Forced escalation
# --------------------------------------------------------------------------


def test_child_ignoring_sigterm_requires_escalation_to_sigkill() -> None:
    script = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(30)\n"
    )
    result = run_bounded_posix_process(
        [PY, "-c", script], timeout_seconds=0.2, grace_period_seconds=0.3
    )
    assert result.timeout_observed is True
    assert result.signal_dispatched == "SIGTERM"
    assert result.escalation_dispatched is True
    assert result.termination_confirmed is True
    assert result.return_code == -signal.SIGKILL.value


# --------------------------------------------------------------------------
# Process-group signaling targets the group, not just the direct child
# --------------------------------------------------------------------------


def test_timeout_signals_target_the_process_group_not_a_single_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_killpg = os.killpg
    calls: list[tuple[int, int]] = []

    def spy(pgid: int, sig: int) -> None:
        calls.append((pgid, sig))
        real_killpg(pgid, sig)

    monkeypatch.setattr(adapter_module.os, "killpg", spy)

    result = run_bounded_posix_process(
        [PY, "-c", "import time; time.sleep(30)"],
        timeout_seconds=0.2,
        grace_period_seconds=0.5,
    )

    assert result.termination_confirmed is True
    assert len(calls) == 1
    pgid, sig = calls[0]
    assert sig == signal.SIGTERM
    # A process group id is used (os.killpg), which also reaches any
    # descendant that inherited this same group -- not just the direct
    # child's own pid via a plain os.kill.
    assert pgid > 0


# --------------------------------------------------------------------------
# Cancellation is distinct from termination confirmation
# --------------------------------------------------------------------------


def test_cancellation_request_is_distinct_from_termination_confirmed() -> None:
    result = run_bounded_posix_process(
        [PY, "-c", "import time; time.sleep(30)"],
        timeout_seconds=30.0,
        grace_period_seconds=1.0,
        cancelled=lambda: True,
    )
    assert result.cancellation_requested is True
    assert result.timeout_observed is False
    # Cancellation and confirmed termination are tracked as separate facts;
    # the group signal still ran and the child's exit was still confirmed.
    assert result.termination_confirmed is True
    assert result.signal_dispatched == "SIGTERM"


# --------------------------------------------------------------------------
# Final communication after timeout/escalation
# --------------------------------------------------------------------------


def test_output_emitted_before_timeout_is_preserved_after_termination() -> None:
    script = "import sys, time; print('before-timeout'); sys.stdout.flush(); time.sleep(30)"
    result = run_bounded_posix_process(
        [PY, "-c", script], timeout_seconds=0.2, grace_period_seconds=0.5
    )
    assert result.termination_confirmed is True
    assert "before-timeout" in result.stdout_text


# --------------------------------------------------------------------------
# Child reaping
# --------------------------------------------------------------------------


def test_child_process_is_fully_reaped_after_completion() -> None:
    script = "import os; print(os.getpid())"
    result = run_bounded_posix_process([PY, "-c", script])
    pid = int(result.stdout_text.strip())
    with pytest.raises(ProcessLookupError):
        # A reaped process no longer exists in the process table at all
        # (unlike an un-reaped zombie, which would still answer signal 0).
        os.kill(pid, 0)


def test_child_process_is_reaped_after_timeout_and_termination() -> None:
    # stdout must be explicitly flushed: Python block-buffers stdout when it
    # is a pipe (not a TTY), and a SIGTERM/SIGKILL termination bypasses the
    # normal interpreter shutdown that would otherwise flush it. Without an
    # explicit flush before the sleep, the pid text can be silently lost
    # instead of ever reaching the pipe -- a real, platform-dependent
    # ordering hazard, not a bounded timing assumption.
    script = "import os, time; print(os.getpid()); import sys; sys.stdout.flush(); time.sleep(30)"
    result = run_bounded_posix_process(
        [PY, "-c", script], timeout_seconds=0.2, grace_period_seconds=0.5
    )
    pid = int(result.stdout_text.strip())
    assert result.termination_confirmed is True
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


# --------------------------------------------------------------------------
# PosixProcessExecutor: PilotExecutor protocol conformance
# --------------------------------------------------------------------------


def test_executor_satisfies_the_pilot_executor_protocol() -> None:
    config = PosixProcessExecutorConfig(argv=(PY, "-c", "print(1)"))
    executor = PosixProcessExecutor(config)
    assert isinstance(executor, PilotExecutor)


def test_executor_runs_at_most_once() -> None:
    config = PosixProcessExecutorConfig(argv=(PY, "-c", "print(1)"))
    executor = PosixProcessExecutor(config)
    observation = executor.run(_request())
    assert isinstance(observation, PilotExecutionObservation)
    with pytest.raises(RuntimeError):
        executor.run(_request())


def test_executor_rejects_wrong_request_type() -> None:
    config = PosixProcessExecutorConfig(argv=(PY, "-c", "print(1)"))
    executor = PosixProcessExecutor(config)
    with pytest.raises(TypeError):
        executor.run("not-a-request")  # type: ignore[arg-type]


def test_executor_maps_successful_result_onto_observation() -> None:
    config = PosixProcessExecutorConfig(argv=(PY, "-c", "import sys; sys.exit(0)"))
    executor = PosixProcessExecutor(config)
    observation = executor.run(_request())
    assert observation.outcome == "succeeded"
    assert observation.started is True
    assert observation.termination_confirmed is True
    assert observation.possible_partial_effects is False
    assert observation.changed_paths == ()
    assert executor.last_result is not None
    assert executor.last_result.return_code == 0


def test_executor_maps_timeout_result_onto_observation() -> None:
    config = PosixProcessExecutorConfig(
        argv=(PY, "-c", "import time; time.sleep(30)"),
        timeout_seconds=0.2,
        grace_period_seconds=0.5,
    )
    executor = PosixProcessExecutor(config)
    observation = executor.run(_request())
    assert observation.outcome == "timed-out"
    assert observation.termination_confirmed is True


# --------------------------------------------------------------------------
# No shell interpolation
# --------------------------------------------------------------------------


def test_source_never_uses_shell_true_or_preexec_fn() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "preexec_fn" not in source
    assert "shell=False" in source


# --------------------------------------------------------------------------
# Architecture boundary: no retry/worktree/lease/persistence/GitHub/network
# --------------------------------------------------------------------------


_FORBIDDEN_IMPORT_ROOTS = (
    "socket",
    "urllib",
    "http",
    "requests",
    "sqlite3",
    "threading",
    "multiprocessing",
    "asyncio",
    "queue",
    "shutil",
)

_FORBIDDEN_MODULE_SUBSTRINGS = (
    "in_memory_lease_adapter",
    "quarantine_review",
    "request_dispatch",
    "retry_manager",
    "execution.executor",
    "github",
    "workflow_dispatch",
)


def test_module_imports_no_retry_worktree_lease_persistence_or_network_authority() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    for module_name in imported_modules:
        root = module_name.split(".")[0]
        assert root not in _FORBIDDEN_IMPORT_ROOTS, f"forbidden import root: {module_name}"
        lowered = module_name.lower()
        for forbidden in _FORBIDDEN_MODULE_SUBSTRINGS:
            assert forbidden not in lowered, f"forbidden import: {module_name}"


def test_module_defines_no_network_or_persistence_calls() -> None:
    source = inspect.getsource(adapter_module)
    for forbidden_token in ("socket.", "sqlite3.", "requests.", "urllib.", "os.system("):
        assert forbidden_token not in source


def test_module_never_retries_execution() -> None:
    source = inspect.getsource(adapter_module)
    for forbidden_token in ("RetryManager", "retry_attempt", "max_retries", "backoff"):
        assert forbidden_token not in source


# --------------------------------------------------------------------------
# WSC-AUTO1C: opt-in cgroup v2 containment
#
# Real launches are gated on the real preflight probe (not a blanket
# platform check) so this suite still runs, and still proves the
# fail-closed path, on a host where the native extension is not built or
# clone3()/cgroup v2 delegation is unavailable.
# --------------------------------------------------------------------------


def _discover_cgroup2_mount() -> str | None:
    for candidate in ("/sys/fs/cgroup", "/sys/fs/cgroup/unified"):
        if os.path.isfile(os.path.join(candidate, "cgroup.controllers")):
            return candidate
    return None


def _real_containment_supported() -> bool:
    root = _discover_cgroup2_mount()
    if root is None:
        return False
    return cgroup_v2_containment.preflight_check(root).supported


requires_real_containment = pytest.mark.skipif(
    not _real_containment_supported(),
    reason="real cgroup v2 delegation/clone3 support not available on this host",
)


@pytest.fixture()
def delegated_parent() -> str | None:
    root = _discover_cgroup2_mount()
    if root is None:
        yield None
        return
    path = os.path.join(root, f"agentos-adapter-test-{uuid.uuid4().hex}")
    try:
        os.mkdir(path)
    except OSError:
        yield None
        return
    yield path
    try:
        os.rmdir(path)
    except OSError:
        pass


def _containment(delegated_parent_path: str) -> ContainmentConfig:
    return ContainmentConfig(
        delegated_parent_cgroup=delegated_parent_path,
        invocation_id=str(uuid.uuid4()),
    )


def test_containment_config_rejects_empty_delegated_parent() -> None:
    with pytest.raises(PosixProcessAdapterError):
        ContainmentConfig(delegated_parent_cgroup="", invocation_id="x")


def test_containment_config_rejects_empty_invocation_id() -> None:
    with pytest.raises(PosixProcessAdapterError):
        ContainmentConfig(delegated_parent_cgroup="/sys/fs/cgroup", invocation_id="")


def test_uncontained_default_path_is_unaffected_by_containment_fields() -> None:
    result = run_bounded_posix_process([PY, "-c", "print(1)"])
    assert result.contained is False
    assert result.invocation_cgroup_path is None
    assert result.populated_confirmed_clear is None
    assert result.cleanup_confirmed is None


def test_preflight_failure_raises_before_any_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        adapter_module.cgroup_v2_containment,
        "preflight_check",
        lambda *_a, **_k: cgroup_v2_containment.ContainmentPreflightResult(
            supported=False,
            delegated_parent_cgroup="/no/such/path",
            cgroup_v2_mounted=False,
            delegated_parent_exists=False,
            can_create_and_remove_child=False,
            clone3_extension_loaded=False,
            clone3_syscall_supported=False,
            cgroup_events_readable=False,
            cgroup_kill_writable=False,
            reason="simulated unsupported host",
        ),
    )

    def _fail_if_called(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("no launch may be attempted after a failed preflight")

    monkeypatch.setattr(adapter_module, "launch_into_cgroup", _fail_if_called)

    with pytest.raises(cgroup_v2_containment.CgroupV2PreflightError):
        run_bounded_posix_process(
            [PY, "-c", "print(1)"],
            containment=ContainmentConfig(
                delegated_parent_cgroup="/no/such/path", invocation_id="x"
            ),
        )
    assert calls == []


@requires_real_containment
def test_contained_ordinary_completion(delegated_parent: str) -> None:
    result = run_bounded_posix_process(
        [PY, "-c", "print('hello')"], containment=_containment(delegated_parent)
    )
    assert result.contained is True
    assert result.started is True
    assert result.return_code == 0
    assert result.stdout_text == "hello\n"
    assert result.termination_confirmed is True
    assert result.possible_partial_effects is False
    assert result.populated_confirmed_clear is True
    assert result.cleanup_confirmed is True
    assert not os.path.exists(result.invocation_cgroup_path)


@requires_real_containment
def test_contained_argv_cwd_env_stdin_stdout_stderr_compatibility(
    tmp_path: Path, delegated_parent: str
) -> None:
    script = (
        "import os, sys\n"
        "print(os.getcwd())\n"
        "print(os.environ.get('AGENTOS_TEST_VAR'))\n"
        "print(sys.stdin.read() == '')\n"
    )
    result = run_bounded_posix_process(
        [PY, "-c", script],
        cwd=str(tmp_path),
        env={"AGENTOS_TEST_VAR": "contained-value", "PATH": os.environ.get("PATH", "")},
        containment=_containment(delegated_parent),
    )
    lines = result.stdout_text.splitlines()
    assert lines[0] == str(tmp_path)
    assert lines[1] == "contained-value"
    assert lines[2] == "True"  # stdin was /dev/null: empty read
    assert result.termination_confirmed is True


@requires_real_containment
def test_contained_child_reports_its_own_cgroup_path(delegated_parent: str) -> None:
    result = run_bounded_posix_process(
        [PY, "-c", "print(open('/proc/self/cgroup').read(), end='')"],
        containment=_containment(delegated_parent),
    )
    expected_suffix = os.path.basename(result.invocation_cgroup_path)
    assert result.stdout_text.strip().endswith(expected_suffix)
    assert "0::/" in result.stdout_text


@requires_real_containment
def test_contained_deterministic_exec_failure_does_not_hang(delegated_parent: str) -> None:
    started = time.monotonic()
    result = run_bounded_posix_process(
        ["/no/such/binary-adapter-test"],
        timeout_seconds=5.0,
        containment=_containment(delegated_parent),
    )
    elapsed = time.monotonic() - started
    assert elapsed < 5.0
    assert result.exec_failure_phase == "execve"
    assert result.exec_failure_errno == 2


@requires_real_containment
def test_contained_child_and_grandchild_success(delegated_parent: str) -> None:
    script = (
        "import os\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    os._exit(0)\n"
        "else:\n"
        "    os.waitpid(pid, 0)\n"
        "    print('parent-and-child-done')\n"
    )
    result = run_bounded_posix_process(
        [PY, "-c", script], containment=_containment(delegated_parent)
    )
    assert "parent-and-child-done" in result.stdout_text
    assert result.termination_confirmed is True


@requires_real_containment
def test_contained_surviving_descendant_still_proven_and_cleaned_up(delegated_parent: str) -> None:
    # The direct child ignores SIGTERM and forks a grandchild that also
    # ignores SIGTERM and outlives it; containment must still prove/clean
    # up the whole subtree via cgroup.kill, not just the direct child.
    script = (
        "import signal, os, time, sys\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(30)\n"
        "    os._exit(0)\n"
        "else:\n"
        "    print(pid)\n"
        "    sys.stdout.flush()\n"
        "    time.sleep(30)\n"
    )
    result = run_bounded_posix_process(
        [PY, "-c", script],
        timeout_seconds=0.3,
        grace_period_seconds=0.5,
        containment=_containment(delegated_parent),
    )
    assert result.timeout_observed is True
    assert result.signal_dispatched == "SIGTERM"
    assert result.cgroup_kill_dispatched is True
    assert result.termination_confirmed is True
    assert result.populated_confirmed_clear is True
    assert result.cleanup_confirmed is True


@requires_real_containment
def test_contained_process_group_escape_via_setsid_still_contained(delegated_parent: str) -> None:
    # The child calls setsid() to leave its process group; process-group
    # SIGTERM will not reach it, so termination must fall through to
    # cgroup.kill and still prove/clean up the whole subtree.
    # The clone3 launcher already made this child its own session/group
    # leader (matching subprocess's start_new_session=True); a second
    # setsid() call here is the child's own escape attempt and normally
    # fails with EPERM precisely because it is already a leader -- which
    # is itself evidence the escape did not create a second, signal-blind
    # process group. Either way SIGTERM is ignored, so containment must
    # still fall through to cgroup.kill.
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "try:\n"
        "    os.setsid()\n"
        "except OSError:\n"
        "    pass\n"
        "time.sleep(30)\n"
    )
    result = run_bounded_posix_process(
        [PY, "-c", script],
        timeout_seconds=0.3,
        grace_period_seconds=0.5,
        containment=_containment(delegated_parent),
    )
    assert result.timeout_observed is True
    assert result.cgroup_kill_dispatched is True
    assert result.termination_confirmed is True
    assert result.populated_confirmed_clear is True
    assert result.cleanup_confirmed is True


@requires_real_containment
def test_contained_descendant_holding_pipe_open_does_not_hang_drain(delegated_parent: str) -> None:
    script = (
        "import os, sys, time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    time.sleep(30)\n"  # keeps stdout fd open long after the parent exits
        "    os._exit(0)\n"
        "else:\n"
        "    print('parent-done')\n"
    )
    started = time.monotonic()
    result = run_bounded_posix_process(
        [PY, "-c", script],
        timeout_seconds=2.0,
        grace_period_seconds=0.3,
        containment=_containment(delegated_parent),
    )
    elapsed = time.monotonic() - started
    assert elapsed < 10.0
    assert "parent-done" in result.stdout_text


@requires_real_containment
def test_contained_exactly_one_spawn_no_retry(delegated_parent: str) -> None:
    marker = str(uuid.uuid4())
    script = f"print('{marker}')"
    result = run_bounded_posix_process([PY, "-c", script], containment=_containment(delegated_parent))
    assert result.stdout_text.count(marker) == 1


@requires_real_containment
def test_contained_pid_reuse_diagnostics_are_distinct_across_runs(delegated_parent: str) -> None:
    result_a = run_bounded_posix_process(
        [PY, "-c", "print(1)"], containment=_containment(delegated_parent)
    )
    result_b = run_bounded_posix_process(
        [PY, "-c", "print(2)"], containment=_containment(delegated_parent)
    )
    assert result_a.pid is not None
    assert result_b.pid is not None
    assert result_a.invocation_cgroup_path != result_b.invocation_cgroup_path


def test_executor_config_threads_containment_through(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def _fake_run(*args: object, **kwargs: object) -> object:
        seen["containment"] = kwargs.get("containment")
        return adapter_module.PosixProcessExecutionResult(
            started=True,
            timeout_observed=False,
            cancellation_requested=False,
            signal_dispatched=None,
            escalation_dispatched=False,
            child_exit_observed=True,
            communication_completed=True,
            return_code=0,
            stdout_text="",
            stdout_truncated=False,
            stderr_text="",
            stderr_truncated=False,
            termination_confirmed=True,
            possible_partial_effects=False,
        )

    monkeypatch.setattr(adapter_module, "run_bounded_posix_process", _fake_run)
    containment = ContainmentConfig(delegated_parent_cgroup="/sys/fs/cgroup", invocation_id="x")
    config = PosixProcessExecutorConfig(argv=(PY, "-c", "print(1)"), containment=containment)
    executor = PosixProcessExecutor(config)
    executor.run(_request())
    assert seen["containment"] is containment


def test_containment_module_exposes_no_shell_network_or_persistence_surface() -> None:
    import inspect as _inspect

    from workflow_scheduler.execution import cgroup_v2_containment as cgroup_module

    source = _inspect.getsource(cgroup_module)
    tree = ast.parse(source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
    for module_name in imported_modules:
        root = module_name.split(".")[0]
        assert root not in _FORBIDDEN_IMPORT_ROOTS, f"forbidden import: {module_name}"


# --------------------------------------------------------------------------
# AOS-LEASE1 (#1202): contained termination evidence for lease recovery
#
# The proof definition stays owned here (#759). These tests pin it to the same
# conditions ``termination_confirmed`` already requires, so a weaker generic
# process check can never be substituted downstream.
# --------------------------------------------------------------------------


def _contained_result(**overrides):
    base = dict(
        started=True,
        timeout_observed=False,
        cancellation_requested=False,
        signal_dispatched=None,
        escalation_dispatched=False,
        child_exit_observed=True,
        communication_completed=True,
        return_code=0,
        stdout_text="",
        stdout_truncated=False,
        stderr_text="",
        stderr_truncated=False,
        termination_confirmed=True,
        possible_partial_effects=False,
        contained=True,
        invocation_cgroup_path="/sys/fs/cgroup/agent-os/inv-1",
        cgroup_kill_dispatched=False,
        populated_confirmed_clear=True,
        cleanup_confirmed=True,
    )
    base.update(overrides)
    return adapter_module.PosixProcessExecutionResult(**base)


def test_lease1_contained_evidence_matches_termination_confirmed_exactly() -> None:
    result = _contained_result()
    evidence = adapter_module.contained_termination_evidence(result)

    assert evidence.termination_proven is True
    assert evidence.termination_proven == result.termination_confirmed
    assert evidence.invocation_cgroup_path == result.invocation_cgroup_path


@pytest.mark.parametrize(
    "overrides",
    [
        {"child_exit_observed": False},
        {"communication_completed": False},
        {"return_code": None},
        {"populated_confirmed_clear": False},
        {"populated_confirmed_clear": None},
        {"cleanup_confirmed": False},
        {"cleanup_confirmed": None},
    ],
)
def test_lease1_any_missing_containment_fact_defeats_the_proof(overrides) -> None:
    """Reap, drain, recursive populated=0, and exact cleanup are all required."""
    result = _contained_result(termination_confirmed=False, **overrides)

    assert adapter_module.contained_termination_evidence(result).termination_proven is False


def test_lease1_uncontained_execution_cannot_produce_containment_evidence() -> None:
    """An uncontained attempt has no recursive-emptiness proof to project."""
    uncontained = _contained_result(
        contained=False,
        invocation_cgroup_path=None,
        populated_confirmed_clear=None,
        cleanup_confirmed=None,
    )

    with pytest.raises(PosixProcessAdapterError):
        adapter_module.contained_termination_evidence(uncontained)


def test_lease1_termination_evidence_rejects_malformed_bindings() -> None:
    with pytest.raises(PosixProcessAdapterError):
        adapter_module.ContainedTerminationEvidence(
            invocation_cgroup_path="",
            contained=True,
            child_exit_observed=True,
            communication_completed=True,
            return_code=0,
            populated_confirmed_clear=True,
            cleanup_confirmed=True,
        )
    with pytest.raises(PosixProcessAdapterError):
        adapter_module.ContainedTerminationEvidence(
            invocation_cgroup_path="/sys/fs/cgroup/agent-os/inv-1",
            contained="yes",
            child_exit_observed=True,
            communication_completed=True,
            return_code=0,
            populated_confirmed_clear=True,
            cleanup_confirmed=True,
        )
    with pytest.raises(PosixProcessAdapterError):
        adapter_module.contained_termination_evidence(object())


def test_lease1_containment_proof_keeps_a_single_definition() -> None:
    """The recovery proof must not drift from the executor's own proof.

    Rather than pinning source text, this cross-checks the two definitions
    against each other over every combination of the containment facts.
    """
    import itertools

    for combo in itertools.product([True, False], repeat=4):
        child_exit, drain, populated, cleanup = combo
        result = _contained_result(
            child_exit_observed=child_exit,
            communication_completed=drain,
            populated_confirmed_clear=populated,
            cleanup_confirmed=cleanup,
            termination_confirmed=all(combo),
        )
        evidence = adapter_module.contained_termination_evidence(result)
        assert evidence.termination_proven == result.termination_confirmed == all(combo)

    # A missing return code defeats the proof on both sides as well.
    no_rc = _contained_result(return_code=None, termination_confirmed=False)
    assert adapter_module.contained_termination_evidence(no_rc).termination_proven is False
