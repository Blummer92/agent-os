"""WSC-AUTO1C Linux cgroup v2 per-invocation process-tree containment.

Owns exactly: preflight probing of one exact delegated Agent OS parent
cgroup v2 subtree, creation/identity of one fresh invocation cgroup per
run, reading the kernel's own recursive whole-subtree emptiness proof
(``cgroup.events`` ``populated``), bounded escalation via the exact-scope
``cgroup.kill`` file, and cleanup of only that one empty invocation cgroup.

It performs no root escalation, no cgroup v1 access, no controller
tuning, no traversal of any cgroup outside the one invocation cgroup it
created, no container/namespace setup, and no retry. Every operation is
scoped to a single caller-identified invocation cgroup directory; nothing
here ever reads, kills, or removes a cgroup path it did not itself create
under the caller-supplied delegated parent.

All failures are typed and fail closed: a preflight failure or a
non-empty cleanup attempt raises rather than silently degrading to an
uncontained or partially-cleaned state.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

try:
    from workflow_scheduler.execution import _clone3_cgroup as _clone3_native
except ImportError:  # pragma: no cover - exercised only on unbuilt hosts
    _clone3_native = None

CGROUP_EVENTS_FILE = "cgroup.events"
CGROUP_KILL_FILE = "cgroup.kill"
CGROUP_PROCS_FILE = "cgroup.procs"

DEFAULT_POPULATED_POLL_INTERVAL_SECONDS = 0.02
DEFAULT_POPULATED_WAIT_SECONDS = 5.0


class CgroupV2ContainmentError(RuntimeError):
    """Base class for every containment failure. Always fail closed."""


class CgroupV2PreflightError(CgroupV2ContainmentError):
    """Raised when the delegated cgroup v2 containment surface is unusable.

    Raised before any process is spawned; never raised mid-launch.
    """


class CgroupV2CreateError(CgroupV2ContainmentError):
    """The one fresh per-invocation cgroup directory could not be created."""


class CgroupV2NotEmptyError(CgroupV2ContainmentError):
    """Cleanup was attempted on a cgroup that is not (yet) recursively empty.

    Never silently ignored: the invocation cgroup is left in place for
    manual/quarantine review instead of being force-removed.
    """


class CgroupV2CleanupError(CgroupV2ContainmentError):
    """The empty invocation cgroup directory could not be removed."""


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _cgroup2_mounted(delegated_parent_cgroup: str) -> bool:
    """True only if ``delegated_parent_cgroup`` is inside a real cgroup2 mount.

    Detected the same way the kernel documents cgroup v2 identification:
    the mount point directory contains ``cgroup.controllers`` (a file that
    exists only on a cgroup2 hierarchy, never on cgroup v1).
    """
    controllers_path = os.path.join(delegated_parent_cgroup, "cgroup.controllers")
    return os.path.isfile(controllers_path)


def _clone3_available() -> bool:
    if _clone3_native is None:
        return False
    try:
        return bool(_clone3_native.probe())
    except OSError:
        return False


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainmentPreflightResult:
    """Bounded, immutable evidence for one preflight probe.

    ``supported`` is the single fail-closed gate: any caller must refuse
    to spawn an uncontained process when it is ``False``.
    """

    supported: bool
    delegated_parent_cgroup: str
    cgroup_v2_mounted: bool
    delegated_parent_exists: bool
    can_create_and_remove_child: bool
    clone3_extension_loaded: bool
    clone3_syscall_supported: bool
    cgroup_events_readable: bool
    cgroup_kill_writable: bool
    reason: str = ""


def preflight_check(delegated_parent_cgroup: str) -> ContainmentPreflightResult:
    """Probe every containment precondition without leaving side effects.

    Performed once, before any validation launch is attempted. A single
    disposable probe child cgroup is created and immediately removed again
    to prove create/remove rights; nothing else under
    ``delegated_parent_cgroup`` is touched.
    """
    reasons: list[str] = []

    cgroup_v2_mounted = _cgroup2_mounted(delegated_parent_cgroup)
    if not cgroup_v2_mounted:
        reasons.append("delegated parent is not on a mounted cgroup v2 hierarchy")

    delegated_parent_exists = os.path.isdir(delegated_parent_cgroup)
    if not delegated_parent_exists:
        reasons.append("delegated parent cgroup directory does not exist")

    can_create_and_remove_child = False
    cgroup_events_readable = False
    cgroup_kill_writable = False
    if cgroup_v2_mounted and delegated_parent_exists:
        probe_path = os.path.join(
            delegated_parent_cgroup, f".agentos-preflight-probe-{os.getpid()}"
        )
        try:
            os.mkdir(probe_path)
            can_create_and_remove_child = True
            events_path = os.path.join(probe_path, CGROUP_EVENTS_FILE)
            kill_path = os.path.join(probe_path, CGROUP_KILL_FILE)
            try:
                cgroup_events_readable = "populated" in _read_text(events_path)
            except OSError:
                cgroup_events_readable = False
            try:
                cgroup_kill_writable = os.access(kill_path, os.W_OK)
            except OSError:
                cgroup_kill_writable = False
            os.rmdir(probe_path)
        except OSError as exc:
            reasons.append(f"cannot create/remove a probe child cgroup: {exc}")
            try:
                os.rmdir(probe_path)
            except OSError:
                pass

    clone3_extension_loaded = _clone3_native is not None
    if not clone3_extension_loaded:
        reasons.append("the _clone3_cgroup native extension is not built/importable")

    clone3_syscall_supported = _clone3_available()
    if clone3_extension_loaded and not clone3_syscall_supported:
        reasons.append("this kernel does not implement the clone3() syscall")

    supported = (
        cgroup_v2_mounted
        and delegated_parent_exists
        and can_create_and_remove_child
        and clone3_extension_loaded
        and clone3_syscall_supported
        and cgroup_events_readable
        and cgroup_kill_writable
    )

    return ContainmentPreflightResult(
        supported=supported,
        delegated_parent_cgroup=delegated_parent_cgroup,
        cgroup_v2_mounted=cgroup_v2_mounted,
        delegated_parent_exists=delegated_parent_exists,
        can_create_and_remove_child=can_create_and_remove_child,
        clone3_extension_loaded=clone3_extension_loaded,
        clone3_syscall_supported=clone3_syscall_supported,
        cgroup_events_readable=cgroup_events_readable,
        cgroup_kill_writable=cgroup_kill_writable,
        reason="; ".join(reasons),
    )


class InvocationCgroup:
    """One fresh, exact-scope cgroup v2 directory for exactly one invocation.

    Every method here operates only on the single directory this instance
    was constructed with. No parent, sibling, or unrelated cgroup path is
    ever read, signaled, or removed.
    """

    __slots__ = ("path", "_fd", "_closed")

    def __init__(self, path: str, fd: int) -> None:
        self.path = path
        self._fd = fd
        self._closed = False

    @classmethod
    def create(cls, delegated_parent_cgroup: str, invocation_id: str) -> "InvocationCgroup":
        if "/" in invocation_id or ".." in invocation_id or not invocation_id:
            raise CgroupV2CreateError("invocation_id must be a single safe path segment")
        path = os.path.join(delegated_parent_cgroup, f"wsc-invocation-{invocation_id}")
        try:
            os.mkdir(path)
        except OSError as exc:
            raise CgroupV2CreateError(f"could not create invocation cgroup {path}: {exc}") from exc
        try:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        except OSError as exc:
            try:
                os.rmdir(path)
            except OSError:
                pass
            raise CgroupV2CreateError(f"could not open invocation cgroup {path}: {exc}") from exc
        return cls(path=path, fd=fd)

    @property
    def fd(self) -> int:
        return self._fd

    def _events_path(self) -> str:
        return os.path.join(self.path, CGROUP_EVENTS_FILE)

    def _kill_path(self) -> str:
        return os.path.join(self.path, CGROUP_KILL_FILE)

    def read_populated(self) -> bool:
        """True if this cgroup or any descendant still contains a live process.

        This is the kernel's own recursive whole-subtree proof (the
        ``cgroup.events`` ``populated`` field is defined by the kernel to
        cover the cgroup and every descendant, not just direct children),
        so no separate ``/proc`` walk is layered on top of it.
        """
        try:
            text = _read_text(self._events_path())
        except OSError as exc:
            raise CgroupV2ContainmentError(
                f"cgroup.events unreadable for {self.path}: {exc}"
            ) from exc
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "populated":
                return parts[1] != "0"
        raise CgroupV2ContainmentError(
            f"malformed cgroup.events for {self.path}: {text!r}"
        )

    def wait_until_empty(
        self,
        deadline_seconds: float = DEFAULT_POPULATED_WAIT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POPULATED_POLL_INTERVAL_SECONDS,
    ) -> bool:
        """Poll ``cgroup.events`` until recursively empty or the deadline passes."""
        deadline = time.monotonic() + deadline_seconds
        while True:
            if not self.read_populated():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(poll_interval_seconds)

    def kill(self) -> None:
        """Recursively SIGKILL every process in this cgroup, exact-scope only."""
        try:
            with open(self._kill_path(), "w", encoding="utf-8") as handle:
                handle.write("1")
        except OSError as exc:
            raise CgroupV2ContainmentError(
                f"cgroup.kill write failed for {self.path}: {exc}"
            ) from exc

    def cleanup(self) -> bool:
        """Remove this invocation cgroup. Refuses (raises) if not recursively empty.

        Returns ``True`` only once the directory has both been rmdir'd and
        directly confirmed gone. Never removes a non-empty cgroup.
        """
        if self.read_populated():
            raise CgroupV2NotEmptyError(
                f"refusing to remove non-empty invocation cgroup {self.path}"
            )
        try:
            os.rmdir(self.path)
        except OSError as exc:
            raise CgroupV2CleanupError(f"rmdir failed for {self.path}: {exc}") from exc
        if os.path.exists(self.path):
            raise CgroupV2CleanupError(f"{self.path} still exists after rmdir")
        return True

    def close(self) -> None:
        if not self._closed:
            os.close(self._fd)
            self._closed = True

    def __enter__(self) -> "InvocationCgroup":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
