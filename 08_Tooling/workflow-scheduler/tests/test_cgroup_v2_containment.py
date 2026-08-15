"""Tests for WSC-AUTO1C's ``cgroup_v2_containment`` preflight, invocation
cgroup lifecycle, and exact-scope evidence.

Real cgroup v2 tests are gated on the real preflight probe
(``preflight_check(...).supported``) via ``pytest.mark.skipif``, not a
blanket platform check.
"""

from __future__ import annotations

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

from workflow_scheduler.execution import cgroup_v2_containment as containment_module  # noqa: E402
from workflow_scheduler.execution.cgroup_v2_containment import (  # noqa: E402
    CgroupV2CleanupError,
    CgroupV2ContainmentError,
    CgroupV2CreateError,
    CgroupV2NotEmptyError,
    CgroupV2PreflightError,
    InvocationCgroup,
    preflight_check,
)


def _discover_cgroup2_mount() -> str | None:
    for candidate in ("/sys/fs/cgroup", "/sys/fs/cgroup/unified"):
        if os.path.isfile(os.path.join(candidate, "cgroup.controllers")):
            return candidate
    return None


@pytest.fixture()
def delegated_parent() -> str | None:
    root = _discover_cgroup2_mount()
    if root is None:
        return None
    name = f"agentos-containment-test-{uuid.uuid4().hex}"
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


def _real_supported(delegated_parent_path: str | None) -> bool:
    if delegated_parent_path is None:
        return False
    return preflight_check(delegated_parent_path).supported


# --------------------------------------------------------------------------
# Preflight: fails closed, no side effects on failure paths
# --------------------------------------------------------------------------


def test_preflight_fails_closed_for_a_nonexistent_delegated_parent() -> None:
    result = preflight_check("/no/such/delegated/parent/agent-os")
    assert result.supported is False
    assert result.delegated_parent_exists is False
    assert result.reason != ""


def test_preflight_fails_closed_when_clone3_extension_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(containment_module, "_clone3_native", None)
    monkeypatch.setattr(containment_module, "_clone3_available", lambda: False)
    # Even a perfectly real, writable cgroup v2 directory must not be
    # reported as supported once the native launcher is unavailable --
    # this is the single fail-closed gate every caller relies on.
    root = _discover_cgroup2_mount()
    if root is None:
        pytest.skip("no cgroup v2 mount available to exercise this path")
    result = preflight_check(root)
    assert result.supported is False
    assert "clone3" in result.reason.lower() or "extension" in result.reason.lower()


def test_preflight_probe_leaves_no_probe_directory_behind(delegated_parent: str) -> None:
    if delegated_parent is None:
        pytest.skip("no writable cgroup v2 mount available")
    preflight_check(delegated_parent)
    subdirs = [
        entry
        for entry in os.listdir(delegated_parent)
        if os.path.isdir(os.path.join(delegated_parent, entry))
    ]
    assert subdirs == []


def test_preflight_result_is_immutable() -> None:
    result = preflight_check("/no/such/path")
    with pytest.raises(AttributeError):
        result.supported = True  # type: ignore[misc]


# --------------------------------------------------------------------------
# Real invocation cgroup lifecycle (skipped when unsupported)
# --------------------------------------------------------------------------


requires_real_containment = pytest.mark.skipif(
    not _real_supported(_discover_cgroup2_mount()),
    reason="real cgroup v2 delegation/clone3 support not available on this host",
)


@requires_real_containment
def test_invocation_cgroup_create_and_cleanup_round_trip(delegated_parent: str) -> None:
    inv = InvocationCgroup.create(delegated_parent, str(uuid.uuid4()))
    try:
        assert os.path.isdir(inv.path)
        assert inv.read_populated() is False
        assert inv.cleanup() is True
        assert not os.path.exists(inv.path)
    finally:
        inv.close()


