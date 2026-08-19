"""Production host composition for the frozen governed-resume entrypoint.

This module wires the fixed ``governed_resume_entrypoint`` contract to real
canonical implementations of the #1218 reconstruction seam and the #758/#1253
Workflow Scheduler dispatch boundary. It introduces no new Scheduler, lease,
store, router, checkpoint, retry, or transport system -- it only composes
existing canonical functions/classes into the single ``GovernedResumeBindings``
shape ``governed_resume_entrypoint`` requires.

``build_governed_resume_bindings`` in ``governed_resume_entrypoint`` cannot be
reused here because it requires ``lease``/``workspace``/``executor``/``validator``
eagerly at construction time, while those concrete adapters can only be built
*after* reconstruction yields an admitted ``pilot_input`` -- they depend on the
current ``ConcreteRuntimeConfiguration`` bound to that exact pilot input, which
is not known until admission. This module therefore constructs
``GovernedResumeBindings`` directly: ``reconstruct`` is a ``functools.partial``
of ``reconstruct_governed_invocation`` bound to production readers, and
``dispatch`` is a closure that builds the concrete runtime adapters only once
an admitted ``pilot_input`` is in hand (via ``build_concrete_runtime_adapters``),
then calls ``run_single_issue_pilot`` exactly once.

The checkpoint store root is read only from the ``AGENT_OS_CHECKPOINT_STORE_ROOT``
environment variable (no default, no caller/argv override) -- see
``scripts/agent_os_execution_interface/hook_adapter.py`` and
``scripts/agent-os-execution-interface-preflight.md`` for the existing
canonical binding convention this module reuses.

Production composition requires a host-local lease directory. Both the
reconstruction-time lease *observation* and the dispatch-time lease *adapter*
are bound to the same caller-supplied ``lease_directory`` and use the existing
``HostLocalLeaseAdapter`` exclusively. If the runtime configuration bound to an
admitted pilot input would select any other lease directory (including
``None``, which is what selects ``InMemoryLeaseAdapter`` inside
``build_concrete_runtime_adapters``), this module fails closed instead of
silently dispatching against an in-memory lease -- an in-memory lease
provides no real cross-process concurrency authority and must never be used
in production.
"""

from __future__ import annotations

import functools
import os
from typing import Callable

from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    load_invocation_descriptor,
)
from workflow_scheduler.execution.concrete_runtime_adapters import (
    ChangedPathsInspector,
    ProcessCancellationCheck,
    build_concrete_runtime_adapters,
)
from workflow_scheduler.execution.dependency_preparation import DependencyCommandRunner
from workflow_scheduler.execution.git_worktree_adapter import GitRunner
from workflow_scheduler.execution.host_local_lease_adapter import (
    HostLocalLeaseAdapter,
    HostLocalLeasePolicy,
)
from workflow_scheduler.execution.runtime_configuration import (
    ConcreteRuntimeConfiguration,
    ConcreteRuntimeConfigurationError,
)
from workflow_scheduler.execution.single_issue_pilot import (
    CancellationProbe,
    SingleIssuePilotInput,
    run_single_issue_pilot,
)

from .current_invocation_resolver import CanonicalCurrentInvocationResolver
from .execution_authorization_source import ExecutionAuthorizationSourceTransport
from .governed_resume_entrypoint import GovernedResumeBindings
from .host_current_invocation_sources import (
    DescriptorReader,
    HandoffReader,
    HostCurrentInvocationSources,
    PilotInputBuilder,
    ResumePlanReader,
    RuntimeConfigurationBuilder,
)
from .invocation_reconstruction import reconstruct_governed_invocation

CHECKPOINT_STORE_ROOT_ENV_VAR = "AGENT_OS_CHECKPOINT_STORE_ROOT"

RuntimeConfigurationProvider = Callable[[SingleIssuePilotInput], ConcreteRuntimeConfiguration]


class ProductionHostCompositionError(RuntimeError):
    """Raised when production host composition cannot be safely wired or dispatched."""


def _checkpoint_store_root() -> str:
    """Resolve the checkpoint store root strictly from the environment.

    No default and no caller-supplied override: this is the canonical host
    binding convention already used by ``scripts/agent_os_execution_interface``.
    """
    value = os.environ.get(CHECKPOINT_STORE_ROOT_ENV_VAR)
    if value is None or not value.strip():
        raise ProductionHostCompositionError(
            f"{CHECKPOINT_STORE_ROOT_ENV_VAR} must be set to a host checkpoint "
            "store root; production governed-resume composition refuses to "
            "invent or default a store location"
        )
    return value


def _host_local_lease_adapter(lease_directory: str) -> HostLocalLeaseAdapter:
    if type(lease_directory) is not str or not lease_directory.strip():
        raise ProductionHostCompositionError(
            "production governed-resume composition requires a non-empty "
            "host-local lease_directory; refusing the in-memory lease "
            "adapter fallback"
        )
    return HostLocalLeaseAdapter(
        policy=HostLocalLeasePolicy(lease_directory=lease_directory)
    )


