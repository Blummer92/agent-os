"""Production composition entrypoint for governed handoff publication (#1409).

This module is intentionally thin. It owns no routing, handoff construction,
descriptor persistence, authorization, checkpoint, ResumePlan, environment,
or Scheduler semantics. Callers must supply the already-current canonical
objects; this entrypoint delegates exactly once to #1243's
``publish_governed_handoff`` and returns that exact handoff.

No retry, fallback, Scheduler call, subprocess, network operation, or alternate
persistence path exists here.
"""

from __future__ import annotations

from pathlib import Path

from scripts.agent_os_candidate_packet.models import CandidatePacket
from scripts.agent_os_execution_capabilities.dependencies import DependencyReadinessEvidence
from scripts.agent_os_execution_checkpoint.models import ExecutionCheckpoint
from scripts.agent_os_execution_checkpoint.resume_planner import ResumePlan
from workflow_scheduler.execution.runtime_configuration import ConcreteRuntimeConfiguration
from workflow_scheduler.execution.single_issue_pilot import SingleIssuePilotInput

from .authorization import ExecutionAuthorizationEvidence
from .executor_routing import ExecutorHandoff, ExecutorRouteDecision
from .handoff_publication import publish_governed_handoff
from .models import ExecutionServiceRequest


def publish_current_governed_handoff(
    store_root: Path | str,
    *,
    request: ExecutionServiceRequest,
    route_decision: ExecutorRouteDecision,
    authorization: ExecutionAuthorizationEvidence,
    checkpoint: ExecutionCheckpoint,
    resume_plan: ResumePlan,
    candidate_packet: CandidatePacket,
    runtime_configuration: ConcreteRuntimeConfiguration,
    dependency_readiness: DependencyReadinessEvidence,
    pilot_input: SingleIssuePilotInput,
    evaluated_at: str,
    required_return_evidence: tuple[str, ...],
    stop_conditions: tuple[str, ...],
) -> ExecutorHandoff:
    """Publish one current governed handoff through the canonical #1243 seam.

    The supplied objects remain owned and validated by their existing canonical
    contracts. In particular, this function does not construct, serialize, or
    persist a descriptor itself. ``publish_governed_handoff`` remains the sole
    publication/persistence authority and therefore preserves the invariant
    ``HANDOFF_PUBLISHED => DESCRIPTOR_PRESENT``.
    """

    return publish_governed_handoff(
        store_root,
        request=request,
        route_decision=route_decision,
        authorization=authorization,
        checkpoint=checkpoint,
        resume_plan=resume_plan,
        candidate_packet=candidate_packet,
        runtime_configuration=runtime_configuration,
        dependency_readiness=dependency_readiness,
        pilot_input=pilot_input,
        evaluated_at=evaluated_at,
        required_return_evidence=required_return_evidence,
        stop_conditions=stop_conditions,
    )