@requires_real_containment
def test_cleanup_refuses_a_non_empty_cgroup(delegated_parent: str) -> None:
    inv = InvocationCgroup.create(delegated_parent, str(uuid.uuid4()))
    child = os.spawnvp(os.P_NOWAIT, "/bin/sleep", ["sleep", "5"])
    try:
        with open(os.path.join(inv.path, "cgroup.procs"), "w", encoding="utf-8") as handle:
            handle.write(str(child))
        assert inv.read_populated() is True
        with pytest.raises(CgroupV2NotEmptyError):
            inv.cleanup()
        # Refused, not silently ignored: the directory is still there.
        assert os.path.isdir(inv.path)
    finally:
        inv.kill()
        inv.wait_until_empty(deadline_seconds=5.0)
        os.waitpid(child, 0)
        inv.cleanup()
        inv.close()


@requires_real_containment
def test_kill_reaches_a_descendant_that_left_the_process_group(delegated_parent: str) -> None:
    """A process that calls setsid() to leave the process group is still
    reachable by cgroup.kill because cgroup membership, not process-group
    membership, is what containment relies on."""
    inv = InvocationCgroup.create(delegated_parent, str(uuid.uuid4()))
    script = (
        "import os, time\n"
        f"os.setsid()\n"
        "pid = os.getpid()\n"
        f"with open('{inv.path}/cgroup.procs', 'w') as f:\n"
        "    f.write(str(pid))\n"
        "time.sleep(30)\n"
    )
    child = os.spawnvp(os.P_NOWAIT, sys.executable, [sys.executable, "-c", script])
    try:
        # Give the child a moment to join the cgroup and detach.
        import time as _time

        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline and not inv.read_populated():
            _time.sleep(0.02)
        assert inv.read_populated() is True
        inv.kill()
        assert inv.wait_until_empty(deadline_seconds=5.0) is True
        os.waitpid(child, 0)
        assert inv.cleanup() is True
    finally:
        inv.close()


@requires_real_containment
def test_unrelated_scope_is_never_touched(delegated_parent: str) -> None:
    """The code never reads/kills/removes a cgroup outside the one
    invocation cgroup it created."""
    sibling_name = f"unrelated-{uuid.uuid4().hex}"
    sibling_path = os.path.join(delegated_parent, sibling_name)
    os.mkdir(sibling_path)
    try:
        inv = InvocationCgroup.create(delegated_parent, str(uuid.uuid4()))
        try:
            inv.kill()
            inv.cleanup()
        finally:
            inv.close()
        # The unrelated sibling cgroup this instance never touched is
        # still exactly where it was.
        assert os.path.isdir(sibling_path)
    finally:
        os.rmdir(sibling_path)


def test_create_rejects_unsafe_invocation_id() -> None:
    with pytest.raises(CgroupV2CreateError):
        InvocationCgroup.create("/tmp", "../escape")


def test_malformed_cgroup_events_raises_containment_error(tmp_path: Path) -> None:
    fake_dir = tmp_path / "fake-cgroup"
    fake_dir.mkdir()
    (fake_dir / "cgroup.events").write_text("not-the-expected-format\n", encoding="utf-8")
    inv = InvocationCgroup(path=str(fake_dir), fd=os.open(str(fake_dir), os.O_RDONLY | os.O_DIRECTORY))
    try:
        with pytest.raises(CgroupV2ContainmentError):
            inv.read_populated()
    finally:
        inv.close()


def test_unreadable_cgroup_events_raises_containment_error(tmp_path: Path) -> None:
    fake_dir = tmp_path / "fake-cgroup-2"
    fake_dir.mkdir()
    inv = InvocationCgroup(path=str(fake_dir), fd=os.open(str(fake_dir), os.O_RDONLY | os.O_DIRECTORY))
    try:
        with pytest.raises(CgroupV2ContainmentError):
            inv.read_populated()  # cgroup.events does not exist under tmp_path
    finally:
        inv.close()
