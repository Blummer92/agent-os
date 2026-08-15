"""WSC-AUTO1C Python-side wrapper around the ``_clone3_cgroup`` C extension.

Owns exactly: translating a validated launch request into the native
``spawn()`` call, and translating its result (or the native extension's
absence) into typed Python exceptions. No shell, no argv construction from
untrusted strings, no networking, no credential handling, no persistence,
no scheduler/workflow behavior, and no fallback to any other launch
mechanism (plain ``subprocess.Popen``/``posix_spawn`` plus later
``cgroup.procs`` migration, or ``preexec_fn``) live here or anywhere in
this launch path.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from workflow_scheduler.execution import _clone3_cgroup as _native
except ImportError:  # pragma: no cover - exercised only on unbuilt hosts
    _native = None

EXTENSION_AVAILABLE = _native is not None


class Clone3LaunchError(RuntimeError):
    """Base class for every clone3-cgroup launch failure."""


class Clone3UnavailableError(Clone3LaunchError):
    """The native extension is not built/importable, or clone3() is unsupported.

    Raised before any process is spawned. There is no fallback launch path
    for this error -- the caller must fail closed.
    """


class Clone3SyscallError(Clone3LaunchError):
    """The clone3() syscall itself failed; no child process was created."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Clone3LaunchRequest:
    """One bounded, fully-materialized request to launch directly into a cgroup."""

    argv: tuple[str, ...]
    cwd: str | None
    env: dict[str, str] | None
    cgroup_fd: int
    stdin_fd: int
    stdout_fd: int
    stderr_fd: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Clone3LaunchOutcome:
    """Bounded, immutable evidence for one clone3-into-cgroup launch attempt.

    ``pid`` is always the already-cloned child's pid, even when
    ``exec_failed`` is ``True`` -- that child ran only the narrow
    dup2/chdir/setsid/execve path before reporting failure and exiting, and
    the caller is responsible for reaping it exactly like any other child.
    """

    pid: int
    exec_failed: bool
    exec_failure_phase: str | None
    exec_failure_errno: int | None


def probe_clone3_support() -> bool:
    """True only if the native extension is loaded and the kernel supports clone3().

    Spawns no process. This is the function the containment preflight in
    ``cgroup_v2_containment.py`` calls; launch failures are never the first
    place this is discovered.
    """
    if _native is None:
        return False
    try:
        return bool(_native.probe())
    except OSError:
        return False


def launch_into_cgroup(request: Clone3LaunchRequest) -> Clone3LaunchOutcome:
    """Launch ``request.argv[0]`` directly inside the target cgroup via clone3().

    Fails closed with ``Clone3UnavailableError`` before spawning anything
    if the native extension is missing or clone3() is unsupported on this
    kernel -- callers must run the preflight probe first so this is never
    the first place unavailability is discovered.
    """
    if _native is None:
        raise Clone3UnavailableError(
            "the _clone3_cgroup native extension is not built/importable"
        )
    if not probe_clone3_support():
        raise Clone3UnavailableError("this kernel does not implement clone3()")

    env_list: list[str] | None = None
    if request.env is not None:
        env_list = [f"{key}={value}" for key, value in request.env.items()]

    try:
        pid, phase, err = _native.spawn(
            list(request.argv),
            request.cwd,
            env_list,
            cgroup_fd=request.cgroup_fd,
            stdin_fd=request.stdin_fd,
            stdout_fd=request.stdout_fd,
            stderr_fd=request.stderr_fd,
        )
    except OSError as exc:
        raise Clone3SyscallError(f"clone3(CLONE_INTO_CGROUP) failed: {exc}") from exc

    return Clone3LaunchOutcome(
        pid=pid,
        exec_failed=phase is not None,
        exec_failure_phase=phase,
        exec_failure_errno=err if phase is not None else None,
    )
