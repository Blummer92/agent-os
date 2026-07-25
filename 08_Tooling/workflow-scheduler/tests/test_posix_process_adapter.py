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
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(SCHEDULER_SRC) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SRC))

from workflow_scheduler.execution import posix_process_adapter as adapter_module  # noqa: E402
from workflow_scheduler.execution.posix_process_adapter import (  # noqa: E402
    MAX_ARGUMENT_BYTES,
    MAX_ARGV_ITEMS,
    MAX_COMMAND_BYTES,
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
