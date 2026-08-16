"""WSC5B2A bounded POSIX process adapter for the existing PilotExecutor contract.

Owns process creation, bounded concurrent pipe draining, timeout/cancellation
observation, process-group signaling, one bounded escalation, final
communication, and termination evidence -- and nothing else. It performs no
retry, no shell, no network, no persistence, no GitHub access, no worktree or
lease behavior, and no workflow dispatch.

``run_bounded_posix_process`` is the low-level, pure function that runs one
argv sequence at most once and returns a rich, bounded, immutable evidence
record. ``PosixProcessExecutor`` is a thin, one-shot adapter around it that
satisfies ``workflow_scheduler.execution.single_issue_pilot.PilotExecutor``
by mapping that rich evidence down onto the narrower, frozen
``PilotExecutionObservation`` contract; it invents no new fields there.

Termination is only ever reported as confirmed once both the child's exit and
the final pipe drain/reap have been directly observed. An ``ESRCH`` (process
already gone) response to a signal is never itself treated as proof of
termination.

WSC-AUTO1C adds an additive, opt-in ``containment`` parameter. When omitted
(the default), every existing behavior above is exactly unchanged. When a
``ContainmentConfig`` is supplied, the child is launched directly inside one
fresh per-invocation Linux cgroup v2 subtree via ``clone3_cgroup_launcher``
instead of ``subprocess.Popen``, escalation adds a bounded exact-scope
``cgroup.kill`` stage after process-group ``SIGTERM``, and
``termination_confirmed`` additionally requires the kernel's own recursive
``cgroup.events`` ``populated=0`` proof and confirmed removal of that empty
invocation cgroup. A containment preflight failure fails closed before any
process is spawned; there is no fallback to the uncontained path for that
invocation.
"""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from workflow_scheduler.execution import cgroup_v2_containment
from workflow_scheduler.execution.clone3_cgroup_launcher import (
    Clone3LaunchRequest,
    launch_into_cgroup,
)
from workflow_scheduler.execution.single_issue_pilot import (
    ExecutorOutcome,
    PilotExecutionObservation,
    PilotExecutionRequest,
)

POSIX_SUPPORTED = os.name == "posix"

MAX_ARGV_ITEMS = 64
MAX_ARGUMENT_BYTES = 4096
MAX_COMMAND_BYTES = 65_536
MAX_OUTPUT_BYTES = 65_536
MAX_REASON_LENGTH = 512

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_GRACE_PERIOD_SECONDS = 5.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.05
READ_CHUNK_BYTES = 4096


class PosixProcessAdapterError(ValueError):
    """Raised for an unsupported runtime or malformed/oversized argv.

    Always raised before any process is spawned.
    """


CancellationCheck = Callable[[], bool]

DEFAULT_DESCENDANT_WAIT_SECONDS = DEFAULT_GRACE_PERIOD_SECONDS


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainmentConfig:
    """Opt-in per-invocation Linux cgroup v2 containment configuration.

    ``delegated_parent_cgroup`` must be the one exact delegated Agent OS
    parent cgroup v2 subtree (never an arbitrary host path); a fresh
    ``wsc-invocation-<invocation_id>`` child cgroup is created under it for
    this run only, and only that one child cgroup is ever read, signaled,
    or removed.
    """

    delegated_parent_cgroup: str
    invocation_id: str
    descendant_wait_seconds: float = DEFAULT_DESCENDANT_WAIT_SECONDS

    def __post_init__(self) -> None:
        if not self.delegated_parent_cgroup:
            raise PosixProcessAdapterError(
                "containment.delegated_parent_cgroup must be a non-empty path"
            )
        if not self.invocation_id:
            raise PosixProcessAdapterError(
                "containment.invocation_id must be a non-empty identifier"
            )
        if (
            not isinstance(self.descendant_wait_seconds, (int, float))
            or self.descendant_wait_seconds < 0
        ):
            raise PosixProcessAdapterError(
                "containment.descendant_wait_seconds must not be negative"
            )


# --------------------------------------------------------------------------
# Preflight: runtime and argv validation (before spawn)
# --------------------------------------------------------------------------


def _require_posix() -> None:
    if not POSIX_SUPPORTED:
        raise PosixProcessAdapterError("the POSIX process adapter requires a POSIX runtime")


def _validate_argv(argv: object) -> tuple[str, ...]:
    if isinstance(argv, (str, bytes)):
        raise PosixProcessAdapterError(
            "argv must be a sequence of strings, not a single string or bytes"
        )
    if not isinstance(argv, (list, tuple)):
        raise PosixProcessAdapterError("argv must be a list or tuple of strings")
    items = tuple(argv)
    if len(items) == 0:
        raise PosixProcessAdapterError("argv must not be empty")
    if len(items) > MAX_ARGV_ITEMS:
        raise PosixProcessAdapterError("argv exceeds the bounded argument count")
    total_bytes = 0
    for item in items:
        if not isinstance(item, str):
            raise PosixProcessAdapterError("every argv element must be a string")
        if not item:
            raise PosixProcessAdapterError("argv elements must not be empty")
        if "\x00" in item:
            raise PosixProcessAdapterError("argv elements must not contain NUL bytes")
        encoded_length = len(item.encode("utf-8"))
        if encoded_length > MAX_ARGUMENT_BYTES:
            raise PosixProcessAdapterError("an argv element exceeds the bounded byte length")
        total_bytes += encoded_length
    if total_bytes > MAX_COMMAND_BYTES:
        raise PosixProcessAdapterError("argv exceeds the bounded aggregate byte length")
    return items


# --------------------------------------------------------------------------
# Bounded head/tail output retention
# --------------------------------------------------------------------------


