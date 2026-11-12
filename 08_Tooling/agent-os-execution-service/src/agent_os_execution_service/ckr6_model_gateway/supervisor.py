"""Spawn untrusted workers WITHOUT a model capability (and fail closed if that is impossible).

Enforced here (observed by tests when the host is privileged): empty network
namespace, a UNIQUE unprivileged uid per worker with no way back to root (so
one worker cannot read, ptrace, or ``pidfd_getfd`` another worker's gateway
socket), no_new_privs, scrubbed environment, only the listed fds inherited, no
credential, no backend handle. The worker is started only after the launcher
reports every check passed; otherwise ``IsolationUnavailable`` is raised.

NOT enforced here: seccomp, cgroup limits, filesystem/PID/mount namespaces. A
worker can still connect to any filesystem AF_UNIX socket its uid may open, so a
provider or credential proxy must never be exposed that way. A worker that can
become root, or an operator with host access, is outside this boundary.
"""
from __future__ import annotations

import os
import secrets
import select
import socket
import subprocess
import sys
import threading
import weakref
from pathlib import Path
from typing import Mapping, Sequence

_LAUNCHER = str(Path(__file__).with_name("_isolated_exec.py"))
_READY_TIMEOUT_SECONDS = 30.0


class IsolationUnavailable(RuntimeError):
    """The host cannot isolate a worker; starting one anyway would be an unenforced boundary."""


def _uid_in_use_by_live_process(uid: int) -> bool:
    """True if ANY process on the host runs with this real/effective/saved uid."""
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/status", "rb") as fh:
                for line in fh:
                    if line.startswith(b"Uid:"):
                        if uid in {int(x) for x in line.split()[1:]}:
                            return True
                        break
        except OSError:
            continue  # process exited
    return False


def _uid_is_unassigned(uid: int) -> bool:
    import pwd
    try:
        pwd.getpwuid(uid)
    except KeyError:
        return True
    return False


class _Claim:
    """Exclusive claim on one uid, held until released (or the process dies)."""

    def __init__(self, sock: socket.socket | None) -> None:
        self._sock = sock

    def release(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None


def claim_uid(uid: int) -> _Claim:
    """Kernel-enforced exclusivity keyed ONLY by the uid: bind an abstract AF_UNIX name. It needs no
    filesystem state (so it cannot depend on which state dir a supervisor was configured with), is
    visible to every supervisor process and fork in this network namespace, covers the launch window
    in which a worker has not yet dropped to its uid (invisible to /proc), is freed automatically if the
    holder dies, and cannot be squatted by a worker, which lives in an EMPTY network namespace."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(b"\0agent-os-ckr6-worker-uid-" + str(uid).encode())
    except OSError:
        sock.close()
        raise IsolationUnavailable("worker-uid-in-use") from None
    return _Claim(sock)


class InProcessUidAllocator:
    """Unique within ONE process only (tests). NOT safe across fork or processes: use ``UidAllocator``."""

    def __init__(self, start: int, count: int) -> None:
        self._next, self._end, self._lock = start, start + count, threading.Lock()

    def allocate(self) -> int:
        with self._lock:
            if self._next >= self._end:
                raise IsolationUnavailable("worker-uid-range-exhausted")
            uid, self._next = self._next, self._next + 1
            return uid


DEFAULT_STATE_DIR = "/run/agent-os-ckr6-uid-alloc"


class UidAllocator:
    """Host-wide uid allocation shared by EVERY supervisor process (and fork) that uses the same
    ``state_dir``: a flock'd counter hands out each uid once; exclusivity while a worker lives is ``claim_uid`` (an
    abstract-socket bind, independent of this directory), so even supervisors configured with DIFFERENT
    state dirs or overlapping ranges cannot put two live workers on one uid (the supervisors must share a
    network namespace and uid space). The state dir must be a real directory
    owned by the supervisor's uid with mode 0700 (so a worker can neither read nor tamper with it)."""

    def __init__(self, state_dir: str = DEFAULT_STATE_DIR, *, start: int = 3_000_000_000,
                 count: int = 1_000_000_000) -> None:
        self._dir, self._start, self._end = state_dir, start, start + count
        try:
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            st = os.lstat(state_dir)
            if os.path.realpath(state_dir) != os.path.abspath(state_dir):  # symlink anywhere in the path
                raise IsolationUnavailable("uid-state-dir-untrusted")
        except OSError:
            raise IsolationUnavailable("uid-state-dir-unavailable") from None
        import stat
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise IsolationUnavailable("uid-state-dir-untrusted")

    def _open(self, name: str) -> int:
        return os.open(os.path.join(self._dir, name), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)

    def allocate(self) -> int:
        import fcntl
        try:
            fd = self._open("counter")
        except OSError:
            raise IsolationUnavailable("uid-counter-unavailable") from None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            raw = os.pread(fd, 32, 0).strip()
            try:
                nxt = int(raw) if raw else self._start
            except ValueError:
                raise IsolationUnavailable("uid-counter-corrupt") from None
            if nxt < self._start or nxt >= self._end:
                raise IsolationUnavailable("worker-uid-range-exhausted")
            os.pwrite(fd, str(nxt + 1).encode().ljust(32), 0)
            os.fsync(fd)
            return nxt
        finally:
            os.close(fd)  # releases the flock


