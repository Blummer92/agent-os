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
"""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Sequence

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
) -> PosixProcessExecutionResult:
    """Run exactly one bounded POSIX process attempt and return its evidence.

    Uses ``selectors.DefaultSelector`` to drain stdout and stderr
    concurrently so neither stream can deadlock the other. On timeout or
    cancellation, signals the whole process group, waits a bounded grace
    period, escalates through one frozen policy (SIGTERM then SIGKILL), and
    always finishes the wait/reap before returning. Never reports
    termination as confirmed unless both the child's exit and the final
    drain/reap were directly observed.
    """
    _require_posix()
    validated_argv = _validate_argv(argv)
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise PosixProcessAdapterError("timeout_seconds must be a positive number")
    if not isinstance(grace_period_seconds, (int, float)) or grace_period_seconds < 0:
        raise PosixProcessAdapterError("grace_period_seconds must not be negative")
    if not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
        raise PosixProcessAdapterError("max_output_bytes must be a positive integer")

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
        )
        self.last_result = result
        return _to_pilot_execution_observation(result)
