"""WSC0/#3200 process-group containment: the lighter sibling of #759.

For execution venues where cgroup v2 delegation is unavailable (for
example Codespaces containers, which mount ``/sys/fs/cgroup`` read-only),
the #759 cgroup proof is unproducible. This module owns exactly:
preflight probing of process-group creation and rlimit lowering, one
fresh process group per invocation (the child becomes a session and
process-group leader via ``Popen(start_new_session=True)`` so
``pgid == child pid``), bounded ``SIGTERM``-then-``SIGKILL`` escalation
scoped to that one pgid, a ``/proc`` survivor scan proving zero live
processes remain in the pgid, direct-child ``waitpid`` reap, final pipe
drain, and a containment record carrying an explicit venue capability
attestation (cgroup delegation reported as unavailable; the #759-grade
guarantees listed as not claimed).

It performs no cgroup filesystem access at all, no root/capability
escalation, no daemon or persistent process, no network access, and no
retry. Every operation is scoped to the single pgid this instance
launched; nothing here ever signals, scans for, or reaps a process
outside it.

All failures are typed and fail closed: a preflight failure, a surviving
live process after ``SIGKILL``, or a reap/drain failure raises rather
than silently degrading to an uncontained or partially-evidenced state.

Known limitation, stated rather than hidden: a descendant that calls
``setsid()`` (or otherwise changes its process group) leaves the
invocation pgid and is then unreachable by ``killpg``. That escape is one
of the #759-grade guarantees this variant explicitly does not claim (see
the attestation block); venues that need it must use ``cgroup_v2_containment``.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Mapping

try:
    import resource as _resource
except ImportError:  # pragma: no cover - non-POSIX hosts fail preflight
    _resource = None

DEFAULT_TERMINATE_GRACE_SECONDS = 5.0
DEFAULT_SURVIVOR_SETTLE_SECONDS = 2.0
DEFAULT_DRAIN_TIMEOUT_SECONDS = 10.0
CGROUP2_MOUNT_CANDIDATES = ("/sys/fs/cgroup", "/sys/fs/cgroup/unified")

# The #759-grade guarantees this lighter variant explicitly does NOT claim.
# Surfaced verbatim in every containment record's attestation block: no
# silent downgrade from the cgroup proof to the process-group proof.
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


class ProcessGroupContainmentError(RuntimeError):
    """Base class for every process-group containment failure. Always fail closed."""


class ProcessGroupPreflightError(ProcessGroupContainmentError):
    """Raised when the process-group containment surface is unusable.

    Raised before any process is spawned; never raised mid-launch.
    """


class ProcessGroupLaunchError(ProcessGroupContainmentError):
    """The invocation process could not be spawned in a fresh process group."""


class ProcessGroupTerminateError(ProcessGroupContainmentError):
    """Signaling or scanning the invocation process group failed mid-termination."""


class ProcessGroupSurvivorError(ProcessGroupContainmentError):
    """Live processes remained in the invocation pgid after SIGKILL escalation.

    Never silently ignored: the surviving pids are reported and the caller
    must route to manual review/quarantine.
    """


class ProcessGroupReapError(ProcessGroupContainmentError):
    """The direct child could not be reaped, or the final pipe drain failed."""


def _resolve_rlimit_key(key: object) -> int:
    """Resolve an rlimit key to a ``resource.RLIMIT_*`` constant.

    Accepts the constant itself or its exact name (``"RLIMIT_NPROC"``).
    Anything else fails closed at launch time, never silently skipped.
    """
    if _resource is None:  # pragma: no cover - preflight already failed
        raise ProcessGroupLaunchError("the resource module is unavailable")
    if isinstance(key, int) and not isinstance(key, bool):
        return key
    if isinstance(key, str):
        resolved = getattr(_resource, key, None)
        if isinstance(resolved, int) and not isinstance(resolved, bool):
            return resolved
    raise ProcessGroupLaunchError(f"unknown rlimit key: {key!r}")


def _validate_rlimits(rlimits: Mapping[object, tuple] | None) -> dict[int, tuple[int, int]]:
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
            raise ProcessGroupLaunchError(
                f"rlimit {key!r} must map to a (soft, hard) int pair, got {bounds!r}"
            )
        soft, hard = int(bounds[0]), int(bounds[1])
        if soft < -1 or hard < -1:
            raise ProcessGroupLaunchError(
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


def _cgroup_delegation_available() -> bool:
    """Actively probe for a writable cgroup v2 subtree.

    Reports True only if a cgroup2 mount exists AND a probe directory can
    be created and removed inside it. In container venues (read-only
    ``/sys/fs/cgroup``) this reports False -- which the lighter variant
    records honestly in its attestation instead of treating as fatal.
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


