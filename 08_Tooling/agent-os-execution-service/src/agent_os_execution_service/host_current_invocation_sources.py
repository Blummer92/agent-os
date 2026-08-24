"""Host-side current-evidence composition for governed invocation reconstruction.

This module implements the existing ``InvocationEvidenceSources`` protocol by
orchestrating read-only owner-specific readers/rebuilders. It owns no execution,
authorization, lease, retry, or persistence lifecycle. The one persisted object
it reads directly is the canonical #1197 ``DependencyReadinessEvidence`` record
from the checkpoint-owned append-only store introduced by #1254.

A descriptor identity is never treated as proof that evidence is current. Each
reader must reacquire its current object from the existing canonical owner; this
module only rejects mismatched bindings early. The existing
``CanonicalCurrentInvocationResolver`` and ``reconstruct_governed_invocation``
remain responsible for exact-type construction, time/currentness checks,
authorization reacquisition, and Scheduler lease observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from scripts.agent_os_execution_checkpoint.dependency_readiness_store import (
    load_dependency_readiness,
)
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    GovernedInvocationDescriptor,
)

from .current_invocation_resolver import CurrentInvocationResolutionError

DescriptorReader = Callable[[GovernedInvocationDescriptor], object]
HandoffReader = Callable[[GovernedInvocationDescriptor, object], object]
ResumePlanReader = Callable[[GovernedInvocationDescriptor, object], object]
RuntimeConfigurationBuilder = Callable[[GovernedInvocationDescriptor, object], object]
PilotInputBuilder = Callable[..., object]


def _descriptor(value: GovernedInvocationDescriptor) -> GovernedInvocationDescriptor:
    if type(value) is not GovernedInvocationDescriptor:
        raise TypeError("descriptor must be an exact GovernedInvocationDescriptor")
    return value


def _require(value: object, attribute: str, expected: object, label: str) -> None:
    observed = getattr(value, attribute, None)
    if observed != expected:
        raise CurrentInvocationResolutionError(
            f"current {label} {attribute} does not match invocation descriptor"
        )


def _require_repository(value: object, expected: str, label: str) -> None:
    observed = getattr(value, "repository", None)
    if type(observed) is not str or observed.casefold() != expected.casefold():
        raise CurrentInvocationResolutionError(
            f"current {label} repository does not match invocation descriptor"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class HostCurrentInvocationSources:
    """Compose canonical read-only owners behind ``InvocationEvidenceSources``.

    The supplied readers/rebuilders remain the owners of route, handoff,
    checkpoint, resume-plan, candidate-packet, runtime, and pilot-input
    semantics. This class adds only host composition and descriptor-binding
    rejection. Dependency readiness is loaded directly from the checkpoint
    store by its content-addressed identity because #1254 made that existing
    #1197 evidence family restart-recoverable.
    """

    checkpoint_store_root: Path | str
    route_decision_reader: DescriptorReader
    handoff_reader: HandoffReader
    checkpoint_reader: DescriptorReader
    resume_plan_reader: ResumePlanReader
    candidate_packet_rebuilder: DescriptorReader
    runtime_configuration_builder: RuntimeConfigurationBuilder
    pilot_input_builder: PilotInputBuilder

    def __post_init__(self) -> None:
        if isinstance(self.checkpoint_store_root, str):
            if not self.checkpoint_store_root.strip():
                raise TypeError("checkpoint_store_root must identify a path")
        elif not isinstance(self.checkpoint_store_root, Path):
            raise TypeError("checkpoint_store_root must be text or a Path")
        object.__setattr__(self, "checkpoint_store_root", Path(self.checkpoint_store_root))
        for name in (
            "route_decision_reader",
            "handoff_reader",
            "checkpoint_reader",
            "resume_plan_reader",
            "candidate_packet_rebuilder",
            "runtime_configuration_builder",
            "pilot_input_builder",
        ):
            if not callable(getattr(self, name)):
                raise TypeError(f"{name} must be callable")

    def route_decision(self, descriptor: GovernedInvocationDescriptor) -> object:
        descriptor = _descriptor(descriptor)
        value = self.route_decision_reader(descriptor)
        _require(value, "decision_id", descriptor.route_decision_id, "route decision")
        _require_repository(value, descriptor.repository, "route decision")
        _require(
            value,
            "issue_or_handoff_identity",
            descriptor.issue_or_handoff_identity,
            "route decision",
        )
        return value

    def handoff(
        self,
        descriptor: GovernedInvocationDescriptor,
        route_decision: object,
    ) -> object:
        descriptor = _descriptor(descriptor)
        value = self.handoff_reader(descriptor, route_decision)
        _require(value, "handoff_id", descriptor.handoff_id, "handoff")
        _require(value, "route_decision_id", descriptor.route_decision_id, "handoff")
        _require_repository(value, descriptor.repository, "handoff")
        _require(
            value,
            "issue_or_handoff_identity",
            descriptor.issue_or_handoff_identity,
            "handoff",
        )
        _require(value, "source_ref_or_none", descriptor.source_ref, "handoff")
        _require(value, "source_sha_or_none", descriptor.source_sha, "handoff")
        return value

    def checkpoint(self, descriptor: GovernedInvocationDescriptor) -> object:
        descriptor = _descriptor(descriptor)
        value = self.checkpoint_reader(descriptor)
        _require(value, "checkpoint_id", descriptor.checkpoint_id, "checkpoint")
        _require_repository(value, descriptor.repository, "checkpoint")
        _require(value, "issue_number", descriptor.issue_number, "checkpoint")
        _require(value, "execution_id", descriptor.execution_id, "checkpoint")
        _require(value, "invocation_id", descriptor.invocation_id, "checkpoint")
        _require(value, "source_sha", descriptor.source_sha, "checkpoint")
        return value

    def resume_plan(
        self,
        descriptor: GovernedInvocationDescriptor,
        checkpoint: object,
    ) -> object:
        descriptor = _descriptor(descriptor)
        value = self.resume_plan_reader(descriptor, checkpoint)
        _require(value, "plan_id", descriptor.resume_plan_id, "resume plan")
        _require_repository(value, descriptor.repository, "resume plan")
        _require(value, "issue_number", descriptor.issue_number, "resume plan")
        _require(value, "execution_id", descriptor.execution_id, "resume plan")
        return value

    def candidate_packet(self, descriptor: GovernedInvocationDescriptor) -> object:
        descriptor = _descriptor(descriptor)
        value = self.candidate_packet_rebuilder(descriptor)
        _require(value, "packet_id", descriptor.candidate_packet_id, "candidate packet")
        _require_repository(value, descriptor.repository, "candidate packet")
        _require(value, "issue_number", descriptor.issue_number, "candidate packet")
        _require(value, "invocation_id", descriptor.invocation_id, "candidate packet")
        _require(value, "candidate_sha", descriptor.source_sha, "candidate packet")
        return value

    def runtime_configuration(
        self,
        descriptor: GovernedInvocationDescriptor,
        candidate_packet: object,
    ) -> object:
        descriptor = _descriptor(descriptor)
        value = self.runtime_configuration_builder(descriptor, candidate_packet)
        _require(
            value,
            "configuration_fingerprint",
            descriptor.runtime_configuration_fingerprint,
            "runtime configuration",
        )
        _require_repository(value, descriptor.repository, "runtime configuration")
        _require(value, "issue_number", descriptor.issue_number, "runtime configuration")
        _require(value, "invocation_id", descriptor.invocation_id, "runtime configuration")
        _require(value, "source_head_sha", descriptor.source_sha, "runtime configuration")
        return value

    def dependency_readiness(self, descriptor: GovernedInvocationDescriptor) -> object:
        descriptor = _descriptor(descriptor)
        value = load_dependency_readiness(
            self.checkpoint_store_root,
            descriptor.dependency_readiness_evidence_id,
        )
        _require(
            value,
            "dependency_readiness_evidence_id",
            descriptor.dependency_readiness_evidence_id,
            "dependency readiness",
        )
        _require(value, "source_sha", descriptor.source_sha, "dependency readiness")
        _require(
            value,
            "required_environment_id",
            descriptor.required_environment_id,
            "dependency readiness",
        )
        _require(
            value,
            "environment_health_evidence_id",
            descriptor.environment_health_evidence_id,
            "dependency readiness",
        )
        _require(
            value,
            "execution_surface_id",
            descriptor.execution_surface_id,
            "dependency readiness",
        )
        _require(
            value,
            "workspace_identity",
            descriptor.workspace_identity,
            "dependency readiness",
        )
        return value

    def pilot_input(
        self,
        descriptor: GovernedInvocationDescriptor,
        *,
        route_decision: object,
        handoff: object,
        authorization: object,
        checkpoint: object,
        resume_plan: object,
        candidate_packet: object,
        runtime_configuration: object,
        dependency_readiness: object,
    ) -> object:
        descriptor = _descriptor(descriptor)
        value = self.pilot_input_builder(
            descriptor=descriptor,
            route_decision=route_decision,
            handoff=handoff,
            authorization=authorization,
            checkpoint=checkpoint,
            resume_plan=resume_plan,
            candidate_packet=candidate_packet,
            runtime_configuration=runtime_configuration,
            dependency_readiness=dependency_readiness,
        )
        _require_repository(value, descriptor.repository, "pilot input")
        _require(value, "issue_numbers", (descriptor.issue_number,), "pilot input")
        _require(value, "invocation_id", descriptor.invocation_id, "pilot input")
        _require(value, "source_head_sha", descriptor.source_sha, "pilot input")
        return value
