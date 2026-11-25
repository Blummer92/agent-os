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
import resource
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


def test_source_never_uses_shell_true_and_preexec_fn_only_for_rlimits() -> None:
    # The #3316 migration intentionally added preexec_fn: it exists solely
    # to lower rlimits in the forked child before exec. Pin that contract
    # instead of the old never-preexec_fn invariant.
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "shell=False" in source
    tree = ast.parse(source)
    preexec_sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "preexec_fn":
                    preexec_sites.append(ast.dump(keyword.value))
    assert len(preexec_sites) == 1, f"expected one preexec_fn wiring, found {len(preexec_sites)}"
    assert "_apply_rlimits_in_child" in preexec_sites[0], (
        "preexec_fn must only ever lower rlimits in the forked child"
    )


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


def test_uncontained_default_path_is_unaffected_by_containment_fields() -> None:
    result = run_bounded_posix_process([PY, "-c", "print(1)"])
    assert result.contained is False
    assert result.invocation_cgroup_path is None
    assert result.populated_confirmed_clear is None
    assert result.cleanup_confirmed is None


# --------------------------------------------------------------------------
# AOS-LEASE1 (#1202): contained termination evidence for lease recovery
#
# The proof definition stays owned here (retained when #759 containment was
# removed under #3101 invasive, for the host-local lease recovery contract).
# These tests pin it to the same conditions ``termination_confirmed`` already
# requires, so a weaker generic process check can never be substituted downstream.
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


# --------------------------------------------------------------------------
# Migrated containment guarantees (#3316)
#
# Behavioral coverage ported from test_process_group_containment.py:
# rlimit validation and enforcement, the /proc survivor scan with its
# fail-closed error, the venue attestation, the preflight probe, and the
# compact framed evidence projection. Implementation-shape tests tied to
# InvocationProcessGroup's class API were intentionally not ported.
# --------------------------------------------------------------------------

requires_posix_proc = pytest.mark.skipif(
    os.name != "posix" or not os.path.isdir("/proc"),
    reason="migrated containment tests need a POSIX host with /proc",
)


def _pid_alive(pid: int) -> bool:
    """True only if the pid exists and is not a zombie."""
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
# Rlimits: validated before spawn, actually applied in the child
# --------------------------------------------------------------------------


def test_migrated_rejects_unknown_rlimit_key_before_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_never_spawns(monkeypatch)
    with pytest.raises(PosixProcessAdapterError):
        run_bounded_posix_process(
            [PY, "-c", "pass"], rlimits={"RLIMIT_NO_SUCH_LIMIT": (1, 1)}
        )


def test_migrated_rejects_malformed_rlimit_bounds_before_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_never_spawns(monkeypatch)
    with pytest.raises(PosixProcessAdapterError):
        run_bounded_posix_process([PY, "-c", "pass"], rlimits={"RLIMIT_NPROC": (1,)})
    _assert_never_spawns(monkeypatch)
    with pytest.raises(PosixProcessAdapterError):
        run_bounded_posix_process([PY, "-c", "pass"], rlimits={"RLIMIT_NPROC": (1, -2)})
    _assert_never_spawns(monkeypatch)
    with pytest.raises(PosixProcessAdapterError):
        run_bounded_posix_process([PY, "-c", "pass"], rlimits={"RLIMIT_NPROC": (True, 1)})


def test_migrated_config_rejects_bad_rlimits_at_construction() -> None:
    with pytest.raises(PosixProcessAdapterError):
        PosixProcessExecutorConfig(
            argv=(PY, "-c", "pass"), rlimits={"RLIMIT_NO_SUCH_LIMIT": (1, 1)}
        )


def test_migrated_no_rlimits_by_default() -> None:
    result = run_bounded_posix_process([PY, "-c", "pass"])
    assert result.rlimits_applied is None


@requires_posix_proc
def test_migrated_rlimit_cpu_kills_a_spinner() -> None:
    """A tight RLIMIT_CPU must kill a CPU spinner via the kernel itself."""
    script = "while True:\n    pass\n"
    result = run_bounded_posix_process(
        [PY, "-c", script],
        rlimits={"RLIMIT_CPU": (1, 1)},
        timeout_seconds=30.0,
    )
    assert result.rlimits_applied == {"RLIMIT_CPU": [1, 1]}
    assert result.timeout_observed is False  # the kernel killed it, not our timeout
    assert result.return_code is not None and result.return_code < 0  # signaled
    assert result.termination_confirmed is True


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
def test_migrated_rlimit_nproc_caps_fork(tmp_path: Path) -> None:
    """RLIMIT_NPROC must cap how many grandchildren the child can fork."""
    limit = _uid_thread_count() + 10
    result_file = tmp_path / "forks"
    script = (
        "import subprocess\n"
        "kids = []\n"
        "ok = 0\n"
        "for _ in range(30):\n"
        "    try:\n"
        "        kids.append(subprocess.Popen(['/bin/sleep', '30']))\n"
        "        ok += 1\n"
        "    except OSError:\n"
        "        break\n"
        f"open({str(result_file)!r}, 'w').write(str(ok))\n"
    )
    result = run_bounded_posix_process(
        [PY, "-c", script],
        rlimits={resource.RLIMIT_NPROC: (limit, limit)},
        timeout_seconds=8.0,
    )
    assert result.rlimits_applied == {"RLIMIT_NPROC": [limit, limit]}
    # The grandchildren hold our pipes open, so the timeout fires and the
    # whole pgid is SIGTERMed; SIGKILL escalation is never needed.
    assert result.timeout_observed is True
    assert result.escalation_dispatched is False
    assert result.termination_confirmed is True
    assert result.survivor_scan_performed is False
    assert result_file.exists(), "child never finished its fork loop"
    successful = int(result_file.read_text())
    assert 1 <= successful < 30