def _raw_status_from_returncode(returncode: int) -> int:
    """Convert a ``Popen.returncode``-convention value to a raw waitpid status.

    Needed when the child was reaped through ``Popen.wait()`` (which stores
    the negative-for-signal convention) instead of our own ``os.waitpid``
    loop: the evidence record always reports the raw status so
    ``WIFEXITED``/``WIFSIGNALED`` decode it identically either way.
    """
    if returncode < 0:
        return -returncode  # signal number in the low bits: WTERMSIG decodes it
    return returncode << 8


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
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _proc_filesystem_usable() -> tuple[bool, str]:
    """/proc must be listable: the survivor scan has no pgrep fallback."""
    try:
        entries = os.listdir("/proc")
    except OSError as exc:
        return False, f"/proc is not listable: {exc}"
    if not any(entry.isdigit() for entry in entries):
        return False, "/proc contains no numeric pid entries"
    return True, ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainmentPreflightResult:
    """Bounded, immutable evidence for one preflight probe.

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


def preflight_check() -> ContainmentPreflightResult:
    """Probe every lighter-containment precondition without side effects.

    Fails closed: ``usable`` is True only on a POSIX host where a fresh
    process group can actually be created, rlimits can be lowered, and
    ``/proc`` is listable for the survivor scan. The probe child exits
    immediately and is reaped; nothing persists.
    """
    reasons: list[str] = []

    if os.name != "posix":
        reasons.append(f"not a POSIX host (os.name={os.name!r})")

    setpgid_available = False
    if os.name == "posix":
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
        os.name == "posix"
        and setpgid_available
        and rlimit_available
        and proc_usable
    )
    return ContainmentPreflightResult(
        usable=usable,
        reason="; ".join(reasons),
        cgroup_delegation_available=cgroup_delegation_available,
        setpgid_available=setpgid_available,
        rlimit_available=rlimit_available,
    )


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


def pgid_live_survivors(pgid: int) -> list[int]:
    """Pids still alive in ``pgid``, excluding zombies.

    A zombie (state ``Z``) is already dead; reaping it is its parent's
    (init's, after reparenting) job, not this module's. Only live
    processes count as survivors.
    """
    survivors: list[int] = []
    try:
        entries = os.listdir("/proc")
    except OSError as exc:
        raise ProcessGroupTerminateError(f"survivor scan could not list /proc: {exc}") from exc
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


class InvocationProcessGroup:
    """One fresh process group for exactly one invocation.

    The child is spawned as a session and process-group leader
    (``start_new_session=True``), so the pgid equals the child pid and is
    the containment identity for the run. Every method operates only on
    that one pgid; no process outside it is ever signaled, scanned for, or
    reaped.
    """

    __slots__ = (
        "invocation_id",
        "_proc",
        "_pgid",
        "_rlimits",
        "_rlimit_names",
        "_launch_ts",
        "_sigterm_ts",
        "_sigkill_ts",
        "_exit_status",
        "_reaped",
        "_drain_status",
        "_stdout_tail",
        "_stderr_tail",
    )

    def __init__(
        self,
        invocation_id: str,
        proc: subprocess.Popen,
        pgid: int,
        rlimits: dict[int, tuple[int, int]],
        rlimit_names: dict[int, str],
        launch_ts: float,
    ) -> None:
        self.invocation_id = invocation_id
        self._proc = proc
        self._pgid = pgid
        self._rlimits = rlimits
        self._rlimit_names = rlimit_names
        self._launch_ts = launch_ts
        self._sigterm_ts: float | None = None
        self._sigkill_ts: float | None = None
        self._exit_status: int | None = None
        self._reaped = False
        self._drain_status = "pending"
        self._stdout_tail = b""
        self._stderr_tail = b""

    @classmethod
    def launch(
        cls,
        argv: list[str],
        rlimits: Mapping[object, tuple] | None = None,
        invocation_id: str = "",
    ) -> "InvocationProcessGroup":
        """Spawn ``argv`` as a fresh process-group leader. Fail closed on any failure."""
        if "/" in invocation_id or ".." in invocation_id or not invocation_id:
            raise ProcessGroupLaunchError("invocation_id must be a single safe path segment")
        if not argv:
            raise ProcessGroupLaunchError("argv must be non-empty")
        validated = _validate_rlimits(rlimits)
        rlimit_names = {res: _rlimit_display_name(res) for res in validated}
        launch_ts = time.time()
        try:
            proc = subprocess.Popen(
                argv,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=(lambda: _apply_rlimits_in_child(validated)) if validated else None,
            )
        except OSError as exc:
            raise ProcessGroupLaunchError(f"could not spawn {argv[0]!r}: {exc}") from exc
        try:
            pgid = os.getpgid(proc.pid)
        except OSError as exc:
            _silent_kill(proc)
            raise ProcessGroupLaunchError(
                f"spawned child {proc.pid} has no readable pgid: {exc}"
            ) from exc
        if pgid != proc.pid:
            _silent_kill(proc)
            raise ProcessGroupLaunchError(
                f"child pgid {pgid} != child pid {proc.pid}: not a fresh process group"
            )
        return cls(
            invocation_id=invocation_id,
            proc=proc,
            pgid=pgid,
            rlimits=validated,
            rlimit_names=rlimit_names,
            launch_ts=launch_ts,
        )

    @property
    def pgid(self) -> int:
        return self._pgid

    @property
    def pid(self) -> int:
        return self._proc.pid

    def _signal_group(self, signum: int) -> None:
        try:
            os.killpg(self._pgid, signum)
        except ProcessLookupError:
            # The whole group is already gone: nothing to signal.
            return
        except (PermissionError, OSError) as exc:
            raise ProcessGroupTerminateError(
                f"killpg({self._pgid}, {signum}) failed: {exc}"
            ) from exc

    def _adopt_popen_returncode(self) -> None:
        """Adopt a status for a child Popen already reaped (e.g. via communicate()).

        Converts the ``Popen.returncode`` convention to the raw waitpid
        status so the evidence record decodes identically either way.
        """
        returncode = self._proc.returncode
        if returncode is None:
            raise ProcessGroupReapError(
                f"child pid {self._proc.pid} is not reaped and not a child of this process"
            )
        self._exit_status = _raw_status_from_returncode(returncode)
        self._reaped = True

    def _wait_child(self, timeout: float) -> bool:
        """Reap the direct child if it exits within ``timeout``.

        A ``waitpid`` loop; the raw kernel status is kept in
        ``_exit_status`` so ``WIFEXITED``/``WIFSIGNALED`` decode it
        faithfully. Never touches ``Popen.wait()`` so the two reaping
        paths cannot disagree.
        """
        if self._reaped:
            return True
        pid = self._proc.pid
        deadline = time.monotonic() + timeout
        while True:
            try:
                waited_pid, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                self._adopt_popen_returncode()
                return True
            if waited_pid == pid:
                self._exit_status = status
                self._reaped = True
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def terminate(
        self,
        grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS,
        settle_seconds: float = DEFAULT_SURVIVOR_SETTLE_SECONDS,
    ) -> None:
        """SIGTERM the invocation pgid, escalate to SIGKILL, prove zero survivors.

        Raises ``ProcessGroupSurvivorError`` if any live process remains in
        the pgid after escalation -- never silently ignored.
        """
        if grace_seconds < 0 or settle_seconds < 0:
            raise ProcessGroupTerminateError("grace_seconds and settle_seconds must be >= 0")
        if self._reaped:
            # The direct child was already reaped (e.g. an explicit reap()
            # by the caller): nothing left to signal -- just prove the
            # group has no live survivors.
            self._assert_no_survivors(settle_seconds)
            return
        self._sigterm_ts = time.time()
        self._signal_group(signal.SIGTERM)
        child_gone = self._wait_child(grace_seconds)
        if child_gone and not pgid_live_survivors(self._pgid):
            return
        # Either the direct child survived the grace period or a descendant
        # is still alive in the pgid: escalate once, then prove zero live
        # survivors. Anything left after that fails closed.
        self._sigkill_ts = time.time()
        self._signal_group(signal.SIGKILL)
        self._wait_child(max(settle_seconds, 1.0))
        self._assert_no_survivors(settle_seconds)

    def _assert_no_survivors(self, settle_seconds: float) -> None:
        deadline = time.monotonic() + settle_seconds
        survivors = pgid_live_survivors(self._pgid)
        while survivors and time.monotonic() < deadline:
            time.sleep(0.02)
            survivors = pgid_live_survivors(self._pgid)
        if survivors:
            raise ProcessGroupSurvivorError(
                f"{len(survivors)} live process(es) survived SIGKILL in pgid {self._pgid}: "
                f"{survivors}; route to manual review/quarantine"
            )

    def reap(self) -> None:
        """Blocking ``waitpid`` loop reaping the direct child. Fail closed if unreapable."""
        if self._reaped:
            return
        pid = self._proc.pid
        try:
            waited_pid, status = os.waitpid(pid, 0)
        except ChildProcessError:
            # Popen.wait()/communicate() (e.g. inside drain()) reaped it first.
            self._adopt_popen_returncode()
            return
        except OSError as exc:
            raise ProcessGroupReapError(f"waitpid({pid}) failed: {exc}") from exc
        if waited_pid == pid:
            self._exit_status = status
            self._reaped = True

    def drain(self, timeout: float = DEFAULT_DRAIN_TIMEOUT_SECONDS) -> None:
        """Read remaining stdout/stderr to completion. The child is already
        reaped by now, so EOF is guaranteed unless a descendant escaped the
        pgid holding a pipe open -- which fails closed here."""
        if self._drain_status == "complete":
            return
        try:
            stdout, stderr = self._proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ProcessGroupReapError(
                "pipe drain timed out: a descendant may hold the pipe open outside the pgid"
            ) from exc
        self._stdout_tail = stdout if stdout is not None else b""
        self._stderr_tail = stderr if stderr is not None else b""
        self._drain_status = "complete"

    def _reap_status(self) -> str:
        if not self._reaped or self._exit_status is None:
            return "not-reaped"
        status = self._exit_status
        if os.WIFEXITED(status):
            return f"reaped:exited:{os.WEXITSTATUS(status)}"
        if os.WIFSIGNALED(status):
            return f"reaped:signaled:{os.WTERMSIG(status)}"
        return f"reaped:status:{status}"

    def containment_record(self) -> dict:
        """The per-run evidence record, including the explicit attestation.

        ``survivor_scan`` is 0 only after ``terminate()`` proved it;
        ``attestation`` states what this venue cannot prove so no caller
        can mistake this record for the #759 cgroup proof.
        """
        try:
            survivors = pgid_live_survivors(self._pgid)
        except ProcessGroupContainmentError:
            survivors = ["scan-failed"]
        return {
            "invocation_id": self.invocation_id,
            "pgid": self._pgid,
            "pid": self._proc.pid,
            "rlimits_applied": {
                self._rlimit_names.get(res, str(res)): [soft, hard]
                for res, (soft, hard) in self._rlimits.items()
            },
            "launch_ts": self._launch_ts,
            "sigterm_ts": self._sigterm_ts,
            "sigkill_ts": self._sigkill_ts,
            "survivor_scan": 0 if survivors == [] else survivors,
            "reap_status": self._reap_status(),
            "drain_status": self._drain_status,
            "attestation": {
                "venue": "process-group",
                "cgroup_delegation": "unavailable",
                "guarantees_claimed": list(GUARANTEES_CLAIMED),
                "guarantees_not_claimed": list(GUARANTEES_NOT_CLAIMED),
            },
        }

    def __enter__(self) -> "InvocationProcessGroup":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        # Ordering is the contract: terminate, then reap, then drain.
        # Never suppresses the caller's exception; a containment failure
        # here raises (fail closed) and chains onto it.
        self.terminate()
        self.reap()
        self.drain()


def _silent_kill(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass
