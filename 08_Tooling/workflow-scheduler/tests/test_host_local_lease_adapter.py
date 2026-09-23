from __future__ import annotations

import ast
import multiprocessing
import os
import stat
from pathlib import Path

import pytest
import workflow_scheduler.execution as execution_pkg

from workflow_scheduler.execution.host_local_lease_adapter import (
    HOST_LOCAL_LEASE_SCHEMA_VERSION,
    LEASE_RECOVERY_WORKSPACE_DISPOSITIONS,
    HostLocalLeaseAdapter,
    HostLocalLeasePolicy,
    OrphanedLeaseRecoveryRequest,
)
from workflow_scheduler.execution.posix_process_adapter import (
    ContainedTerminationEvidence,
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
    adapter = HostLocalLeaseAdapter(policy=HostLocalLeasePolicy(lease_directory=root))
    start.wait()
    grant = adapter.acquire(request)
    output.put((grant.acquired, grant.generation, grant.reason))


def _orphan_worker(root: str, request: PilotLeaseRequest, marker: str) -> None:
    adapter = HostLocalLeaseAdapter(policy=HostLocalLeasePolicy(lease_directory=root))
    grant = adapter.acquire(request)
    if not grant.acquired:
        os._exit(2)
    Path(marker).write_text(str(grant.generation), encoding="ascii")
    os._exit(0)


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


def test_policy_protocol_exports_and_identity_compatibility(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    request = _request()
    assert isinstance(adapter, LeaseAdapter)
    assert HOST_LOCAL_LEASE_SCHEMA_VERSION == "1.0"
    assert execution_pkg.HostLocalLeaseAdapter is HostLocalLeaseAdapter
    assert execution_pkg.HostLocalLeasePolicy is HostLocalLeasePolicy

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


def test_active_generation_is_preserved_while_durable_record_is_ambiguous(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    request = _request(invocation_id="generation-window")
    grant = adapter.acquire(request)
    assert grant.acquired is True
    _, generation_path = adapter._paths(grant.lease_identity)
    generation_path.unlink()

    observation = adapter.inspect(request)
    blocked = adapter.acquire(request)
    assert observation.active is True
    assert observation.ambiguous is True
    assert observation.generation == grant.generation == 1
    assert "not durably recorded" in observation.reason
    assert blocked.acquired is False
    assert blocked.generation == grant.generation
    assert "manual recovery" in blocked.reason


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


def test_abrupt_child_exit_preserves_orphan_as_occupied(tmp_path: Path) -> None:
    root = str(tmp_path / "leases")
    HostLocalLeaseAdapter(policy=HostLocalLeasePolicy(lease_directory=root))
    request = _request(invocation_id="orphan")
    marker = tmp_path / "acquired.txt"
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_orphan_worker, args=(root, request, str(marker))
    )
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 0
    assert marker.read_text(encoding="ascii") == "1"

    after_crash = HostLocalLeaseAdapter(
        policy=HostLocalLeasePolicy(lease_directory=root)
    )
    observation = after_crash.inspect(request)
    blocked = after_crash.acquire(request)
    assert observation.active is True
    assert observation.ambiguous is False
    assert blocked.acquired is False
    assert blocked.generation == 1
    assert "already acquired" in blocked.reason


def test_process_control_exception_propagates_and_leaves_ambiguity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    request = _request(invocation_id="interrupt")

    def interrupt(_path: Path, _generation: int) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(adapter, "_write_generation", interrupt)
    with pytest.raises(KeyboardInterrupt):
        adapter.acquire(request)

    observation = adapter.inspect(request)
    blocked = adapter.acquire(request)
    assert observation.active is True
    assert observation.ambiguous is True
    assert blocked.acquired is False
    assert "manual recovery" in blocked.reason


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


def test_no_renew_takeover_force_release_or_retry_surface(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    for name in ("renew", "takeover", "force_release", "retry"):
        assert not hasattr(adapter, name)
    assert adapter._policy.automatic_retry is False
    assert adapter._policy.takeover_allowed is False


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


# --------------------------------------------------------------------------
# AOS-LEASE1 (#1202): bounded exact-identity orphaned-lease recovery
#
# Recovery is not a force-release, steal, takeover, expiry, or retry. It removes
# only the exact active ownership named by the request, only after independently
# proven termination, and only while an authoritative re-read still matches.
# --------------------------------------------------------------------------


def _proven_termination(
    *, cgroup_path: str = "/sys/fs/cgroup/agent-os/inv-758"
) -> ContainedTerminationEvidence:
    """The canonical #759 contained proof: reap + drain + populated=0 + cleanup."""
    return ContainedTerminationEvidence(
        invocation_cgroup_path=cgroup_path,
        contained=True,
        child_exit_observed=True,
        communication_completed=True,
        return_code=0,
        populated_confirmed_clear=True,
        cleanup_confirmed=True,
    )


def _recovery(
    grant: PilotLeaseGrant,
    *,
    holder: str | None = None,
    generation: int | None = None,
    evidence: ContainedTerminationEvidence | None = None,
    disposition: str = "workspace-removed-and-verified",
) -> OrphanedLeaseRecoveryRequest:
    return OrphanedLeaseRecoveryRequest(
        lease_identity=grant.lease_identity,
        expected_holder_identity=holder if holder is not None else grant.holder_identity,
        expected_generation=generation if generation is not None else grant.generation,
        original_invocation_id="inv-758",
        termination_evidence=evidence if evidence is not None else _proven_termination(),
        workspace_disposition=disposition,
        review_evidence_identity="quarantine-review:operator-evidence-1",
    )


def _orphaned_at_generation_two(tmp_path: Path):
    """Leave one genuinely orphaned active lease whose generation history is > 1."""
    adapter = _adapter(tmp_path)
    request = _request()
    first = adapter.acquire(request)
    assert first.acquired and first.generation == 1
    assert adapter.release(first).released is True
    orphan = adapter.acquire(request)
    assert orphan.acquired and orphan.generation == 2
    return adapter, request, orphan


def test_lease1_exact_containment_proof_and_identity_recovers_the_orphan(
    tmp_path: Path,
) -> None:
    """#1202-9/17: proven termination + exact identity may satisfy recovery."""
    adapter, request, orphan = _orphaned_at_generation_two(tmp_path)

    observation = adapter.recover_orphaned_lease(_recovery(orphan))

    assert observation.recovered is True
    assert observation.mutated is True
    assert observation.lease_identity == orphan.lease_identity
    assert observation.expected_generation == 2
    # Generation history survives recovery: it is never rewritten or reset.
    assert observation.retained_generation == 2
    assert adapter.inspect(request).active is False
    assert adapter.inspect(request).generation == 2


def test_lease1_recovery_yields_a_strictly_newer_generation_never_one(
    tmp_path: Path,
) -> None:
    """#1202-18/19: the next acquisition fences every stale holder."""
    adapter, request, orphan = _orphaned_at_generation_two(tmp_path)
    assert adapter.recover_orphaned_lease(_recovery(orphan)).recovered is True

    successor = adapter.acquire(request)

    assert successor.acquired is True
    assert successor.generation == 3
    assert successor.generation > orphan.generation
    assert successor.generation != 1

    # A delayed release from the recovered generation cannot free the new owner.
    stale = adapter.release(orphan)
    assert stale.released is False
    assert "generation" in stale.reason
    assert adapter.inspect(request).active is True
    assert adapter.inspect(request).generation == 3

    # The current owner still releases exactly, on its own identity.
    assert adapter.release(successor).released is True


@pytest.mark.parametrize(
    "evidence",
    [
        # No recursive cgroup emptiness observation at all.
        ContainedTerminationEvidence(
            invocation_cgroup_path="/sys/fs/cgroup/agent-os/inv-758",
            contained=True,
            child_exit_observed=True,
            communication_completed=True,
            return_code=0,
            populated_confirmed_clear=None,
            cleanup_confirmed=None,
        ),
        # Descendants still present in the invocation cgroup.
        ContainedTerminationEvidence(
            invocation_cgroup_path="/sys/fs/cgroup/agent-os/inv-758",
            contained=True,
            child_exit_observed=True,
            communication_completed=True,
            return_code=0,
            populated_confirmed_clear=False,
            cleanup_confirmed=False,
        ),
        # The child was reaped but the final drain never completed.
        ContainedTerminationEvidence(
            invocation_cgroup_path="/sys/fs/cgroup/agent-os/inv-758",
            contained=True,
            child_exit_observed=True,
            communication_completed=False,
            return_code=0,
            populated_confirmed_clear=True,
            cleanup_confirmed=True,
        ),
        # Never contained, so the containment proof cannot exist for it.
        ContainedTerminationEvidence(
            invocation_cgroup_path="/sys/fs/cgroup/agent-os/inv-758",
            contained=False,
            child_exit_observed=True,
            communication_completed=True,
            return_code=0,
            populated_confirmed_clear=True,
            cleanup_confirmed=True,
        ),
    ],
)
def test_lease1_uncertain_termination_performs_zero_mutation(
    tmp_path: Path, evidence: ContainedTerminationEvidence
) -> None:
    """#1202-16: anything short of the exact containment proof is rejected."""
    adapter, request, orphan = _orphaned_at_generation_two(tmp_path)

    observation = adapter.recover_orphaned_lease(_recovery(orphan, evidence=evidence))

    assert observation.recovered is False
    assert observation.mutated is False
    assert evidence.termination_proven is False
    assert adapter.inspect(request).active is True
    assert adapter.inspect(request).generation == 2


def test_lease1_forbidden_recovery_proofs_cannot_even_be_expressed() -> None:
    """#1202-10/11: PID absence, age, TTL, and heartbeats are not expressible."""
    fields = set(OrphanedLeaseRecoveryRequest.__dataclass_fields__)
    evidence_fields = set(ContainedTerminationEvidence.__dataclass_fields__)

    for forbidden in (
        "pid",
        "process_id",
        "esrch",
        "lease_age_seconds",
        "age",
        "ttl",
        "ttl_seconds",
        "expires_at",
        "expiry",
        "last_heartbeat",
        "heartbeat",
        "heartbeat_age",
        "host_reachable",
        "process_name",
        "observed_at",
        "timestamp",
        "wall_clock",
        "believed_dead",
    ):
        assert forbidden not in fields
        assert forbidden not in evidence_fields

    # The proof is the canonical #759 containment set and nothing else.
    assert evidence_fields == {
        "invocation_cgroup_path",
        "contained",
        "child_exit_observed",
        "communication_completed",
        "return_code",
        "populated_confirmed_clear",
        "cleanup_confirmed",
    }


def test_lease1_wrong_holder_performs_zero_mutation(tmp_path: Path) -> None:
    """#1202-12."""
    adapter, request, orphan = _orphaned_at_generation_two(tmp_path)

    observation = adapter.recover_orphaned_lease(
        _recovery(orphan, holder="pilot-holder:" + "0" * 64)
    )

    assert observation.recovered is False
    assert observation.mutated is False
    assert adapter.inspect(request).active is True
    assert adapter.inspect(request).holder_identity == orphan.holder_identity
    assert adapter.inspect(request).generation == 2


@pytest.mark.parametrize("generation", [1, 3, 99])
def test_lease1_wrong_generation_performs_zero_mutation(
    tmp_path: Path, generation: int
) -> None:
    """#1202-13."""
    adapter, request, orphan = _orphaned_at_generation_two(tmp_path)

    observation = adapter.recover_orphaned_lease(_recovery(orphan, generation=generation))

    assert observation.recovered is False
    assert observation.mutated is False
    assert adapter.inspect(request).active is True
    assert adapter.inspect(request).generation == 2


def test_lease1_active_metadata_change_between_decision_and_mutation_is_rejected(
    tmp_path: Path,
) -> None:
    """#1202-14: compare-and-act re-reads immediately before the only mutation."""
    adapter, request, orphan = _orphaned_at_generation_two(tmp_path)

    class DriftingAdapter(HostLocalLeaseAdapter):
        def __init__(self, *, policy, drift):
            super().__init__(policy=policy)
            self._drift = drift
            self.barrier_calls = 0

        def _before_recovery_mutation(self) -> None:
            self.barrier_calls += 1
            self._drift()

    def drift() -> None:
        # The orphan is recovered and re-acquired by a real new owner while the
        # recovery decision is in flight.
        assert adapter.recover_orphaned_lease(_recovery(orphan)).recovered is True
        successor = adapter.acquire(request)
        assert successor.acquired and successor.generation == 3

    drifting = DriftingAdapter(
        policy=HostLocalLeasePolicy(lease_directory=str(tmp_path / "leases")),
        drift=drift,
    )

    observation = drifting.recover_orphaned_lease(_recovery(orphan))

    assert drifting.barrier_calls == 1
    assert observation.recovered is False
    assert observation.mutated is False
    assert "changed before recovery could act" in observation.reason
    # The new owner is untouched: a stale recovery never disturbs generation 3.
    current = adapter.inspect(request)
    assert current.active is True
    assert current.generation == 3


@pytest.mark.parametrize(
    "payload",
    [
        b"{not json",
        b"{}",
        b'{"lease_identity":"x","holder_identity":"y","generation":0}',
        b'{"lease_identity":"x","holder_identity":"y"}',
        b'{"lease_identity":"x","holder_identity":"y","generation":"2"}',
    ],
)
def test_lease1_malformed_active_metadata_performs_zero_mutation(
    tmp_path: Path, payload: bytes
) -> None:
    """#1202-15."""
    adapter, request, orphan = _orphaned_at_generation_two(tmp_path)
    active_path, _ = adapter._paths(orphan.lease_identity)
    active_path.write_bytes(payload)

    observation = adapter.recover_orphaned_lease(_recovery(orphan))

    assert observation.recovered is False
    assert observation.mutated is False
    assert active_path.read_bytes() == payload


def test_lease1_recovery_requires_a_resolved_workspace_disposition(
    tmp_path: Path,
) -> None:
    """#1202-22: while workspace disposition is open, quarantine stays dominant."""
    _, _, orphan = _orphaned_at_generation_two(tmp_path)

    for unresolved in ("", "unknown", "workspace-unresolved", "probably-clean"):
        with pytest.raises(ValueError):
            _recovery(orphan, disposition=unresolved)

    assert LEASE_RECOVERY_WORKSPACE_DISPOSITIONS == {
        "workspace-removed-and-verified",
        "workspace-preserved-under-review",
    }


def test_lease1_recovery_requires_every_binding_precondition(tmp_path: Path) -> None:
    _, _, orphan = _orphaned_at_generation_two(tmp_path)
    required = {
        "lease_identity",
        "expected_holder_identity",
        "expected_generation",
        "original_invocation_id",
        "termination_evidence",
        "workspace_disposition",
        "review_evidence_identity",
    }
    assert set(OrphanedLeaseRecoveryRequest.__dataclass_fields__) == required

    def _fields(**overrides):
        base = {
            "lease_identity": orphan.lease_identity,
            "expected_holder_identity": orphan.holder_identity,
            "expected_generation": orphan.generation,
            "original_invocation_id": "inv-758",
            "termination_evidence": _proven_termination(),
            "workspace_disposition": "workspace-removed-and-verified",
            "review_evidence_identity": "review-1",
        }
        base.update(overrides)
        return base

    assert OrphanedLeaseRecoveryRequest(**_fields()).expected_generation == 2

    for blank in (
        "lease_identity",
        "expected_holder_identity",
        "original_invocation_id",
        "review_evidence_identity",
    ):
        with pytest.raises(ValueError):
            OrphanedLeaseRecoveryRequest(**_fields(**{blank: ""}))

    for bad_generation in (0, -1):
        with pytest.raises(ValueError):
            OrphanedLeaseRecoveryRequest(**_fields(expected_generation=bad_generation))

    with pytest.raises(TypeError):
        OrphanedLeaseRecoveryRequest(**_fields(termination_evidence=object()))


def test_lease1_recovery_on_an_unheld_lease_performs_zero_mutation(
    tmp_path: Path,
) -> None:
    adapter, request, orphan = _orphaned_at_generation_two(tmp_path)
    assert adapter.release(orphan).released is True

    observation = adapter.recover_orphaned_lease(_recovery(orphan))

    assert observation.recovered is False
    assert observation.mutated is False
    assert observation.reason == "no active lease ownership to recover"
    assert adapter.inspect(request).active is False
    assert adapter.inspect(request).generation == 2


def test_lease1_recovery_introduces_no_takeover_expiry_or_retry_surface(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    for name in (
        "renew",
        "takeover",
        "force_release",
        "retry",
        "steal",
        "expire",
        "heartbeat",
    ):
        assert not hasattr(adapter, name)
    assert adapter._policy.automatic_retry is False
    assert adapter._policy.takeover_allowed is False
