"""Spawn untrusted workers WITHOUT a model capability (and fail closed if that is impossible).

Enforced here (observed by tests when the host is privileged): empty network
namespace, unprivileged uid with no way back to root, no_new_privs, scrubbed
environment, only the listed fds inherited, no credential, no backend handle.

NOT enforced here: seccomp, cgroup limits, filesystem namespace. A worker that
can become root, or an operator with host access, is outside this boundary.
If isolation cannot be established the worker is NOT started (``IsolationUnavailable``).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

NOBODY = 65534
_LAUNCHER = str(Path(__file__).with_name("_isolated_exec.py"))
_PROBED: bool | None = None


class IsolationUnavailable(RuntimeError):
    """The host cannot isolate a worker; starting one anyway would be an unenforced boundary."""


def _launch(argv: Sequence[str], *, pass_fds: Sequence[int], env: Mapping[str, str], cwd: str | None,
            uid: int) -> subprocess.Popen:
    clean = {"PATH": "/usr/bin:/bin", **env}
    return subprocess.Popen(
        [sys.executable, "-I", _LAUNCHER, str(uid), "--", *argv], env=clean, cwd=cwd, close_fds=True,
        pass_fds=tuple(pass_fds), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def isolation_available(uid: int = NOBODY) -> bool:
    global _PROBED
    if _PROBED is None:
        if os.geteuid() != 0 or not hasattr(os, "unshare"):
            _PROBED = False
        else:
            probe = _launch([sys.executable, "-I", "-c", "pass"], pass_fds=(), env={}, cwd="/", uid=uid)
            probe.communicate(timeout=30)
            _PROBED = probe.returncode == 0
    return _PROBED


def spawn_isolated_worker(argv: Sequence[str], *, pass_fds: Sequence[int] = (), env: Mapping[str, str] | None = None,
                          cwd: str | None = None, uid: int = NOBODY) -> subprocess.Popen:
    if not isolation_available(uid):
        raise IsolationUnavailable("host-cannot-isolate-worker")
    return _launch(argv, pass_fds=pass_fds, env=env or {}, cwd=cwd, uid=uid)
