"""Offline tests for the production host composition of the governed-resume
entrypoint (#1287 / AOS-GCE2B).

Every test here is offline: no GitHub, network, cloud, IAM, VM, SSH, or IAP
effects. Filesystem needs use ``tmp_path``. Where the full #1218 reconstruction
seam is not itself under test, ``reconstruct_governed_invocation`` and the
Workflow Scheduler dispatch functions are stubbed/monkeypatched at the module
seam, exactly as the module composes them -- proving wiring/call-count
behavior without re-testing #1218/#758 internals owned by their own suites.
"""

from __future__ import annotations

import functools
import hashlib
from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import agent_os_execution_service.current_invocation_resolver as current_invocation_resolver_module
import agent_os_execution_service.host_current_invocation_sources as host_current_invocation_sources_module
import agent_os_execution_service.production_host_composition as phc
from agent_os_execution_service.current_invocation_resolver import (
    CanonicalCurrentInvocationResolver,
)
from agent_os_execution_service.governed_resume_entrypoint import (
    GovernedResumeBindings,
    main,
    run_governed_resume,
)
from agent_os_execution_service.host_current_invocation_sources import (
    HostCurrentInvocationSources,
)
from agent_os_execution_service.invocation_reconstruction import (
    reconstruct_governed_invocation,
)
from agent_os_execution_service.production_host_composition import (
    CHECKPOINT_STORE_ROOT_ENV_VAR,
    ProductionHostCompositionError,
    build_production_governed_resume_bindings,
)
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME,
    INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    GovernedInvocationDescriptor,
    append_invocation_descriptor,
    load_invocation_descriptor,
)
from workflow_scheduler.execution import concrete_runtime_adapters as concrete_runtime_adapters_module
from workflow_scheduler.execution import host_local_lease_adapter as host_local_lease_adapter_module
from workflow_scheduler.execution import single_issue_pilot as single_issue_pilot_module
from workflow_scheduler.execution.concrete_runtime_adapters import (
    build_concrete_runtime_adapters,
)
from workflow_scheduler.execution.host_local_lease_adapter import HostLocalLeaseAdapter
from workflow_scheduler.execution.runtime_configuration import ConcreteRuntimeConfiguration
from workflow_scheduler.execution.single_issue_pilot import (
    SingleIssuePilotInput,
    run_single_issue_pilot,
)

H = "executor-handoff:" + "a" * 64


class Status(str, Enum):
    ADMITTED = "admitted"
    BLOCKED = "blocked"
    STALE = "stale"
    NEEDS_DECISION = "needs-decision"


@dataclass
class Result:
    """Minimal stand-in for InvocationReconstructionResult, mirroring the
    existing governed_resume_entrypoint test suite's technique."""

    status: Status
    reason_codes: tuple[str, ...]
    pilot_input: object | None


def _id(prefix: str, label: str) -> str:
    return f"{prefix}:{hashlib.sha256(label.encode('utf-8')).hexdigest()}"


def _authorization_transport() -> object:
    def read_authorization_source(repository: str, issue_number: int) -> object:
        raise AssertionError("authorization transport must not be reached in these tests")

    return SimpleNamespace(read_authorization_source=read_authorization_source)