@requires_posix_proc
def test_migrated_rlimit_names_resolve_to_constants() -> None:
    result = run_bounded_posix_process(
        [PY, "-c", "pass"],
        rlimits={"RLIMIT_AS": (2**30, 2**30), resource.RLIMIT_FSIZE: (2**20, 2**20)},
    )
    assert result.rlimits_applied is not None
    assert result.rlimits_applied["RLIMIT_AS"] == [2**30, 2**30]
    assert result.rlimits_applied["RLIMIT_FSIZE"] == [2**20, 2**20]


def test_migrated_executor_applies_config_rlimits() -> None:
    config = PosixProcessExecutorConfig(
        argv=(PY, "-c", "pass"), rlimits={"RLIMIT_NOFILE": (64, 64)}
    )
    executor = PosixProcessExecutor(config)
    observation = executor.run(_request())
    assert observation.outcome == "succeeded"
    assert executor.last_result is not None
    assert executor.last_result.rlimits_applied == {"RLIMIT_NOFILE": [64, 64]}


# --------------------------------------------------------------------------
# Survivor scan: SIGTERM grace, SIGKILL escalation, fail-closed proof
# --------------------------------------------------------------------------


@requires_posix_proc
def test_migrated_graceful_sigterm_kills_a_multiprocess_group(tmp_path: Path) -> None:
    """Child spawns a grandchild; SIGTERM to the pgid must kill both."""
    grandchild_pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, time\n"
        "grandchild = subprocess.Popen(['/bin/sleep', '30'])\n"
        f"open({str(grandchild_pid_file)!r}, 'w').write(str(grandchild.pid))\n"
        "time.sleep(30)\n"
    )
    result = run_bounded_posix_process(
        [PY, "-c", script], timeout_seconds=3.0, grace_period_seconds=2.0
    )
    assert result.timeout_observed is True
    assert result.escalation_dispatched is False  # SIGTERM was enough
    assert result.survivor_scan_performed is False
    assert result.termination_confirmed is True
    grandchild_pid = int(grandchild_pid_file.read_text())
    assert not _pid_alive(grandchild_pid)


@requires_posix_proc
def test_migrated_sigkill_escalation_for_a_sigterm_ignorer() -> None:
    """A child that ignores SIGTERM must still die via the bounded escalation.

    No handshake is needed: the timeout itself guarantees the SIGTERM
    cannot race interpreter startup.
    """
    script = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(30)\n"
    )
    result = run_bounded_posix_process(
        [PY, "-c", script], timeout_seconds=2.0, grace_period_seconds=1.0
    )
    assert result.timeout_observed is True
    assert result.escalation_dispatched is True
    assert result.survivor_scan_performed is True
    assert result.survivor_count == 0
    assert result.termination_confirmed is True
    assert result.return_code == -signal.SIGKILL


@requires_posix_proc
def test_migrated_sigkill_escalation_reaches_a_lingering_grandchild(
    tmp_path: Path,
) -> None:
    """Child exits at once; a SIGTERM-ignoring grandchild must still die.

    The grandchild holds our pipes open, so the timeout fires with the
    direct child already gone; the SIGTERM grace finds the pgid still
    populated and the run must escalate to SIGKILL rather than declare
    victory.
    """
    grandchild_pid_file = tmp_path / "grandchild.pid"
    grandchild_code = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(30)\n"
    )
    script = (
        "import subprocess, sys\n"
        f"grandchild = subprocess.Popen([sys.executable, '-c', {grandchild_code!r}])\n"
        f"open({str(grandchild_pid_file)!r}, 'w').write(str(grandchild.pid))\n"
    )
    result = run_bounded_posix_process(
        [PY, "-c", script], timeout_seconds=2.0, grace_period_seconds=1.0
    )
    assert result.timeout_observed is True
    assert result.escalation_dispatched is True
    assert result.survivor_scan_performed is True
    assert result.survivor_count == 0
    assert result.termination_confirmed is True
    grandchild_pid = int(grandchild_pid_file.read_text())
    assert not _pid_alive(grandchild_pid)


