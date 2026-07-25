from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from workflow_scheduler.execution.in_memory_lease_adapter import InMemoryLeaseAdapter
from workflow_scheduler.execution.single_issue_pilot import (
    LeaseAdapter,
    PilotLeaseGrant,
    PilotLeaseReleaseObservation,
    PilotLeaseRequest,
    pilot_holder_identity,
    pilot_lease_identity,
)


def _request(*, invocation_id: str = "inv-1", issue_number: int = 595) -> PilotLeaseRequest:
    return PilotLeaseRequest(
        repository="Blummer92/agent-os",
        issue_number=issue_number,
        invocation_id=invocation_id,
        branch=f"agent/{issue_number}-{invocation_id}",
        workspace_request_id=f"workspace-{invocation_id}",
        projection_id=f"projection-{invocation_id}",
        approval_id=f"approval-{invocation_id}",
        source_head_sha=("a" * 39) + str(issue_number % 10),
    )


def _forge(
    grant: PilotLeaseGrant,
    *,
    lease_identity: str | None = None,
    holder_identity: str | None = None,
    generation: int | None = None,
) -> PilotLeaseGrant:
    return PilotLeaseGrant(
        acquired=True,
        lease_identity=lease_identity or grant.lease_identity,
        holder_identity=holder_identity or grant.holder_identity,
        generation=grant.generation if generation is None else generation,
    )


def test_protocol_and_canonical_identity_compatibility() -> None:
    adapter = InMemoryLeaseAdapter()
    request = _request()

    assert isinstance(adapter, LeaseAdapter)
    grant = adapter.acquire(request)
    assert isinstance(grant, PilotLeaseGrant)
    assert grant.acquired is True
    assert grant.generation == 1
    assert grant.lease_identity == pilot_lease_identity(request)
    assert grant.holder_identity == pilot_holder_identity(request)

    released = adapter.release(grant)
    assert isinstance(released, PilotLeaseReleaseObservation)
    assert released.released is True
    assert released.ambiguous is False
    assert released.forced is False


def test_duplicate_acquire_fails_without_replacing_active_lease() -> None:
    adapter = InMemoryLeaseAdapter()
    request = _request()
    first = adapter.acquire(request)
    second = adapter.acquire(request)

    assert first.acquired is True
    assert second.acquired is False
    assert second.generation == first.generation
    assert second.lease_identity == first.lease_identity
    assert adapter.release(first).released is True

    third = adapter.acquire(request)
    assert third.acquired is True
    assert third.generation == first.generation + 1


def test_repeated_release_is_distinct_and_non_mutating() -> None:
    adapter = InMemoryLeaseAdapter()
    request = _request()
    grant = adapter.acquire(request)

    assert adapter.release(grant).released is True
    repeated = adapter.release(grant)
    assert repeated.released is False
    assert repeated.reason == "lease already released"

    reacquired = adapter.acquire(request)
    assert reacquired.generation == grant.generation + 1


def test_wrong_holder_wrong_generation_and_wrong_identity_do_not_mutate() -> None:
    adapter = InMemoryLeaseAdapter()
    request = _request()
    first = adapter.acquire(request)

    wrong_holder = adapter.release(_forge(first, holder_identity="pilot-holder:wrong"))
    assert wrong_holder.released is False
    assert "holder" in wrong_holder.reason
    assert adapter.release(first).released is True

    active = adapter.acquire(request)
    stale = adapter.release(first)
    future = adapter.release(_forge(active, generation=active.generation + 1))
    assert stale.released is False
    assert future.released is False
    assert "generation" in stale.reason
    assert "generation" in future.reason

    wrong_identity = adapter.release(
        _forge(active, lease_identity="pilot-lease:unknown")
    )
    assert wrong_identity.released is False
    assert wrong_identity.reason == "lease is not owned"

    assert adapter.release(active).released is True


def test_unknown_release_does_not_consume_capacity_or_mutate_other_lease() -> None:
    adapter = InMemoryLeaseAdapter(max_lease_identities=1)
    request = _request()
    active = adapter.acquire(request)

    unknown = PilotLeaseGrant(
        acquired=True,
        lease_identity="pilot-lease:unknown",
        holder_identity="pilot-holder:unknown",
        generation=1,
    )
    result = adapter.release(unknown)
    assert result.released is False
    assert result.reason == "lease is not owned"
    assert adapter.release(active).released is True

    same_identity = adapter.acquire(request)
    assert same_identity.acquired is True
    assert same_identity.generation == 2


def test_generation_is_monotonic_and_stale_same_owner_grant_cannot_release_newer() -> None:
    adapter = InMemoryLeaseAdapter()
    request = _request()

    first = adapter.acquire(request)
    assert adapter.release(first).released is True
    second = adapter.acquire(request)
    assert second.holder_identity == first.holder_identity
    assert second.generation == first.generation + 1

    stale = adapter.release(first)
    assert stale.released is False
    assert "generation" in stale.reason
    assert adapter.release(second).released is True

    third = adapter.acquire(request)
    assert third.generation == second.generation + 1