def _no_op_reader(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("reader must not be reached in these tests")


def _base_kwargs(lease_directory: str, *, runtime_configuration_provider) -> dict:
    return dict(
        lease_directory=lease_directory,
        route_decision_reader=_no_op_reader,
        handoff_reader=_no_op_reader,
        checkpoint_reader=_no_op_reader,
        resume_plan_reader=_no_op_reader,
        candidate_packet_rebuilder=_no_op_reader,
        runtime_configuration_builder=_no_op_reader,
        pilot_input_builder=_no_op_reader,
        authorization_transport=_authorization_transport(),
        runtime_configuration_provider=runtime_configuration_provider,
        evaluated_at="2026-08-19T00:00:00Z",
        cancelled=lambda: False,
    )


class FakePilotInput:
    """Test double standing in for SingleIssuePilotInput.

    Tests that exercise composition/wiring (not the real #1218/#758 type
    contracts, which have their own suites) monkeypatch the module's
    ``SingleIssuePilotInput``/``ConcreteRuntimeConfiguration`` isinstance/type
    targets to plain ``object`` so a lightweight double can stand in.
    """


class FakeConfiguration:
    def __init__(self, *, lease_directory: str | None) -> None:
        self.lease_directory = lease_directory
        self.verify_calls: list[object] = []

    def verify(self, pilot_input: object) -> None:
        self.verify_calls.append(pilot_input)


@pytest.fixture
def loosen_type_checks(monkeypatch):
    """Relax the module's exact-type gates so lightweight doubles pass.

    Used only for tests proving composition/call-count/wiring behavior, where
    the real exact-type SingleIssuePilotInput/ConcreteRuntimeConfiguration
    contracts are out of scope (those are covered by #1218/#758's own suites).
    """
    monkeypatch.setattr(phc, "SingleIssuePilotInput", object)
    monkeypatch.setattr(phc, "ConcreteRuntimeConfiguration", object)


@pytest.fixture
def store_root(tmp_path, monkeypatch):
    root = tmp_path / "checkpoint-store"
    root.mkdir()
    monkeypatch.setenv(CHECKPOINT_STORE_ROOT_ENV_VAR, str(root))
    return root


@pytest.fixture
def lease_directory(tmp_path):
    directory = tmp_path / "leases"
    return str(directory)


def _build_bindings_with_stub_reconstruction(
    monkeypatch, *, store_root, lease_directory, result, dispatch_stub_calls
):
    monkeypatch.setattr(phc, "ConcreteRuntimeConfiguration", FakeConfiguration)

    def reconstruct_stub(handoff_id, **_kwargs):
        return result

    monkeypatch.setattr(phc, "reconstruct_governed_invocation", reconstruct_stub)

    def build_adapters_stub(pilot_input, configuration, **_kwargs):
        dispatch_stub_calls.append(("build_concrete_runtime_adapters", pilot_input, configuration))
        return SimpleNamespace(lease=object(), workspace=object(), executor=None, validator=object())

    def run_pilot_stub(pilot_input, *, lease, workspace, executor, validator, cancelled):
        dispatch_stub_calls.append(("run_single_issue_pilot", pilot_input))
        return SimpleNamespace(outcome="stub")

    monkeypatch.setattr(phc, "build_concrete_runtime_adapters", build_adapters_stub)
    monkeypatch.setattr(phc, "run_single_issue_pilot", run_pilot_stub)

    configuration = FakeConfiguration(lease_directory=lease_directory)
    return build_production_governed_resume_bindings(
        **_base_kwargs(lease_directory, runtime_configuration_provider=lambda _pilot: configuration)
    )


# ---------------------------------------------------------------------------
# 1. valid immutable handoff -> admitted reconstruction -> exactly one dispatch
# ---------------------------------------------------------------------------


def test_admitted_reconstruction_dispatches_exactly_once(
    loosen_type_checks, monkeypatch, store_root, lease_directory
):
    pilot_input = FakePilotInput()
    calls: list[object] = []
    bindings = _build_bindings_with_stub_reconstruction(
        monkeypatch,
        store_root=store_root,
        lease_directory=lease_directory,
        result=Result(Status.ADMITTED, ("admitted",), pilot_input),
        dispatch_stub_calls=calls,
    )
    output = run_governed_resume(["--handoff-id", H], bindings=bindings)

    assert [call[0] for call in calls] == [
        "build_concrete_runtime_adapters",
        "run_single_issue_pilot",
    ]
    import json

    assert json.loads(output)["scheduler_dispatch_count"] == 1
    assert json.loads(output)["status"] == "completed"


# ---------------------------------------------------------------------------
# 2/3/4. stale / blocked / needs-decision (ambiguous) -> zero dispatch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [Status.STALE, Status.BLOCKED, Status.NEEDS_DECISION])
def test_nonadmitted_reconstruction_never_dispatches(
    loosen_type_checks, monkeypatch, store_root, lease_directory, status
):
    calls: list[object] = []
    bindings = _build_bindings_with_stub_reconstruction(
        monkeypatch,
        store_root=store_root,
        lease_directory=lease_directory,
        result=Result(status, ("example-reason",), None),
        dispatch_stub_calls=calls,
    )
    output = run_governed_resume(["--handoff-id", H], bindings=bindings)

    assert calls == []
    import json

    assert json.loads(output)["scheduler_dispatch_count"] == 0
    assert json.loads(output)["status"] == status.value


# ---------------------------------------------------------------------------
# 5. malformed argv -> composition seam never invoked
# ---------------------------------------------------------------------------


def test_malformed_argv_never_reaches_production_composition(
    loosen_type_checks, monkeypatch, store_root, lease_directory
):
    calls: list[object] = []
    bindings = _build_bindings_with_stub_reconstruction(
        monkeypatch,
        store_root=store_root,
        lease_directory=lease_directory,
        result=Result(Status.ADMITTED, ("admitted",), FakePilotInput()),
        dispatch_stub_calls=calls,
    )
    reconstruct_calls: list[object] = []
    original_reconstruct = bindings.reconstruct
    tracked = GovernedResumeBindings(
        lambda handoff_id: (reconstruct_calls.append(handoff_id), original_reconstruct(handoff_id))[1],
        bindings.dispatch,
    )

    with pytest.raises(ValueError):
        main(["--command", "echo pwned"], bindings=tracked)

    assert reconstruct_calls == []
    assert calls == []


# ---------------------------------------------------------------------------
# 6. missing production composition -> existing fail-closed behavior preserved
# ---------------------------------------------------------------------------


def test_no_composition_supplied_preserves_existing_fail_closed_behavior():
    with pytest.raises(RuntimeError, match="host-supplied"):
        main(["--handoff-id", H])


# ---------------------------------------------------------------------------
# 7. descriptor existence alone grants no execution
# ---------------------------------------------------------------------------


def _persisted_descriptor(store_root) -> GovernedInvocationDescriptor:
    descriptor = GovernedInvocationDescriptor(
        schema_name=INVOCATION_DESCRIPTOR_SCHEMA_NAME,
        schema_version=INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        repository="Blummer92/agent-os",
        issue_number=1287,
        issue_or_handoff_identity="issue:1287",
        handoff_id=H,
        route_decision_id=_id("executor-route-decision", "route"),
        execution_service_request_fingerprint=_id("execution-request", "request"),
        authorization_id=_id("authorization", "authorization"),
        source_ref="refs/heads/agent/1287-production-host-composition",
        source_sha="a" * 40,
        checkpoint_id=_id("agent-os.execution-checkpoint", "checkpoint"),
        resume_plan_id=_id("agent-os.execution-checkpoint.resume-plan", "resume"),
        environment_profile_id=_id("environment-profile", "profile"),
        environment_health_evidence_id=_id("environment-health", "health"),
        required_environment_id=_id("required-environment", "environment"),
        dependency_readiness_evidence_id=_id("dependency-readiness", "readiness"),
        execution_surface_id="execution-surface:gce-agent-os-test",
        workspace_identity=_id("pilot-workspace", "workspace"),
        workflow_runtime_identity=_id("workflow-runtime", "runtime"),
        candidate_packet_id=_id("candidate-packet", "packet"),
        runtime_configuration_fingerprint=_id("concrete-adapters", "configuration"),
        execution_id="execution-1287-a",
        invocation_id="invocation-1287-a",
    )
    append_invocation_descriptor(store_root, descriptor)
    return descriptor


def test_descriptor_existence_alone_grants_no_execution(store_root, lease_directory):
    """A found descriptor whose current route decision has drifted must still
    yield zero dispatch: currentness, not descriptor existence, gates
    execution."""
    _persisted_descriptor(store_root)
    dispatch_calls: list[object] = []

    def stale_route_decision_reader(descriptor):
        return SimpleNamespace(
            decision_id=_id("executor-route-decision", "a-different-route"),
            repository=descriptor.repository,
            issue_or_handoff_identity=descriptor.issue_or_handoff_identity,
        )

    def dispatch_spy(pilot_input):
        dispatch_calls.append(pilot_input)

    kwargs = _base_kwargs(lease_directory, runtime_configuration_provider=lambda _pilot: None)
    kwargs["route_decision_reader"] = stale_route_decision_reader
    bindings = build_production_governed_resume_bindings(**kwargs)

    result = bindings.reconstruct(H)
    assert result.status.value != "admitted"
    assert result.pilot_input is None

    output = run_governed_resume(
        ["--handoff-id", H],
        bindings=GovernedResumeBindings(bindings.reconstruct, dispatch_spy),
    )
    import json

    assert dispatch_calls == []
    assert json.loads(output)["scheduler_dispatch_count"] == 0


def test_reconstruct_uses_real_load_invocation_descriptor(store_root, lease_directory):
    """Descriptor loading in the composed reconstruct partial is the real
    canonical loader, not a re-implementation."""
    kwargs = _base_kwargs(lease_directory, runtime_configuration_provider=lambda _pilot: None)
    bindings = build_production_governed_resume_bindings(**kwargs)
    result = bindings.reconstruct(H)
    assert result.status.value == "blocked"
    assert "descriptor-missing" in result.reason_codes


# ---------------------------------------------------------------------------
# 8. no InMemoryLeaseAdapter production fallback
# ---------------------------------------------------------------------------


def test_missing_lease_directory_fails_closed_at_composition_time(store_root):
    with pytest.raises(ProductionHostCompositionError):
        build_production_governed_resume_bindings(
            **_base_kwargs("", runtime_configuration_provider=lambda _pilot: None)
        )


def test_dispatch_rejects_configuration_selecting_in_memory_lease(
    loosen_type_checks, monkeypatch, store_root, lease_directory
):
    monkeypatch.setattr(phc, "ConcreteRuntimeConfiguration", FakeConfiguration)

    def reconstruct_stub(handoff_id, **_kwargs):
        return Result(Status.ADMITTED, ("admitted",), FakePilotInput())

    monkeypatch.setattr(phc, "reconstruct_governed_invocation", reconstruct_stub)
    adapter_calls: list[object] = []
    monkeypatch.setattr(
        phc,
        "build_concrete_runtime_adapters",
        lambda *a, **k: adapter_calls.append("called"),
    )

    # lease_directory=None on the configuration is exactly what selects
    # InMemoryLeaseAdapter inside build_concrete_runtime_adapters; production
    # composition must refuse to dispatch rather than silently use it.
    configuration = FakeConfiguration(lease_directory=None)
    bindings = build_production_governed_resume_bindings(
        **_base_kwargs(lease_directory, runtime_configuration_provider=lambda _pilot: configuration)
    )

    with pytest.raises(ProductionHostCompositionError, match="lease_directory"):
        bindings.dispatch(FakePilotInput())
    assert adapter_calls == []


def test_dispatch_rejects_configuration_with_mismatched_lease_directory(
    loosen_type_checks, monkeypatch, store_root, lease_directory
):
    monkeypatch.setattr(phc, "ConcreteRuntimeConfiguration", FakeConfiguration)
    monkeypatch.setattr(
        phc, "reconstruct_governed_invocation", lambda handoff_id, **_k: None
    )
    adapter_calls: list[object] = []
    monkeypatch.setattr(
        phc,
        "build_concrete_runtime_adapters",
        lambda *a, **k: adapter_calls.append("called"),
    )
    configuration = FakeConfiguration(lease_directory="/some/other/lease/directory")
    bindings = build_production_governed_resume_bindings(
        **_base_kwargs(lease_directory, runtime_configuration_provider=lambda _pilot: configuration)
    )

    with pytest.raises(ProductionHostCompositionError, match="lease_directory"):
        bindings.dispatch(FakePilotInput())
    assert adapter_calls == []


def test_production_lease_reader_is_the_real_host_local_lease_adapter(lease_directory, store_root):
    kwargs = _base_kwargs(lease_directory, runtime_configuration_provider=lambda _pilot: None)
    bindings = build_production_governed_resume_bindings(**kwargs)
    assert isinstance(bindings.reconstruct, functools.partial)
    assert isinstance(bindings.reconstruct.keywords["lease_reader"], HostLocalLeaseAdapter)


# ---------------------------------------------------------------------------
# 9. canonical real adapters are reused, not reimplemented
# ---------------------------------------------------------------------------


def test_production_composition_reuses_canonical_symbols_without_duplication():
    assert phc.reconstruct_governed_invocation is reconstruct_governed_invocation
    assert phc.run_single_issue_pilot is run_single_issue_pilot
    assert phc.build_concrete_runtime_adapters is build_concrete_runtime_adapters
    assert phc.HostLocalLeaseAdapter is host_local_lease_adapter_module.HostLocalLeaseAdapter
    assert phc.CanonicalCurrentInvocationResolver is CanonicalCurrentInvocationResolver
    assert (
        phc.CanonicalCurrentInvocationResolver
        is current_invocation_resolver_module.CanonicalCurrentInvocationResolver
    )
    assert phc.HostCurrentInvocationSources is HostCurrentInvocationSources
    assert (
        phc.HostCurrentInvocationSources
        is host_current_invocation_sources_module.HostCurrentInvocationSources
    )
    assert phc.SingleIssuePilotInput is single_issue_pilot_module.SingleIssuePilotInput
    assert phc.ConcreteRuntimeConfiguration is ConcreteRuntimeConfiguration
    assert (
        phc.build_concrete_runtime_adapters
        is concrete_runtime_adapters_module.build_concrete_runtime_adapters
    )


def test_composed_reconstruct_is_a_partial_of_the_canonical_function(store_root, lease_directory):
    kwargs = _base_kwargs(lease_directory, runtime_configuration_provider=lambda _pilot: None)
    bindings = build_production_governed_resume_bindings(**kwargs)
    assert isinstance(bindings.reconstruct, functools.partial)
    assert bindings.reconstruct.func is reconstruct_governed_invocation
    assert bindings.reconstruct.keywords["evaluated_at"] == "2026-08-19T00:00:00Z"
    assert isinstance(
        bindings.reconstruct.keywords["resolver"], CanonicalCurrentInvocationResolver
    )
    # With no canonical runtime request bound, the descriptor loader falls
    # back to the real canonical loader over the exact composed store root
    # (#1338): it is no longer a bare functools.partial of that loader, since
    # a canonical-present request must be able to short-circuit it entirely.
    descriptor_loader = bindings.reconstruct.keywords["descriptor_loader"]
    with patch(
        "agent_os_execution_service.production_host_composition.load_invocation_descriptor"
    ) as mock_load:
        descriptor_loader(H)
        mock_load.assert_called_once_with(str(store_root), H)


# ---------------------------------------------------------------------------
# 10. no network/GitHub/cloud/IAM/VM/SSH/IAP effects
# ---------------------------------------------------------------------------


def test_no_network_or_external_effects_are_performed_by_this_module():
    """Static confirmation: the module never imports a network/subprocess
    transport of its own -- it only composes injected/canonical seams."""
    import ast
    from pathlib import Path

    path = Path(phc.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden = {"socket", "requests", "urllib", "http", "subprocess", "paramiko"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & forbidden)
