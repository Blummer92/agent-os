"""Execution-interface caller for existing governed handoff publication (#1237).

This module closes only the repository-side callability gap between the Agent OS
execution interface and #1243 ``publish_governed_handoff(...)``. It owns no
route selection, authorization, checkpoint planning, candidate construction,
Scheduler admission, lease, retry, transport, or persistence semantics.

The caller must already hold current canonical evidence from the existing
owners. This adapter unwraps the request/runtime/candidate objects already
produced by ``prepare_candidate_packet(...)``, requires a CURRENT result from
the existing execution-authorization source, preserves the supplied #918 route
and #895 checkpoint/ResumePlan, and delegates exactly once to #1243. #1243
remains the exact-type/current-binding validator and the sole publication
ordering/persistence owner.
"""

from __future__ import annotations

from pathlib import Path

from agent_os_execution_service.execution_authorization_source import (
    ExecutionAuthorizationReadResult,
    ExecutionAuthorizationSourceStatus,
)
from agent_os_execution_service.executor_routing import ExecutorHandoff, ExecutorRouteDecision
from agent_os_execution_service.handoff_publication import publish_governed_handoff
from scripts.agent_os_candidate_packet.cli import PreparedCandidatePacket
from scripts.agent_os_candidate_packet.execution_packet_stage import (
    ExecutionPacketDisposition,
    ExecutionPacketStageResult,
)
from scripts.agent_os_execution_capabilities.dependencies import DependencyReadinessEvidence
from scripts.agent_os_execution_checkpoint.models import ExecutionCheckpoint
from scripts.agent_os_execution_checkpoint.resume_planner import ResumePlan
from workflow_scheduler.execution.single_issue_pilot import SingleIssuePilotInput

PRE_PR_DEVELOPER_LOOP_OPERATION = "pre-pr-developer-loop"


class ExecutionInterfacePublicationError(RuntimeError):
    """Fail-closed evidence that the interface cannot call #1243 yet."""


def publish_current_pre_pr_handoff(
    store_root: Path | str,
    *,
    prepared_candidate: PreparedCandidatePacket,
    route_decision: ExecutorRouteDecision,
    authorization_read: ExecutionAuthorizationReadResult,
    checkpoint: ExecutionCheckpoint,
    resume_plan: ResumePlan,
    dependency_readiness: DependencyReadinessEvidence,
    pilot_input: SingleIssuePilotInput,
    evaluated_at: str,
    required_return_evidence: tuple[str, ...],
    stop_conditions: tuple[str, ...],
) -> ExecutorHandoff:
    """Publish one already-current pre-PR governed-runner handoff through #1243.

    This function deliberately does not derive or synthesize any of its
    authority/currentness inputs. ``PreparedCandidatePacket`` supplies the
    already-canonical candidate, execution request, and runtime configuration;
    ``authorization_read`` must be the CURRENT result from the existing
    execution-authorization source; route/checkpoint/ResumePlan/dependency/pilot
    evidence stays owned by its existing modules.

    The nested objects are not semantically revalidated here. #1243 performs
    the canonical deterministic route replay, pre-PR runtime projection,
    binding, and persistence checks before it returns an immutable handoff.
    """

    if type(prepared_candidate) is not PreparedCandidatePacket:
        raise TypeError("prepared_candidate must be an exact PreparedCandidatePacket")
    if type(authorization_read) is not ExecutionAuthorizationReadResult:
        raise TypeError("authorization_read must be an exact ExecutionAuthorizationReadResult")
    if type(route_decision) is not ExecutorRouteDecision:
        raise TypeError("route_decision must be an exact ExecutorRouteDecision")

    if route_decision.requested_operation != PRE_PR_DEVELOPER_LOOP_OPERATION:
        raise ExecutionInterfacePublicationError(
            "route is not bound to pre-pr-developer-loop"
        )

    execution_stage = prepared_candidate.execution_packet_stage_result
    candidate_packet = prepared_candidate.packet
    if execution_stage is None or candidate_packet is None:
        raise ExecutionInterfacePublicationError(
            "prepared candidate has no complete execution-candidate evidence"
        )
    if type(execution_stage) is not ExecutionPacketStageResult:
        raise ExecutionInterfacePublicationError("execution packet evidence is malformed")
    if (
        execution_stage.disposition is not ExecutionPacketDisposition.GO
        or execution_stage.packet_complete is not True
        or execution_stage.request is None
        or execution_stage.runtime_configuration is None
    ):
        raise ExecutionInterfacePublicationError(
            "execution packet is not complete and GO"
        )

    if (
        authorization_read.status is not ExecutionAuthorizationSourceStatus.CURRENT
        or authorization_read.evidence is None
    ):
        raise ExecutionInterfacePublicationError(
            "execution authorization is not current"
        )

    packet_id = getattr(candidate_packet, "packet_id", None)
    invocation_id = getattr(candidate_packet, "invocation_id", None)
    if (
        authorization_read.authorized_candidate_packet_id != packet_id
        or authorization_read.authorized_invocation_id != invocation_id
    ):
        raise ExecutionInterfacePublicationError(
            "current execution authorization does not bind the prepared candidate"
        )

    return publish_governed_handoff(
        store_root,
        request=execution_stage.request,
        route_decision=route_decision,
        authorization=authorization_read.evidence,
        checkpoint=checkpoint,
        resume_plan=resume_plan,
        candidate_packet=candidate_packet,
        runtime_configuration=execution_stage.runtime_configuration,
        dependency_readiness=dependency_readiness,
        pilot_input=pilot_input,
        evaluated_at=evaluated_at,
        required_return_evidence=required_return_evidence,
        stop_conditions=stop_conditions,
    )