def build_production_governed_resume_bindings(
    *,
    lease_directory: str,
    route_decision_reader: DescriptorReader,
    handoff_reader: HandoffReader,
    checkpoint_reader: DescriptorReader,
    resume_plan_reader: ResumePlanReader,
    candidate_packet_rebuilder: DescriptorReader,
    runtime_configuration_builder: RuntimeConfigurationBuilder,
    pilot_input_builder: PilotInputBuilder,
    authorization_transport: ExecutionAuthorizationSourceTransport,
    runtime_configuration_provider: RuntimeConfigurationProvider,
    evaluated_at: str,
    cancelled: CancellationProbe,
    git_runner: GitRunner | None = None,
    process_cancelled: ProcessCancellationCheck | None = None,
    changed_paths_inspector: ChangedPathsInspector | None = None,
    dependency_command_runner: DependencyCommandRunner | None = None,
) -> GovernedResumeBindings:
    """Compose the real #1218 seam and the real #758/#1253 dispatch boundary.

    ``lease_directory`` is the one host-local Scheduler lease directory this
    composition is ever allowed to observe or dispatch against; it is
    required (never optional, never ``None``) so production composition can
    never silently select ``InMemoryLeaseAdapter``.

    ``runtime_configuration_provider`` is the host's existing owner of
    ``ConcreteRuntimeConfiguration`` construction for one pilot input
    (mirroring how ``HostCurrentInvocationSources.runtime_configuration``
    already delegates configuration construction to an injected builder). It
    is invoked only with the exact current pilot input the #1218 seam has
    reacquired -- never eagerly, and never before reconstruction reaches that
    point.

    Every other keyword argument is an existing canonical reader/rebuilder or
    transport the host already owns; this function performs no reconstruction
    or dispatch logic of its own, only composition.
    """
    if not callable(runtime_configuration_provider):
        raise TypeError("runtime_configuration_provider must be callable")
    lease_adapter = _host_local_lease_adapter(lease_directory)

    checkpoint_store_root = _checkpoint_store_root()

    descriptor_loader = functools.partial(
        load_invocation_descriptor, checkpoint_store_root
    )

    sources = HostCurrentInvocationSources(
        checkpoint_store_root=checkpoint_store_root,
        route_decision_reader=route_decision_reader,
        handoff_reader=handoff_reader,
        checkpoint_reader=checkpoint_reader,
        resume_plan_reader=resume_plan_reader,
        candidate_packet_rebuilder=candidate_packet_rebuilder,
        runtime_configuration_builder=runtime_configuration_builder,
        pilot_input_builder=pilot_input_builder,
    )
    resolver = CanonicalCurrentInvocationResolver(
        sources=sources,
        authorization_transport=authorization_transport,
        evaluated_at=evaluated_at,
    )

    # The lease is only ever *observed* here (never acquired/released):
    # existing Scheduler lease truth remains the sole concurrency authority,
    # exactly as #1218 requires. ``HostLocalLeaseAdapter.inspect`` already
    # satisfies the ``LeaseObservationReader`` protocol -- no new lease
    # semantics are introduced.
    reconstruct = functools.partial(
        reconstruct_governed_invocation,
        descriptor_loader=descriptor_loader,
        resolver=resolver,
        lease_reader=lease_adapter,
        evaluated_at=evaluated_at,
    )

    def dispatch(pilot_input: object) -> object:
        if not isinstance(pilot_input, SingleIssuePilotInput):
            raise TypeError("pilot_input must be SingleIssuePilotInput")
        configuration = runtime_configuration_provider(pilot_input)
        if type(configuration) is not ConcreteRuntimeConfiguration:
            raise ProductionHostCompositionError(
                "runtime_configuration_provider must return an exact "
                "ConcreteRuntimeConfiguration"
            )
        try:
            configuration.verify(pilot_input)
        except ConcreteRuntimeConfigurationError as exc:
            raise ProductionHostCompositionError(
                f"runtime configuration does not verify the admitted pilot input: {exc}"
            ) from exc
        if configuration.lease_directory != lease_directory:
            raise ProductionHostCompositionError(
                "runtime configuration lease_directory does not match the "
                "bound production lease_directory; refusing dispatch rather "
                "than risk an in-memory or mismatched lease adapter"
            )

        adapters = build_concrete_runtime_adapters(
            pilot_input,
            configuration,
            git_runner=git_runner,
            process_cancelled=process_cancelled,
            changed_paths_inspector=changed_paths_inspector,
            dependency_command_runner=dependency_command_runner,
        )
        return run_single_issue_pilot(
            pilot_input,
            lease=adapters.lease,
            workspace=adapters.workspace,
            executor=adapters.executor,
            validator=adapters.validator,
            cancelled=cancelled,
        )

    return GovernedResumeBindings(reconstruct, dispatch)
