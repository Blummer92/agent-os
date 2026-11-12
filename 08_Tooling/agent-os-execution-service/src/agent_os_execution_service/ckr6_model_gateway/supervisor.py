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
import subprocess
import sys
import threading
from pathlib import Path
from typing import Mapping, Sequence

_LAUNCHER = str(Path(__file__).with_name("_isolated_exec.py"))
_READY_TIMEOUT_SECONDS = 30.0


class IsolationUnavailable(RuntimeError):
    """The host cannot isolate a worker; starting one anyway would be an unenforced boundary."""


class UidAllocator:
    """Hands out each uid at most once per allocator, so no two workers ever share one.

    Supervisors running in different processes MUST be given disjoint ranges."""

    def __init__(self, start: int | None = None, count: int = 1_000_000) -> None:
        self._next = start if start is not None else 1_000_000 + secrets.randbelow(2_000_000_000)
        self._end = self._next + count
        self._lock = threading.Lock()

    def allocate(self) -> int:
        with self._lock:
            if self._next >= self._end:
                raise IsolationUnavailable("worker-uid-range-exhausted")
            uid, self._next = self._next, self._next + 1
            return uid


_DEFAULT_ALLOCATOR = UidAllocator()
_PRIVILEGED: bool | None = None


def isolation_available() -> bool:
    """Capability probe only (root + unshare). The authoritative check is the per-spawn readiness handshake."""
    global _PRIVILEGED
    if _PRIVILEGED is None:
        _PRIVILEGED = os.geteuid() == 0 and hasattr(os, "unshare")
    return _PRIVILEGED


def spawn_isolated_worker(argv: Sequence[str], *, pass_fds: Sequence[int] = (), env: Mapping[str, str] | None = None,
                          cwd: str | None = None, allocator: UidAllocator | None = None) -> subprocess.Popen:
    if not argv or not isolation_available():
        raise IsolationUnavailable("host-cannot-isolate-worker")
    uid = (allocator or _DEFAULT_ALLOCATOR).allocate()
    read_fd, write_fd = os.pipe()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", _LAUNCHER, str(uid), str(write_fd), "--", *argv],
            env={"PATH": "/usr/bin:/bin", **(env or {})}, cwd=cwd, close_fds=True,
            pass_fds=(write_fd, *pass_fds), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
    return proc