def test_independent_identities_do_not_interfere() -> None:
    adapter = InMemoryLeaseAdapter()
    first_request = _request(invocation_id="one", issue_number=595)
    second_request = _request(invocation_id="two", issue_number=596)

    first = adapter.acquire(first_request)
    second = adapter.acquire(second_request)
    assert first.acquired is True
    assert second.acquired is True
    assert first.lease_identity != second.lease_identity

    assert adapter.release(first).released is True
    duplicate_second = adapter.acquire(second_request)
    assert duplicate_second.acquired is False
    assert duplicate_second.generation == second.generation
    assert adapter.release(second).released is True


def test_capacity_is_bounded_without_eviction() -> None:
    adapter = InMemoryLeaseAdapter(max_lease_identities=2)
    first_request = _request(invocation_id="one", issue_number=595)
    second_request = _request(invocation_id="two", issue_number=596)
    third_request = _request(invocation_id="three", issue_number=597)

    first = adapter.acquire(first_request)
    second = adapter.acquire(second_request)
    blocked = adapter.acquire(third_request)

    assert first.acquired is True
    assert second.acquired is True
    assert blocked.acquired is False
    assert blocked.generation == 0
    assert blocked.reason == "lease identity capacity reached"

    assert adapter.acquire(first_request).acquired is False
    assert adapter.acquire(second_request).acquired is False
    assert adapter.release(first).released is True
    reacquired = adapter.acquire(first_request)
    assert reacquired.acquired is True
    assert reacquired.generation == 2


def test_thread_contention_has_exactly_one_winner() -> None:
    adapter = InMemoryLeaseAdapter()
    request = _request()
    barrier = Barrier(8)

    def attempt() -> PilotLeaseGrant:
        barrier.wait()
        return adapter.acquire(request)

    with ThreadPoolExecutor(max_workers=8) as pool:
        grants = list(pool.map(lambda _: attempt(), range(8)))

    winners = [grant for grant in grants if grant.acquired]
    losers = [grant for grant in grants if not grant.acquired]
    assert len(winners) == 1
    assert len(losers) == 7
    assert {grant.lease_identity for grant in grants} == {
        pilot_lease_identity(request)
    }
    assert {grant.generation for grant in grants} == {1}
    assert adapter.release(winners[0]).released is True
    assert adapter.release(winners[0]).released is False


def test_stale_release_cannot_remove_reacquired_generation_across_threads() -> None:
    adapter = InMemoryLeaseAdapter()
    request = _request()
    first = adapter.acquire(request)
    assert adapter.release(first).released is True
    second = adapter.acquire(request)
    barrier = Barrier(2)

    def stale_release() -> PilotLeaseReleaseObservation:
        barrier.wait()
        return adapter.release(first)

    def duplicate_acquire() -> PilotLeaseGrant:
        barrier.wait()
        return adapter.acquire(request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        stale_future = pool.submit(stale_release)
        acquire_future = pool.submit(duplicate_acquire)
        stale = stale_future.result()
        duplicate = acquire_future.result()

    assert stale.released is False
    assert duplicate.acquired is False
    assert duplicate.generation == second.generation
    assert adapter.release(second).released is True


def test_input_validation_and_reset_are_deterministic() -> None:
    with pytest.raises(TypeError):
        InMemoryLeaseAdapter(max_lease_identities=True)
    with pytest.raises(TypeError):
        InMemoryLeaseAdapter(max_lease_identities=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        InMemoryLeaseAdapter(max_lease_identities=0)

    adapter = InMemoryLeaseAdapter()
    with pytest.raises(TypeError):
        adapter.acquire(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        adapter.release(object())  # type: ignore[arg-type]

    malformed = PilotLeaseGrant(
        acquired=True,
        lease_identity="",
        holder_identity="",
        generation=0,
    )
    result = adapter.release(malformed)
    assert result.released is False
    assert result.reason == "malformed release request"

    request = _request()
    first = adapter.acquire(request)
    adapter._reset_for_tests()
    after_reset = adapter.acquire(request)
    assert first.generation == 1
    assert after_reset.generation == 1
    assert "_reset_for_tests" not in InMemoryLeaseAdapter.__dict__.get("__all__", ())


def test_architecture_boundaries_are_minimal() -> None:
    module_path = (
        Path(__file__).parents[1]
        / "src"
        / "workflow_scheduler"
        / "execution"
        / "in_memory_lease_adapter.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots <= {"__future__", "dataclasses", "threading", "workflow_scheduler"}
    forbidden = {
        "time",
        "datetime",
        "asyncio",
        "subprocess",
        "sqlite3",
        "fcntl",
        "portalocker",
        "requests",
        "urllib",
        "github",
        "retry",
        "worktree",
    }
    assert imported_roots.isdisjoint(forbidden)
