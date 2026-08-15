"""Tests for the WSC-AUTO1C clone3(CLONE_INTO_CGROUP) launcher and its
native ``_clone3_cgroup`` extension boundary.

Real clone3()/cgroup-v2 launch tests are gated on the real preflight probe
(``probe_clone3_support()`` plus a real, writable cgroup v2 directory) via
``pytest.mark.skipif`` -- never a blanket platform check -- so this suite
still runs (and still proves the fail-closed path) on a host where the
native extension is not built or clone3() is unsupported.
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
import uuid
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(SCHEDULER_SRC) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SRC))

from workflow_scheduler.execution import clone3_cgroup_launcher as launcher_module  # noqa: E402
from workflow_scheduler.execution.clone3_cgroup_launcher import (  # noqa: E402
    Clone3LaunchRequest,
    Clone3SyscallError,
    Clone3UnavailableError,
    launch_into_cgroup,
    probe_clone3_support,
)

LAUNCHER_MODULE_PATH = SCHEDULER_SRC / "workflow_scheduler" / "execution" / "clone3_cgroup_launcher.py"
PY = sys.executable


def _discover_cgroup2_mount() -> str | None:
    for candidate in ("/sys/fs/cgroup", "/sys/fs/cgroup/unified"):
        if os.path.isfile(os.path.join(candidate, "cgroup.controllers")):
            return candidate
    return None


@pytest.fixture()
def delegated_parent(tmp_path_factory: pytest.TempPathFactory) -> str | None:
    root = _discover_cgroup2_mount()
    if root is None:
        return None
    name = f"agentos-clone3-launcher-test-{uuid.uuid4().hex}"
    path = os.path.join(root, name)
    try:
        os.mkdir(path)
    except OSError:
        return None
    yield path
    try:
        os.rmdir(path)
    except OSError:
        pass


def _real_containment_available() -> bool:
    return probe_clone3_support() and _discover_cgroup2_mount() is not None


requires_real_clone3 = pytest.mark.skipif(
    not _real_containment_available(),
    reason="real clone3()/cgroup v2 support not available on this host",
)


# --------------------------------------------------------------------------
# Availability / fail-closed behavior
# --------------------------------------------------------------------------


def test_probe_returns_a_bool() -> None:
    assert isinstance(probe_clone3_support(), bool)


def test_extension_unavailable_raises_before_spawning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher_module, "_native", None)

    def _fail_if_called() -> None:
        raise AssertionError("probe_clone3_support must not be reached with no native module")

    request = Clone3LaunchRequest(
        argv=(PY, "-c", "print(1)"),
        cwd=None,
        env=None,
        cgroup_fd=0,
        stdin_fd=0,
        stdout_fd=1,
        stderr_fd=2,
    )
    with pytest.raises(Clone3UnavailableError):
        launch_into_cgroup(request)


def test_unsupported_clone3_raises_before_spawning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher_module, "probe_clone3_support", lambda: False)
    request = Clone3LaunchRequest(
        argv=(PY, "-c", "print(1)"),
        cwd=None,
        env=None,
        cgroup_fd=0,
        stdin_fd=0,
        stdout_fd=1,
        stderr_fd=2,
    )
    with pytest.raises(Clone3UnavailableError):
        launch_into_cgroup(request)


def test_clone3_syscall_failure_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    if launcher_module._native is None:
        pytest.skip("native extension not built")

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(launcher_module, "probe_clone3_support", lambda: True)
    monkeypatch.setattr(launcher_module._native, "spawn", _boom)
    request = Clone3LaunchRequest(
        argv=(PY, "-c", "print(1)"),
        cwd=None,
        env=None,
        cgroup_fd=0,
        stdin_fd=0,
        stdout_fd=1,
        stderr_fd=2,
    )
    with pytest.raises(Clone3SyscallError):
        launch_into_cgroup(request)


# --------------------------------------------------------------------------
# Real launches (skipped when clone3()/cgroup v2 is unavailable)
# --------------------------------------------------------------------------


@requires_real_clone3
def test_child_lands_directly_in_the_target_cgroup(delegated_parent: str) -> None:
    """The exec-visible child begins inside the target cgroup, proven by
    the child itself reading its own /proc/self/cgroup and reporting it
    back over stdout."""
    cgroup_fd = os.open(delegated_parent, os.O_RDONLY | os.O_DIRECTORY)
    devnull = os.open(os.devnull, os.O_RDONLY)
    read_fd, write_fd = os.pipe()
    try:
        request = Clone3LaunchRequest(
            argv=(PY, "-c", "print(open('/proc/self/cgroup').read(), end='')"),
            cwd=None,
            env=None,
            cgroup_fd=cgroup_fd,
            stdin_fd=devnull,
            stdout_fd=write_fd,
            stderr_fd=write_fd,
        )
        outcome = launch_into_cgroup(request)
        os.close(write_fd)
        write_fd = -1
        output = b""
        while True:
            chunk = os.read(read_fd, 4096)
            if not chunk:
                break
            output += chunk
        _, status = os.waitpid(outcome.pid, 0)
        assert outcome.exec_failed is False
        assert f"0::/{os.path.basename(delegated_parent)}".encode() in output
    finally:
        os.close(cgroup_fd)
        os.close(devnull)
        os.close(read_fd)
        if write_fd != -1:
            os.close(write_fd)


@requires_real_clone3
def test_exec_of_nonexistent_binary_reports_deterministically(delegated_parent: str) -> None:
    """A nonexistent binary reports a bounded exec failure through the
    error pipe -- never a hang."""
    cgroup_fd = os.open(delegated_parent, os.O_RDONLY | os.O_DIRECTORY)
    devnull = os.open(os.devnull, os.O_RDONLY)
    try:
        request = Clone3LaunchRequest(
            argv=("/no/such/binary-launcher-test",),
            cwd=None,
            env=None,
            cgroup_fd=cgroup_fd,
            stdin_fd=devnull,
            stdout_fd=devnull,
            stderr_fd=devnull,
        )
        outcome = launch_into_cgroup(request)
        os.waitpid(outcome.pid, 0)
        assert outcome.exec_failed is True
        assert outcome.exec_failure_phase == "execve"
        assert outcome.exec_failure_errno == 2  # ENOENT
    finally:
        os.close(cgroup_fd)
        os.close(devnull)


@requires_real_clone3
def test_successful_exec_reports_no_failure(delegated_parent: str) -> None:
    cgroup_fd = os.open(delegated_parent, os.O_RDONLY | os.O_DIRECTORY)
    devnull = os.open(os.devnull, os.O_RDONLY)
    try:
        request = Clone3LaunchRequest(
            argv=(PY, "-c", "import sys; sys.exit(0)"),
            cwd=None,
            env=None,
            cgroup_fd=cgroup_fd,
            stdin_fd=devnull,
            stdout_fd=devnull,
            stderr_fd=devnull,
        )
        outcome = launch_into_cgroup(request)
        _, status = os.waitpid(outcome.pid, 0)
        assert outcome.exec_failed is False
        assert outcome.exec_failure_phase is None
        assert os.WIFEXITED(status)
        assert os.WEXITSTATUS(status) == 0
    finally:
        os.close(cgroup_fd)
        os.close(devnull)


# --------------------------------------------------------------------------
# Architecture boundary: no shell/network/credential/persistence surface
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
    "subprocess",
    "shutil",
)


def test_launcher_module_imports_no_shell_network_or_persistence_surface() -> None:
    source = LAUNCHER_MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
    for module_name in imported_modules:
        root = module_name.split(".")[0]
        assert root not in _FORBIDDEN_IMPORT_ROOTS, f"forbidden import: {module_name}"


def test_launcher_module_defines_no_fallback_launch_mechanism() -> None:
    source = inspect.getsource(launcher_module)
    tree = ast.parse(source)
    code_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Call, ast.Attribute, ast.Name)):
            code_lines.add(node.lineno)
    source_lines = source.splitlines()
    code_only = "\n".join(
        line for i, line in enumerate(source_lines, start=1) if i in code_lines
    )
    for forbidden_token in ("preexec_fn", "posix_spawn", "Popen(", "shell=True", "os.system("):
        assert forbidden_token not in code_only


def test_native_extension_exposes_exactly_spawn_and_probe() -> None:
    if launcher_module._native is None:
        pytest.skip("native extension not built")
    public_names = {name for name in dir(launcher_module._native) if not name.startswith("_")}
    assert public_names == {"spawn", "probe"}