def test_migrated_fail_closed_on_survivor(monkeypatch: pytest.MonkeyPatch) -> None:
    """A survivor after SIGKILL raises PosixProcessSurvivorError -- never ignored."""
    monkeypatch.setattr(adapter_module, "_pgid_live_survivors", lambda _pgid: [424242])
    script = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(30)\n"
    )
    with pytest.raises(adapter_module.PosixProcessSurvivorError) as excinfo:
        run_bounded_posix_process(
            [PY, "-c", script], timeout_seconds=1.0, grace_period_seconds=0.5
        )
    assert "424242" in str(excinfo.value)


def test_migrated_survivor_error_is_a_runtime_error_not_value_error() -> None:
    # A containment breach is a runtime failure, never a malformed-input
    # rejection: the ValueError-based PosixProcessAdapterError stays
    # pre-spawn-only by contract.
    assert issubclass(adapter_module.PosixProcessSurvivorError, RuntimeError)
    assert not issubclass(adapter_module.PosixProcessSurvivorError, ValueError)


# --------------------------------------------------------------------------
# Attestation: the result states what it does and does not claim
# --------------------------------------------------------------------------


@requires_posix_proc
def test_migrated_attestation_states_what_is_not_claimed() -> None:
    result = run_bounded_posix_process([PY, "-c", "pass"])
    assert result.containment_venue == "process-group"
    assert isinstance(result.cgroup_delegation_available, bool)
    assert result.guarantees_not_claimed == adapter_module.GUARANTEES_NOT_CLAIMED
    not_claimed = " ".join(result.guarantees_not_claimed or ()).lower()
    assert "clone3" in not_claimed
    assert "cgroup.events" in not_claimed or "populated" in not_claimed
    assert "cgroup.kill" in not_claimed
    assert len(result.guarantees_claimed or ()) > 0
    # A clean exit needs no escalation, so no scan runs -- and the result
    # says so honestly instead of implying one did.
    assert result.survivor_scan_performed is False
    assert result.survivor_count == 0


# --------------------------------------------------------------------------
# Preflight: fails closed, honest about cgroup delegation
# --------------------------------------------------------------------------


@requires_posix_proc
def test_migrated_preflight_usable_on_this_posix_host() -> None:
    result = adapter_module.posix_containment_preflight()
    assert result.usable is True
    assert result.setpgid_available is True
    assert result.rlimit_available is True
    assert result.reason == ""
    # An honest probe, not a gate: this field is a bool either way.
    assert isinstance(result.cgroup_delegation_available, bool)


def test_migrated_preflight_fails_closed_on_non_posix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Patch the module's _os_name seam, never the real os.name: pytest
    # itself calls pathlib.Path() while reporting results and Path
    # dispatches on os.name -- a patched "nt" crashes the session with
    # INTERNALERROR: cannot instantiate 'WindowsPath'.
    monkeypatch.setattr(adapter_module, "_os_name", lambda: "nt")
    result = adapter_module.posix_containment_preflight()
    assert result.usable is False
    assert result.setpgid_available is False
    assert result.reason != ""


def test_migrated_preflight_fails_closed_when_resource_module_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter_module, "_resource", None)
    result = adapter_module.posix_containment_preflight()
    assert result.usable is False
    assert result.rlimit_available is False
    assert "resource" in result.reason


def test_migrated_preflight_fails_closed_when_proc_unlistable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Patch the module's probe seam, never the global os.listdir: the patch
    # is live while pytest reports the result, and pytest's own machinery
    # must keep working during that window.
    monkeypatch.setattr(
        adapter_module,
        "_proc_filesystem_usable",
        lambda: (False, "/proc is not listable: no /proc here"),
    )
    result = adapter_module.posix_containment_preflight()
    assert result.usable is False
    assert "/proc" in result.reason


def test_migrated_preflight_result_is_immutable() -> None:
    result = adapter_module.posix_containment_preflight()
    with pytest.raises(AttributeError):
        result.usable = False  # type: ignore[misc]


def test_migrated_preflight_probes_cgroup_delegation_honestly() -> None:
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
    result = adapter_module.posix_containment_preflight()
    assert result.cgroup_delegation_available is independent


# --------------------------------------------------------------------------
# Compact framed evidence: the summary callers consume instead of raw logs
# --------------------------------------------------------------------------


def test_migrated_compact_evidence_is_schema_versioned_and_framed() -> None:
    result = run_bounded_posix_process([PY, "-c", "print('hi')"])
    framed = adapter_module.compact_execution_evidence(result)
    assert framed["schema_version"] == adapter_module.COMPACT_EVIDENCE_SCHEMA_VERSION
    assert framed["outcome"] == "succeeded"
    assert framed["return_code"] == 0
    assert framed["termination_confirmed"] is True
    containment = framed["containment"]
    assert containment["venue"] == "process-group"
    assert "clone3" in " ".join(containment["guarantees_not_claimed"]).lower()
    assert len(containment["guarantees_claimed"]) > 0
    assert "hi" in framed["stdout_tail"]
    assert framed["stdout_truncated"] is False
    assert len(framed["reason"]) <= 512


def test_migrated_compact_evidence_rejects_non_results() -> None:
    with pytest.raises(PosixProcessAdapterError):
        adapter_module.compact_execution_evidence(object())
