from __future__ import annotations

import ast
import multiprocessing
import os
import stat
from pathlib import Path

import pytest

from workflow_scheduler.execution.host_local_lease_adapter import (
    HOST_LOCAL_LEASE_SCHEMA_VERSION,
    HostLocalLeaseAdapter,
    HostLocalLeasePolicy,
)
from workflow_scheduler.execution.single_issue_pilot import (
    LeaseAdapter,
    PilotLeaseGrant,
    PilotLeaseRequest,
    pilot_holder_identity,
    pilot_lease_identity,
)


def _request(*, invocation_id: str = "inv-758") -> PilotLeaseRequest:
    return PilotLeaseRequest(
        repository="Blummer92/agent-os",
        issue_number=758,
        invocation_id=invocation_id,
        branch="agent/758-host-local-lease",
        workspace_request_id=f"workspace-{invocation_id}",
        projection_id=f"projection-{invocation_id}",
        approval_id=f"approval-{invocation_id}",
        source_head_sha="a" * 40,
    )


def _worker(root: str, request: PilotLeaseRequest, start, output) -> None:
    adapter = HostLocalLeaseAdapter(
        policy=HostLocalLeasePolicy(lease_directory=root)
    )
    start.wait()
    grant = adapter.acquire(request)
    output.put((grant.acquired, grant.generation, grant.reason))


def _adapter(tmp_path: Path) -> HostLocalLeaseAdapter:
    return HostLocalLeaseAdapter(
        policy=HostLocalLeasePolicy(lease_directory=str(tmp_path / "leases"))
    )


def _forge(
    grant: PilotLeaseGrant,
    *,
    holder_identity: str | None = None,
    generation: int | None = None,
) -> PilotLeaseGrant:
    return PilotLeaseGrant(
        acquired=True,
        lease_identity=grant.lease_identity,
        holder_identity=holder_identity or grant.holder_identity,
        generation=grant.generation if generation is None else generation,
    )


def test_policy_protocol_and_identity_compatibility(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    request = _request()
    assert isinstance(adapter, LeaseAdapter)
    assert HOST_LOCAL_LEASE_SCHEMA_VERSION == "1.0"

    grant = adapter.acquire(request)
    assert grant.acquired is True
    assert grant.generation == 1
    assert grant.lease_identity == pilot_lease_identity(request)
    assert grant.holder_identity == pilot_holder_identity(request)

    observation = adapter.inspect(request)
    assert observation.active is True
    assert observation.ambiguous is False
    assert observation.generation == 1
    assert observation.holder_identity == grant.holder_identity
    assert adapter.release(grant).released is True


def test_two_processes_race_and_exactly_one_acquires(tmp_path: Path) -> None:
    root = str(tmp_path / "leases")
    HostLocalLeaseAdapter(policy=HostLocalLeasePolicy(lease_directory=root))
    request = _request()
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    output = context.Queue()
    processes = [
        context.Process(target=_worker, args=(root, request, start, output))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    results = [output.get(timeout=10) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert sum(1 for acquired, _, _ in results if acquired) == 1
    assert {generation for _, generation, _ in results} == {1}


def test_duplicate_release_and_generation_fencing(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    request = _request()
    first = adapter.acquire(request)
    assert adapter.acquire(request).acquired is False
    assert adapter.release(first).released is True
    assert adapter.release(first).released is False

    second = adapter.acquire(request)
    assert second.acquired is True
    assert second.generation == first.generation + 1
    stale = adapter.release(first)
    assert stale.released is False
    assert "generation" in stale.reason
    assert adapter.release(second).released is True


def test_wrong_holder_and_generation_cannot_release(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    grant = adapter.acquire(_request())

    wrong_holder = adapter.release(
        _forge(grant, holder_identity="pilot-holder:" + "0" * 64)
    )
    wrong_generation = adapter.release(_forge(grant, generation=grant.generation + 1))
    assert wrong_holder.released is False
    assert "holder" in wrong_holder.reason
    assert wrong_generation.released is False
    assert "generation" in wrong_generation.reason
    assert adapter.release(grant).released is True


def test_malformed_or_inconsistent_metadata_is_ambiguous_and_not_taken_over(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    request = _request()
    lease_identity = pilot_lease_identity(request)
    active_path, generation_path = adapter._paths(lease_identity)
    active_path.write_text("not-json", encoding="utf-8")
    os.chmod(active_path, 0o600)
    generation_path.write_text("1", encoding="ascii")
    os.chmod(generation_path, 0o600)

    observation = adapter.inspect(request)
    blocked = adapter.acquire(request)
    assert observation.active is True
    assert observation.ambiguous is True
    assert blocked.acquired is False
    assert "manual recovery" in blocked.reason
    assert active_path.exists()


def test_existing_active_state_is_never_expired_or_stolen(tmp_path: Path) -> None:
    first = _adapter(tmp_path)
    request = _request()
    grant = first.acquire(request)

    second = HostLocalLeaseAdapter(policy=first._policy)
    blocked = second.acquire(request)
    assert blocked.acquired is False
    assert blocked.generation == grant.generation
    assert "already acquired" in blocked.reason
    assert first.release(grant).released is True


def test_private_permissions_and_path_rejections(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    root = Path(adapter._policy.lease_directory)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    grant = adapter.acquire(_request())
    active_path, generation_path = adapter._paths(grant.lease_identity)
    assert stat.S_IMODE(active_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(generation_path.stat().st_mode) == 0o600

    with pytest.raises(ValueError):
        HostLocalLeasePolicy(lease_directory="relative/path")
    with pytest.raises(ValueError):
        HostLocalLeasePolicy(lease_directory="/tmp/../tmp/leases")
    with pytest.raises(ValueError):
        HostLocalLeasePolicy(lease_directory="/")

    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        HostLocalLeaseAdapter(policy=HostLocalLeasePolicy(lease_directory=str(link)))


def test_oversized_and_symlink_metadata_fail_closed(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    request = _request()
    lease_identity = pilot_lease_identity(request)
    active_path, generation_path = adapter._paths(lease_identity)
    active_path.write_bytes(b"x" * 20_000)
    os.chmod(active_path, 0o600)
    generation_path.write_text("1", encoding="ascii")
    os.chmod(generation_path, 0o600)
    assert adapter.inspect(request).ambiguous is True
    assert adapter.acquire(request).acquired is False

    active_path.unlink()
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    active_path.symlink_to(target)
    assert adapter.acquire(request).acquired is False


def test_malformed_release_is_non_mutating(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    malformed = PilotLeaseGrant(
        acquired=True,
        lease_identity="",
        holder_identity="",
        generation=0,
    )
    result = adapter.release(malformed)
    assert result.released is False
    assert result.reason == "malformed release request"


def test_architecture_has_no_network_retry_or_runtime_wiring() -> None:
    module_path = (
        Path(__file__).parents[1]
        / "src"
        / "workflow_scheduler"
        / "execution"
        / "host_local_lease_adapter.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    forbidden = {
        "requests",
        "urllib",
        "socket",
        "github",
        "subprocess",
        "sqlite3",
        "redis",
        "retry",
        "time",
        "datetime",
    }
    assert imported_roots.isdisjoint(forbidden)