_DEFAULT_ALLOCATOR: UidAllocator | None = None
_PRIVILEGED: bool | None = None


def _default_allocator() -> UidAllocator:
    global _DEFAULT_ALLOCATOR
    if _DEFAULT_ALLOCATOR is None:
        _DEFAULT_ALLOCATOR = UidAllocator()
    return _DEFAULT_ALLOCATOR


def isolation_available() -> bool:
    """Capability probe only (root + unshare). The authoritative check is the per-spawn readiness handshake."""
    global _PRIVILEGED
    if _PRIVILEGED is None:
        _PRIVILEGED = os.geteuid() == 0 and hasattr(os, "unshare")
    return _PRIVILEGED


def spawn_isolated_worker(argv: Sequence[str], *, pass_fds: Sequence[int] = (), env: Mapping[str, str] | None = None,
                          cwd: str | None = None, allocator=None) -> subprocess.Popen:
    if not argv or not isolation_available():
        raise IsolationUnavailable("host-cannot-isolate-worker")
    allocator = allocator or _default_allocator()
    uid = allocator.allocate()
    claim = claim_uid(uid)  # exclusive across every supervisor process and fork, from allocation through launch
    try:
        if (type(uid) is not int or not 0 < uid < 2**32 - 1 or _uid_in_use_by_live_process(uid)
                or not _uid_is_unassigned(uid)):
            raise IsolationUnavailable("worker-uid-in-use")
        read_fd, write_fd = os.pipe()
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", _LAUNCHER, str(uid), str(write_fd), "--", *argv],
                env={"PATH": "/usr/bin:/bin", **(env or {})}, cwd=cwd, close_fds=True, start_new_session=True,
                pass_fds=(write_fd, *pass_fds), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        except Exception:
            os.close(read_fd); os.close(write_fd)
            raise
        os.close(write_fd)
        try:
            ready, _, _ = select.select([read_fd], [], [], _READY_TIMEOUT_SECONDS)
            signalled = bool(ready) and os.read(read_fd, 1) == b"R"
        finally:
            os.close(read_fd)
        if not signalled:
            proc.kill()
            proc.communicate()
            raise IsolationUnavailable("host-cannot-isolate-worker")
    except BaseException:
        claim.release()
        raise
    # The claim lives as long as the Popen object; /proc is re-checked at the next claim in any case.
    weakref.finalize(proc, claim.release)
    proc.aos_uid = uid  # type: ignore[attr-defined]
    return proc