class _BoundedBuffer:
    """Retains a bounded head+tail prefix/suffix of an unbounded byte stream."""

    __slots__ = ("_max_bytes", "_head", "_tail", "_total", "truncated")

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes
        self._head = bytearray()
        self._tail = bytearray()
        self._total = 0
        self.truncated = False

    def add(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._total += len(chunk)
        half = max(self._max_bytes // 2, 1)
        if len(self._head) < half:
            take = half - len(self._head)
            self._head.extend(chunk[:take])
            chunk = chunk[take:]
        if chunk:
            self._tail.extend(chunk)
            if len(self._tail) > half:
                del self._tail[: len(self._tail) - half]
        self.truncated = self._total > self._max_bytes

    def text(self) -> str:
        return bytes(self._head + self._tail).decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# Rich, bounded, immutable process evidence
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class PosixProcessExecutionResult:
    """Bounded, immutable evidence for exactly one POSIX process attempt."""

    started: bool
    timeout_observed: bool
    cancellation_requested: bool
    signal_dispatched: str | None
    escalation_dispatched: bool
    child_exit_observed: bool
    communication_completed: bool
    return_code: int | None
    stdout_text: str
    stdout_truncated: bool
    stderr_text: str
    stderr_truncated: bool
    termination_confirmed: bool
    possible_partial_effects: bool
    reason: str = ""
    pid: int | None = None
    contained: bool = False
    invocation_cgroup_path: str | None = None
    cgroup_kill_dispatched: bool = False
    populated_confirmed_clear: bool | None = None
    cleanup_confirmed: bool | None = None
    exec_failure_phase: str | None = None
    exec_failure_errno: int | None = None


MAX_CGROUP_PATH_LENGTH = 1024


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainedTerminationEvidence:
    """Independently observed containment proof for exactly one invocation.

    Carries only the canonical contained-termination facts this module already
    owns: the direct child exit/reap, the final pipe drain, the kernel's own
    recursive ``cgroup.events`` ``populated=0`` observation, and removal of that
    exact invocation cgroup.

    Process age, TTL, wall-clock expiry, heartbeat absence, PID absence,
    ``ESRCH``, process names, and host reachability are deliberately absent:
    none of them prove termination, so none of them can be expressed here and
    none of them can satisfy ``termination_proven``.
    """

    invocation_cgroup_path: str
    contained: bool
    child_exit_observed: bool
    communication_completed: bool
    return_code: int | None
    populated_confirmed_clear: bool | None
    cleanup_confirmed: bool | None

    def __post_init__(self) -> None:
        if type(self.invocation_cgroup_path) is not str or not self.invocation_cgroup_path:
            raise PosixProcessAdapterError(
                "invocation_cgroup_path must be a non-empty string"
            )
        if len(self.invocation_cgroup_path) > MAX_CGROUP_PATH_LENGTH:
            raise PosixProcessAdapterError(
                "invocation_cgroup_path exceeds the bounded path length"
            )
        for name in ("contained", "child_exit_observed", "communication_completed"):
            if type(getattr(self, name)) is not bool:
                raise PosixProcessAdapterError(f"{name} must be an exact bool")
        if self.return_code is not None and (
            type(self.return_code) is not int or isinstance(self.return_code, bool)
        ):
            raise PosixProcessAdapterError("return_code must be an int or None")
        for name in ("populated_confirmed_clear", "cleanup_confirmed"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise PosixProcessAdapterError(f"{name} must be a bool or None")

    @property
    def termination_proven(self) -> bool:
        """Report the same contained proof ``termination_confirmed`` requires.

        This mirrors ``_run_bounded_posix_process_contained`` exactly so the
        containment proof keeps a single definition in this module. An
        uncontained attempt can never satisfy it.
        """
        return bool(
            self.contained
            and self.child_exit_observed
            and self.communication_completed
            and self.return_code is not None
            and self.populated_confirmed_clear
            and self.cleanup_confirmed
        )


def contained_termination_evidence(
    result: PosixProcessExecutionResult,
) -> ContainedTerminationEvidence:
    """Project one bounded contained execution result onto its termination proof.

    Raises rather than inventing a path when the attempt was never contained:
    only the containment path produces the recursive-emptiness and cgroup
    cleanup observations this evidence is built from.
    """
    if type(result) is not PosixProcessExecutionResult:
        raise PosixProcessAdapterError("result must be an exact PosixProcessExecutionResult")
    if not result.contained or result.invocation_cgroup_path is None:
        raise PosixProcessAdapterError(
            "contained termination evidence requires a contained invocation"
        )
    return ContainedTerminationEvidence(
        invocation_cgroup_path=result.invocation_cgroup_path,
        contained=bool(result.contained),
        child_exit_observed=bool(result.child_exit_observed),
        communication_completed=bool(result.communication_completed),
        return_code=result.return_code,
        populated_confirmed_clear=result.populated_confirmed_clear,
        cleanup_confirmed=result.cleanup_confirmed,
    )


def _signal_group(process: "subprocess.Popen[bytes]", sig: signal.Signals) -> str | None:
    try:
        pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        return None
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        return None
    return sig.name


def _drain_until(
    process: "subprocess.Popen[bytes]",
    selector: selectors.BaseSelector,
    open_streams: set,
    deadline: float,
    cancelled: CancellationCheck | None,
    poll_interval: float,
) -> tuple[bool, bool, bool]:
    """Drain ready pipes until both close, the deadline passes, or cancellation.

    Returns ``(timeout_observed, cancellation_requested, exited)``.
    """
    while True:
        exited = process.poll() is not None
        if exited and not open_streams:
            return False, False, True
        now = time.monotonic()
        remaining = deadline - now
        if remaining <= 0:
            return True, False, exited and not open_streams
        if cancelled is not None and cancelled():
            return False, True, exited and not open_streams
        if not open_streams:
            # Process still running with both pipes closed; just wait for exit.
            time.sleep(min(poll_interval, remaining))
            continue
        for key, _ in selector.select(timeout=min(poll_interval, remaining)):
            stream = key.fileobj
            buf: _BoundedBuffer = key.data
            try:
                chunk = stream.read1(READ_CHUNK_BYTES)  # type: ignore[union-attr]
            except BlockingIOError:
                continue
            except OSError:
                chunk = b""
            if not chunk:
                selector.unregister(stream)
                open_streams.discard(stream)
                continue
            buf.add(chunk)


def run_bounded_posix_process(
    argv: Sequence[str],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    grace_period_seconds: float = DEFAULT_GRACE_PERIOD_SECONDS,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    cancelled: CancellationCheck | None = None,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    containment: ContainmentConfig | None = None,
) -> PosixProcessExecutionResult:
    """Run exactly one bounded POSIX process attempt and return its evidence.

    Uses ``selectors.DefaultSelector`` to drain stdout and stderr
    concurrently so neither stream can deadlock the other. On timeout or
    cancellation, signals the whole process group, waits a bounded grace
    period, escalates through one frozen policy (SIGTERM then SIGKILL), and
    always finishes the wait/reap before returning. Never reports
    termination as confirmed unless both the child's exit and the final
    drain/reap were directly observed.

    ``containment`` is additive and opt-in. When ``None`` (the default),
    everything above is exactly the pre-#759 behavior. When supplied, see
    the module docstring and ``_run_bounded_posix_process_contained`` for
    the cgroup v2 containment path.
    """
    _require_posix()
    validated_argv = _validate_argv(argv)
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise PosixProcessAdapterError("timeout_seconds must be a positive number")
    if not isinstance(grace_period_seconds, (int, float)) or grace_period_seconds < 0:
        raise PosixProcessAdapterError("grace_period_seconds must not be negative")
    if not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
        raise PosixProcessAdapterError("max_output_bytes must be a positive integer")

    if containment is not None:
        return _run_bounded_posix_process_contained(
            validated_argv,
            timeout_seconds=timeout_seconds,
            grace_period_seconds=grace_period_seconds,
            max_output_bytes=max_output_bytes,
            cwd=cwd,
            env=env,
            cancelled=cancelled,
            poll_interval_seconds=poll_interval_seconds,
            containment=containment,
        )

    process: subprocess.Popen[bytes] = subprocess.Popen(  # noqa: S603 - argv validated above
        list(validated_argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    started = True

    stdout_buf = _BoundedBuffer(max_output_bytes)
    stderr_buf = _BoundedBuffer(max_output_bytes)

    assert process.stdout is not None and process.stderr is not None
    os.set_blocking(process.stdout.fileno(), False)
    os.set_blocking(process.stderr.fileno(), False)

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, stdout_buf)
    selector.register(process.stderr, selectors.EVENT_READ, stderr_buf)
    open_streams = {process.stdout, process.stderr}

    try:
        deadline = time.monotonic() + timeout_seconds
        timeout_observed, cancellation_requested, exited = _drain_until(
            process, selector, open_streams, deadline, cancelled, poll_interval_seconds
        )

        signal_dispatched: str | None = None
        escalation_dispatched = False
        child_exit_observed = exited

        if not exited and (timeout_observed or cancellation_requested):
            signal_dispatched = _signal_group(process, signal.SIGTERM)
            grace_deadline = time.monotonic() + grace_period_seconds
            _, _, exited_after_term = _drain_until(
                process, selector, open_streams, grace_deadline, None, poll_interval_seconds
            )
            child_exit_observed = exited_after_term

            if not exited_after_term:
                escalation_dispatched = _signal_group(process, signal.SIGKILL) is not None
                kill_deadline = time.monotonic() + grace_period_seconds
                _, _, exited_after_kill = _drain_until(
                    process, selector, open_streams, kill_deadline, None, poll_interval_seconds
                )
                child_exit_observed = exited_after_kill
    finally:
        selector.close()

    communication_completed = False
    return_code = process.poll()
    if child_exit_observed or return_code is not None:
        try:
            return_code = process.wait(timeout=max(grace_period_seconds, 0.1))
            communication_completed = True
        except subprocess.TimeoutExpired:
            communication_completed = False
    termination_confirmed = bool(
        child_exit_observed and communication_completed and return_code is not None
    )
    possible_partial_effects = not termination_confirmed

    reason = _bounded_reason(
        return_code=return_code,
        timeout_observed=timeout_observed,
        cancellation_requested=cancellation_requested,
        signal_dispatched=signal_dispatched,
        escalation_dispatched=escalation_dispatched,
        stdout_truncated=stdout_buf.truncated,
        stderr_truncated=stderr_buf.truncated,
    )

    return PosixProcessExecutionResult(
        started=started,
        timeout_observed=timeout_observed,
        cancellation_requested=cancellation_requested,
        signal_dispatched=signal_dispatched,
        escalation_dispatched=escalation_dispatched,
        child_exit_observed=child_exit_observed,
        communication_completed=communication_completed,
        return_code=return_code,
        stdout_text=stdout_buf.text(),
        stdout_truncated=stdout_buf.truncated,
        stderr_text=stderr_buf.text(),
        stderr_truncated=stderr_buf.truncated,
        termination_confirmed=termination_confirmed,
        possible_partial_effects=possible_partial_effects,
        reason=reason,
        pid=process.pid,
    )


def _bounded_reason(
    *,
    return_code: int | None,
    timeout_observed: bool,
    cancellation_requested: bool,
    signal_dispatched: str | None,
    escalation_dispatched: bool,
    stdout_truncated: bool,
    stderr_truncated: bool,
) -> str:
    text = (
        f"return_code={return_code} timeout_observed={timeout_observed} "
        f"cancellation_requested={cancellation_requested} "
        f"signal_dispatched={signal_dispatched} "
        f"escalation_dispatched={escalation_dispatched} "
        f"stdout_truncated={stdout_truncated} stderr_truncated={stderr_truncated}"
    )
    return text[:MAX_REASON_LENGTH]


# --------------------------------------------------------------------------
# Optional cgroup v2 containment path (WSC-AUTO1C)
# --------------------------------------------------------------------------


def _decode_wait_status(status: int) -> int | None:
    """Mirror ``subprocess``'s return-code sign convention for a raw wait status."""
    if os.WIFSIGNALED(status):
        return -os.WTERMSIG(status)
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    return None


class _ClonedProcessHandle:
    """Duck-types just enough of ``subprocess.Popen`` for ``_signal_group``/``_drain_until``.

    Backs a pid that was created by ``clone3(CLONE_INTO_CGROUP)`` rather
    than ``subprocess.Popen``, so both helpers can be reused verbatim for
    the contained launch path instead of duplicating their polling logic.
    """

    __slots__ = ("pid", "_returncode")

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._returncode: int | None = None

    def poll(self) -> int | None:
        if self._returncode is not None:
            return self._returncode
        try:
            reaped_pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            return self._returncode
        if reaped_pid == 0:
            return None
        self._returncode = _decode_wait_status(status)
        return self._returncode

    def wait(self, timeout: float | None = None) -> int:
        if self._returncode is not None:
            return self._returncode
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            return_code = self.poll()
            if return_code is not None:
                return return_code
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(cmd=["<contained>"], timeout=timeout)
            time.sleep(0.005)


def _bounded_reason_contained(
    *,
    return_code: int | None,
    timeout_observed: bool,
    cancellation_requested: bool,
    signal_dispatched: str | None,
    cgroup_kill_dispatched: bool,
    populated_confirmed_clear: bool | None,
    cleanup_confirmed: bool | None,
    exec_failure_phase: str | None,
    exec_failure_errno: int | None,
) -> str:
    text = (
        f"return_code={return_code} timeout_observed={timeout_observed} "
        f"cancellation_requested={cancellation_requested} "
        f"signal_dispatched={signal_dispatched} "
        f"cgroup_kill_dispatched={cgroup_kill_dispatched} "
        f"populated_confirmed_clear={populated_confirmed_clear} "
        f"cleanup_confirmed={cleanup_confirmed} "
        f"exec_failure_phase={exec_failure_phase} exec_failure_errno={exec_failure_errno}"
    )
    return text[:MAX_REASON_LENGTH]


def _run_bounded_posix_process_contained(
    validated_argv: tuple[str, ...],
    *,
    timeout_seconds: float,
    grace_period_seconds: float,
    max_output_bytes: int,
    cwd: str | None,
    env: dict[str, str] | None,
    cancelled: CancellationCheck | None,
    poll_interval_seconds: float,
    containment: ContainmentConfig,
) -> PosixProcessExecutionResult:
    """The WSC-AUTO1C cgroup v2 containment launch/escalation/evidence path.

    Preflight runs first and fails closed (raises) before any process is
    spawned. Escalation on timeout/cancellation is process-group ``SIGTERM``
    first (identical timing/logic to the uncontained path), then bounded
    exact-scope ``cgroup.kill`` only if the grace period expires without
    exit. ``termination_confirmed`` additionally requires the kernel's own
    recursive ``cgroup.events`` ``populated=0`` proof and confirmed removal
    of the invocation cgroup.
    """
    preflight = cgroup_v2_containment.preflight_check(containment.delegated_parent_cgroup)
    if not preflight.supported:
        raise cgroup_v2_containment.CgroupV2PreflightError(
            f"cgroup v2 containment preflight failed: {preflight.reason}"
        )

    inv_cgroup = cgroup_v2_containment.InvocationCgroup.create(
        containment.delegated_parent_cgroup, containment.invocation_id
    )

    devnull_fd = os.open(os.devnull, os.O_RDONLY)
    stdout_r_fd, stdout_w_fd = os.pipe()
    stderr_r_fd, stderr_w_fd = os.pipe()

    stdout_buf = _BoundedBuffer(max_output_bytes)
    stderr_buf = _BoundedBuffer(max_output_bytes)

    env_for_launch = None if env is None else dict(env)

    started = False
    handle: _ClonedProcessHandle | None = None
    exec_failed = False
    exec_failure_phase: str | None = None
    exec_failure_errno: int | None = None
    selector = selectors.DefaultSelector()
    stdout_stream = None
    stderr_stream = None

    timeout_observed = False
    cancellation_requested = False
    signal_dispatched: str | None = None
    cgroup_kill_dispatched = False
    child_exit_observed = False
    communication_completed = False
    return_code: int | None = None
    populated_confirmed_clear: bool | None = None
    cleanup_confirmed: bool | None = None

    try:
        outcome = launch_into_cgroup(
            Clone3LaunchRequest(
                argv=validated_argv,
                cwd=cwd,
                env=env_for_launch,
                cgroup_fd=inv_cgroup.fd,
                stdin_fd=devnull_fd,
                stdout_fd=stdout_w_fd,
                stderr_fd=stderr_w_fd,
            )
        )
        started = True
        handle = _ClonedProcessHandle(outcome.pid)
        exec_failed = outcome.exec_failed
        exec_failure_phase = outcome.exec_failure_phase
        exec_failure_errno = outcome.exec_failure_errno
    finally:
        os.close(devnull_fd)
        os.close(stdout_w_fd)
        os.close(stderr_w_fd)

    try:
        stdout_stream = os.fdopen(stdout_r_fd, "rb")
        stderr_stream = os.fdopen(stderr_r_fd, "rb")
        os.set_blocking(stdout_stream.fileno(), False)
        os.set_blocking(stderr_stream.fileno(), False)
        selector.register(stdout_stream, selectors.EVENT_READ, stdout_buf)
        selector.register(stderr_stream, selectors.EVENT_READ, stderr_buf)
        open_streams = {stdout_stream, stderr_stream}

        try:
            deadline = time.monotonic() + timeout_seconds
            timeout_observed, cancellation_requested, exited = _drain_until(
                handle, selector, open_streams, deadline, cancelled, poll_interval_seconds
            )
            child_exit_observed = exited

            if not exited and (timeout_observed or cancellation_requested):
                signal_dispatched = _signal_group(handle, signal.SIGTERM)
                grace_deadline = time.monotonic() + grace_period_seconds
                _, _, exited_after_term = _drain_until(
                    handle, selector, open_streams, grace_deadline, None, poll_interval_seconds
                )
                child_exit_observed = exited_after_term

                if not exited_after_term:
                    try:
                        inv_cgroup.kill()
                        cgroup_kill_dispatched = True
                    except cgroup_v2_containment.CgroupV2ContainmentError:
                        cgroup_kill_dispatched = False
                    kill_deadline = time.monotonic() + grace_period_seconds
                    _, _, exited_after_kill = _drain_until(
                        handle, selector, open_streams, kill_deadline, None, poll_interval_seconds
                    )
                    child_exit_observed = exited_after_kill
        finally:
            selector.close()

        if child_exit_observed or handle.poll() is not None:
            try:
                return_code = handle.wait(timeout=max(grace_period_seconds, 0.1))
                communication_completed = True
            except subprocess.TimeoutExpired:
                communication_completed = False

        if child_exit_observed:
            populated_confirmed_clear = inv_cgroup.wait_until_empty(
                deadline_seconds=containment.descendant_wait_seconds
            )
            if populated_confirmed_clear:
                try:
                    cleanup_confirmed = inv_cgroup.cleanup()
                except cgroup_v2_containment.CgroupV2ContainmentError:
                    cleanup_confirmed = False
            else:
                cleanup_confirmed = False
    finally:
        if stdout_stream is not None:
            stdout_stream.close()
        else:
            os.close(stdout_r_fd)
        if stderr_stream is not None:
            stderr_stream.close()
        else:
            os.close(stderr_r_fd)
        inv_cgroup.close()

    termination_confirmed = bool(
        child_exit_observed
        and communication_completed
        and return_code is not None
        and populated_confirmed_clear
        and cleanup_confirmed
    )
    possible_partial_effects = not termination_confirmed

    reason = _bounded_reason_contained(
        return_code=return_code,
        timeout_observed=timeout_observed,
        cancellation_requested=cancellation_requested,
        signal_dispatched=signal_dispatched,
        cgroup_kill_dispatched=cgroup_kill_dispatched,
        populated_confirmed_clear=populated_confirmed_clear,
        cleanup_confirmed=cleanup_confirmed,
        exec_failure_phase=exec_failure_phase,
        exec_failure_errno=exec_failure_errno,
    )

    return PosixProcessExecutionResult(
        started=started,
        timeout_observed=timeout_observed,
        cancellation_requested=cancellation_requested,
        signal_dispatched=signal_dispatched,
        escalation_dispatched=cgroup_kill_dispatched,
        child_exit_observed=child_exit_observed,
        communication_completed=communication_completed,
        return_code=return_code,
        stdout_text=stdout_buf.text(),
        stdout_truncated=stdout_buf.truncated,
        stderr_text=stderr_buf.text(),
        stderr_truncated=stderr_buf.truncated,
        termination_confirmed=termination_confirmed,
        possible_partial_effects=possible_partial_effects,
        reason=reason,
        pid=handle.pid if handle is not None else None,
        contained=True,
        invocation_cgroup_path=inv_cgroup.path,
        cgroup_kill_dispatched=cgroup_kill_dispatched,
        populated_confirmed_clear=populated_confirmed_clear,
        cleanup_confirmed=cleanup_confirmed,
        exec_failure_phase=exec_failure_phase,
        exec_failure_errno=exec_failure_errno,
    )


# --------------------------------------------------------------------------
# PilotExecutor-conformant, one-shot adapter
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class PosixProcessExecutorConfig:
    """One bounded, validated argv plus its execution limits."""

    argv: tuple[str, ...]
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    grace_period_seconds: float = DEFAULT_GRACE_PERIOD_SECONDS
    max_output_bytes: int = MAX_OUTPUT_BYTES
    cwd: str | None = None
    env: dict[str, str] | None = None
    containment: ContainmentConfig | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", _validate_argv(self.argv))


def _outcome_for(result: PosixProcessExecutionResult) -> ExecutorOutcome:
    if result.cancellation_requested:
        return "cancelled"
    if result.timeout_observed:
        return "timed-out"
    if result.return_code == 0:
        return "succeeded"
    return "failed"


def _to_pilot_execution_observation(
    result: PosixProcessExecutionResult,
) -> PilotExecutionObservation:
    return PilotExecutionObservation(
        outcome=_outcome_for(result),
        started=result.started,
        cancellation_requested=result.cancellation_requested,
        termination_confirmed=result.termination_confirmed,
        possible_partial_effects=result.possible_partial_effects,
        changed_paths=(),
        reason=result.reason,
    )


class PosixProcessExecutor:
    """A one-shot ``PilotExecutor`` backed by ``run_bounded_posix_process``."""

    def __init__(
        self,
        config: PosixProcessExecutorConfig,
        *,
        cancelled: CancellationCheck | None = None,
    ) -> None:
        if not isinstance(config, PosixProcessExecutorConfig):
            raise TypeError("config must be PosixProcessExecutorConfig")
        _require_posix()
        self._config = config
        self._cancelled = cancelled
        self._attempted = False
        self.last_result: PosixProcessExecutionResult | None = None

    def run(self, request: PilotExecutionRequest) -> PilotExecutionObservation:
        if not isinstance(request, PilotExecutionRequest):
            raise TypeError("request must be PilotExecutionRequest")
        if self._attempted:
            raise RuntimeError("the POSIX process executor may run at most once")
        self._attempted = True
        result = run_bounded_posix_process(
            self._config.argv,
            timeout_seconds=self._config.timeout_seconds,
            grace_period_seconds=self._config.grace_period_seconds,
            max_output_bytes=self._config.max_output_bytes,
            cwd=self._config.cwd,
            env=self._config.env,
            cancelled=self._cancelled,
            containment=self._config.containment,
        )
        self.last_result = result
        return _to_pilot_execution_observation(result)
