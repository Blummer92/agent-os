"""WSC5B2A bounded POSIX process adapter for the existing PilotExecutor contract.

Owns process creation, bounded concurrent pipe draining, timeout/cancellation
observation, process-group signaling, one bounded escalation, final
communication, and termination evidence -- and nothing else. Migrated from the
retired #3200 lighter variant, it additionally owns optional rlimit
lowering at launch, a post-escalation ``/proc`` survivor scan proving
zero live processes remain in the invocation pgid, and an explicit venue
attestation carried on every result. It performs no
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
from typing import Callable, Mapping, Sequence

try:
    import resource as _resource
except ImportError:  # pragma: no cover - non-POSIX hosts fail _require_posix first
    _resource = None

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
# Migrated containment guarantees (from the retired #3200 lighter variant)
#
# For execution venues where cgroup v2 delegation is unavailable, the #759
# cgroup proof is unproducible. These helpers own: rlimit lowering at
# launch (lowering never needs privilege), a /proc survivor scan proving
# zero live processes remain in the invocation pgid, and an explicit venue
# capability attestation carried on every result. All failures are typed
# and fail closed.
# --------------------------------------------------------------------------

# The #759-grade guarantees this process-group variant explicitly does NOT
# claim. Surfaced verbatim in every result's attestation fields: no silent
# downgrade from the cgroup proof to the process-group proof.
GUARANTEES_NOT_CLAIMED = (
    "clone3(CLONE_INTO_CGROUP) race-free launch directly inside a target cgroup",
    "kernel recursive cgroup.events populated=0 whole-subtree emptiness proof",
    "cgroup.kill exact-scope escalation reaching descendants that left the process group (setsid)",
    "per-invocation cgroup creation, identity, and rmdir cleanup",
)

GUARANTEES_CLAIMED = (
    "one fresh process group per invocation (pgid == child pid)",
    "SIGTERM-then-SIGKILL escalation scoped to exactly the invocation pgid",
    "/proc survivor scan proving zero live processes remain in the invocation pgid",
    "direct-child waitpid reap with observed exit status",
    "final stdout/stderr pipe drain to completion",
    "rlimit bounds applied at launch (lowering only, no privilege)",
)


class PosixProcessSurvivorError(RuntimeError):
    """Live processes remained in the invocation pgid after SIGKILL escalation.

    Fail-closed and never silently ignored: the surviving pids are named in
    the message. Also raised when the survivor state itself cannot be
    established (``/proc`` unlistable). Deliberately a ``RuntimeError``,
    not a ``ValueError``: this is a runtime containment breach, never a
    malformed-input rejection (those stay ``PosixProcessAdapterError`` and
    are always raised before any process is spawned).
    """


def _resolve_rlimit_key(key: object) -> int:
    """Resolve an rlimit key to a ``resource.RLIMIT_*`` constant.

    Accepts the constant itself or its exact name (``"RLIMIT_NPROC"``).
    Anything else fails closed at launch time, never silently skipped.
    """
    if _resource is None:  # pragma: no cover - _require_posix already failed
        raise PosixProcessAdapterError("the resource module is unavailable")
    if isinstance(key, int) and not isinstance(key, bool):
        return key
    if isinstance(key, str):
        resolved = getattr(_resource, key, None)
        if isinstance(resolved, int) and not isinstance(resolved, bool):
            return resolved
    raise PosixProcessAdapterError(f"unknown rlimit key: {key!r}")


def _validate_rlimits(
    rlimits: Mapping[object, tuple[int, int]] | None,
) -> dict[int, tuple[int, int]]:
    """Validate the caller-supplied rlimit map before any process is spawned."""
    if rlimits is None:
        return {}
    validated: dict[int, tuple[int, int]] = {}
    for key, bounds in rlimits.items():
        if (
            not isinstance(bounds, (tuple, list))
            or len(bounds) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in bounds)
        ):
            raise PosixProcessAdapterError(
                f"rlimit {key!r} must map to a (soft, hard) int pair, got {bounds!r}"
            )
        soft, hard = int(bounds[0]), int(bounds[1])
        if soft < -1 or hard < -1:
            raise PosixProcessAdapterError(
                f"rlimit {key!r} bounds must be >= -1 (RLIM_INFINITY), got {(soft, hard)}"
            )
        validated[_resolve_rlimit_key(key)] = (soft, hard)
    return validated


def _rlimit_display_name(res: int) -> str:
    """Best-effort ``RLIMIT_*`` name for a constant, for evidence records."""
    assert _resource is not None
    for name in dir(_resource):
        if name.startswith("RLIMIT_") and getattr(_resource, name) == res:
            return name
    return str(res)


def _apply_rlimits_in_child(rlimits: dict[int, tuple[int, int]]) -> None:
    """``preexec_fn`` body: lower rlimits in the forked child before exec.

    Only ``setrlimit`` syscalls are issued here -- no allocation, no Python
    C-API use beyond the call itself -- because this runs between fork and
    exec. Lowering a limit never needs privilege.
    """
    assert _resource is not None
    for res, (soft, hard) in rlimits.items():
        _resource.setrlimit(res, (soft, hard))


def _read_proc_stat(pid: int) -> tuple[int, str] | None:
    """Return ``(pgrp, state)`` for a pid, or None if it vanished/unreadable.

    A process in another uid's session can never share our fresh pgid, so
    an unreadable entry is skipped rather than treated as a survivor; a
    vanished pid is simply gone.
    """
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
            text = handle.read()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    # comm may contain spaces/parens; the fields after the last ')' are stable.
    tail = text.rsplit(")", 1)
    if len(tail) != 2:
        return None
    fields = tail[1].split()
    if len(fields) < 4:
        return None
    try:
        return int(fields[2]), fields[0]
    except ValueError:
        return None


def _pgid_live_survivors(pgid: int) -> list[int]:
    """Pids still alive in ``pgid``, excluding zombies.

    A zombie (state ``Z``) is already dead; reaping it is init's job after
    reparenting, not this module's. Only live processes count as
    survivors. Raises ``PosixProcessSurvivorError`` when ``/proc`` cannot
    be listed: survivor state that cannot be established is itself a
    fail-closed condition.
    """
    survivors: list[int] = []
    try:
        entries = os.listdir("/proc")
    except OSError as exc:
        raise PosixProcessSurvivorError(
            f"survivor scan could not list /proc: {exc}"
        ) from exc
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        stat = _read_proc_stat(pid)
        if stat is None:
            continue
        pgrp, state = stat
        if pgrp == pgid and state != "Z":
            survivors.append(pid)
    return sorted(survivors)


def _assert_no_pgid_survivors(pgid: int, settle_seconds: float) -> None:
    """Fail closed unless zero live processes remain in ``pgid``.

    Settles briefly (a reaped child needs a moment to vanish from
    ``/proc``), then raises ``PosixProcessSurvivorError`` naming any
    survivors -- never silently ignored.
    """
    deadline = time.monotonic() + max(settle_seconds, 0.0)
    survivors = _pgid_live_survivors(pgid)
    while survivors and time.monotonic() < deadline:
        time.sleep(0.02)
        survivors = _pgid_live_survivors(pgid)
    if survivors:
        raise PosixProcessSurvivorError(
            f"{len(survivors)} live process(es) survived SIGKILL in pgid {pgid}: "
            f"{survivors}; route to manual review/quarantine"
        )


def _silent_kill(process: "subprocess.Popen[bytes]") -> None:
    """Best-effort kill+reap for a child that failed containment setup."""
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


CGROUP2_MOUNT_CANDIDATES = ("/sys/fs/cgroup", "/sys/fs/cgroup/unified")


def _cgroup_delegation_available() -> bool:
    """Actively probe for a writable cgroup v2 subtree.

    Reports True only if a cgroup2 mount exists AND a probe directory can
    be created and removed inside it. In container venues (read-only
    ``/sys/fs/cgroup``) this reports False -- which the attestation
    records honestly instead of treating as fatal.
    """
    for candidate in CGROUP2_MOUNT_CANDIDATES:
        controllers = os.path.join(candidate, "cgroup.controllers")
        if not os.path.isfile(controllers):
            continue
        probe = os.path.join(candidate, f".agentos-pg-preflight-{os.getpid()}")
        try:
            os.mkdir(probe)
        except OSError:
            continue
        try:
            os.rmdir(probe)
        except OSError:
            pass
        return True
    return False


def _setpgid_probe() -> tuple[bool, str]:
    """Prove a fresh process group can actually be created on this host.

    The pgid is read while the probe child is still alive: reading it
    after ``wait()`` would race the pid's disappearance.
    """
    try:
        proc = subprocess.Popen(
            ["/bin/sleep", "30"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return False, f"cannot spawn a process-group leader: {exc}"
    try:
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            return False, f"cannot read the spawned child's pgid: {exc}"
        if pgid != proc.pid:
            return False, f"child pgid {pgid} != child pid {proc.pid}"
        return True, ""
    finally:
        _silent_kill(proc)


def _proc_filesystem_usable() -> tuple[bool, str]:
    """/proc must be listable: the survivor scan has no pgrep fallback."""
    try:
        entries = os.listdir("/proc")
    except OSError as exc:
        return False, f"/proc is not listable: {exc}"
    if not any(entry.isdigit() for entry in entries):
        return False, "/proc contains no numeric pid entries"
    return True, ""


def _os_name() -> str:
    """Return ``os.name`` through an indirection tests can safely patch.

    Patching the real ``os.name`` is not viable: pytest calls
    ``pathlib.Path()`` while reporting each test result, and ``Path``
    dispatches on ``os.name`` -- a leaked ``"nt"`` crashes the whole
    session with ``INTERNALERROR: cannot instantiate 'WindowsPath'``.
    Tests simulate a non-POSIX host by patching this function instead.
    """
    return os.name


@dataclass(frozen=True, slots=True, kw_only=True)
class PosixContainmentPreflightResult:
    """Bounded, immutable evidence for one containment preflight probe.

    ``usable`` is the single fail-closed gate: any caller must refuse to
    spawn an uncontained process when it is ``False``.
    ``cgroup_delegation_available`` is reported honestly (False in
    container venues) but does not gate ``usable`` -- this variant exists
    precisely for venues without delegation.
    """

    usable: bool
    reason: str
    cgroup_delegation_available: bool
    setpgid_available: bool
    rlimit_available: bool


def posix_containment_preflight() -> PosixContainmentPreflightResult:
    """Probe every process-group containment precondition without side effects.

    Fails closed: ``usable`` is True only on a POSIX host where a fresh
    process group can actually be created, rlimits can be lowered, and
    ``/proc`` is listable for the survivor scan. The probe child exits
    immediately and is reaped; nothing persists. This is the entry point
    for the Codespace experiment (expect ``usable=True`` with
    ``cgroup_delegation_available=False`` there).
    """
    reasons: list[str] = []

    if _os_name() != "posix":
        reasons.append(f"not a POSIX host (os.name={_os_name()!r})")

    setpgid_available = False
    if _os_name() == "posix":
        setpgid_available, setpgid_reason = _setpgid_probe()
        if not setpgid_available:
            reasons.append(setpgid_reason)

    rlimit_available = _resource is not None
    if not rlimit_available:
        reasons.append("the resource module is unavailable (rlimits cannot be applied)")
    else:
        try:
            current = _resource.getrlimit(_resource.RLIMIT_NPROC)
            _resource.setrlimit(_resource.RLIMIT_NPROC, current)
        except (OSError, ValueError) as exc:
            rlimit_available = False
            reasons.append(f"rlimit get/set probe failed: {exc}")

    proc_usable, proc_reason = _proc_filesystem_usable()
    if not proc_usable:
        reasons.append(proc_reason)

    cgroup_delegation_available = _cgroup_delegation_available()

    usable = (
        _os_name() == "posix"
        and setpgid_available
        and rlimit_available
        and proc_usable
    )
    return PosixContainmentPreflightResult(
        usable=usable,
        reason="; ".join(reasons),
        cgroup_delegation_available=cgroup_delegation_available,
        setpgid_available=setpgid_available,
        rlimit_available=rlimit_available,
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
    # Migrated venue attestation (from the retired #3200 lighter variant).
    # Every result states its containment venue and exactly which
    # guarantees it claims -- never the #759 cgroup proof.
    rlimits_applied: dict[str, list[int]] | None = None
    containment_venue: str | None = None
    cgroup_delegation_available: bool | None = None
    guarantees_claimed: tuple[str, ...] | None = None
    guarantees_not_claimed: tuple[str, ...] | None = None
    survivor_scan_performed: bool = False
    survivor_count: int = 0


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

        The containment launch path is removed (#3101 invasive); this proof
        definition is retained for the host-local lease recovery contract
        (``OrphanedLeaseRecoveryRequest``). An uncontained attempt can never
        satisfy it.
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
    only a contained invocation (the launch path is removed under #3101
    invasive; retained for the host-local lease recovery contract) produces
    the recursive-emptiness and cgroup cleanup observations this evidence
    is built from.
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


COMPACT_EVIDENCE_SCHEMA_VERSION = 1


def compact_execution_evidence(result: PosixProcessExecutionResult) -> dict:
    """Project one execution result onto a compact, schema-versioned evidence dict.

    The framed summary that callers (dev-validation pilot, Codespaces
    adapters) consume instead of raw logs: outcome, bounded reason, output
    tails with truncation flags, and the containment attestation sub-block
    that makes the summary trustworthy without re-verification. It never
    claims the #759 cgroup proof: see ``guarantees_not_claimed``.
    """
    if type(result) is not PosixProcessExecutionResult:
        raise PosixProcessAdapterError("result must be an exact PosixProcessExecutionResult")
    return {
        "schema_version": COMPACT_EVIDENCE_SCHEMA_VERSION,
        "outcome": _outcome_for(result),
        "return_code": result.return_code,
        "termination_confirmed": result.termination_confirmed,
        "timeout_observed": result.timeout_observed,
        "cancellation_requested": result.cancellation_requested,
        "containment": {
            "venue": result.containment_venue,
            "cgroup_delegation_available": result.cgroup_delegation_available,
            "guarantees_claimed": list(result.guarantees_claimed or ()),
            "guarantees_not_claimed": list(result.guarantees_not_claimed or ()),
            "survivor_scan_performed": result.survivor_scan_performed,
            "survivor_count": result.survivor_count,
            "rlimits_applied": result.rlimits_applied,
        },
        "reason": result.reason,
        "stdout_tail": result.stdout_text,
        "stdout_truncated": result.stdout_truncated,
        "stderr_tail": result.stderr_text,
        "stderr_truncated": result.stderr_truncated,
    }


def _signal_group(pgid: int, sig: signal.Signals) -> str | None:
    """Signal exactly the invocation pgid captured at spawn.

    The pgid is passed in rather than re-derived from the child pid: once
    the direct child has exited and been reaped, ``os.getpgid(pid)`` raises
    ``ProcessLookupError`` and a re-derived lookup would silently skip the
    signal -- leaving pipe-holding descendants alive while the escalation
    believes it signaled them.
    """
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
    rlimits: Mapping[object, tuple[int, int]] | None = None,
) -> PosixProcessExecutionResult:
    """Run exactly one bounded POSIX process attempt and return its evidence.

    Uses ``selectors.DefaultSelector`` to drain stdout and stderr
    concurrently so neither stream can deadlock the other. On timeout or
    cancellation, signals the whole process group, waits a bounded grace
    period, escalates through one frozen policy (SIGTERM then SIGKILL), and
    always finishes the wait/reap before returning. Never reports
    termination as confirmed unless both the child's exit and the final
    drain/reap were directly observed. After a SIGKILL escalation, a
    ``/proc`` survivor scan proves zero live processes remain in the
    invocation pgid and raises ``PosixProcessSurvivorError`` fail-closed
    otherwise. Optional ``rlimits`` are lowered in the child before exec.
    Every result carries the venue attestation (``containment_venue`` of
    ``"process-group"`` with explicit claimed/not-claimed guarantees).
    """
    _require_posix()
    validated_argv = _validate_argv(argv)
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise PosixProcessAdapterError("timeout_seconds must be a positive number")
    if not isinstance(grace_period_seconds, (int, float)) or grace_period_seconds < 0:
        raise PosixProcessAdapterError("grace_period_seconds must not be negative")
    if not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
        raise PosixProcessAdapterError("max_output_bytes must be a positive integer")
    validated_rlimits = _validate_rlimits(rlimits)

    process: subprocess.Popen[bytes] = subprocess.Popen(  # noqa: S603 - argv validated above
        list(validated_argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        cwd=cwd,
        env=env,
        start_new_session=True,
        preexec_fn=(lambda: _apply_rlimits_in_child(validated_rlimits))
        if validated_rlimits
        else None,
    )
    # The pgid is the containment identity for this run: capture it now,
    # while the child is certainly still ours, and fail closed unless it
    # is a fresh group led by the child itself.
    try:
        pgid = os.getpgid(process.pid)
    except OSError as exc:
        _silent_kill(process)
        raise PosixProcessAdapterError(
            f"spawned child has no readable pgid: {exc}"
        ) from exc
    if pgid != process.pid:
        _silent_kill(process)
        raise PosixProcessAdapterError(
            f"child pgid {pgid} != child pid {process.pid}: not a fresh process group"
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
        survivor_scan_performed = False

        if not exited and (timeout_observed or cancellation_requested):
            signal_dispatched = _signal_group(pgid, signal.SIGTERM)
            grace_deadline = time.monotonic() + grace_period_seconds
            _, _, exited_after_term = _drain_until(
                process, selector, open_streams, grace_deadline, None, poll_interval_seconds
            )
            child_exit_observed = exited_after_term

            if not exited_after_term:
                escalation_dispatched = _signal_group(pgid, signal.SIGKILL) is not None
                kill_deadline = time.monotonic() + grace_period_seconds
                _, _, exited_after_kill = _drain_until(
                    process, selector, open_streams, kill_deadline, None, poll_interval_seconds
                )
                child_exit_observed = exited_after_kill
                # Prove zero live processes remain in the invocation pgid.
                # Fail closed: survivors (or an unlistable /proc) raise.
                survivor_scan_performed = True
                _assert_no_pgid_survivors(pgid, max(grace_period_seconds, 1.0))
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
        rlimits_applied=(
            {
                _rlimit_display_name(res): [soft, hard]
                for res, (soft, hard) in validated_rlimits.items()
            }
            or None
        ),
        containment_venue="process-group",
        cgroup_delegation_available=_cgroup_delegation_available(),
        guarantees_claimed=GUARANTEES_CLAIMED,
        guarantees_not_claimed=GUARANTEES_NOT_CLAIMED,
        survivor_scan_performed=survivor_scan_performed,
        survivor_count=0,
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
    rlimits: Mapping[object, tuple[int, int]] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", _validate_argv(self.argv))
        _validate_rlimits(self.rlimits)


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
            rlimits=self._config.rlimits,
        )
        self.last_result = result
        return _to_pilot_execution_observation(result)
