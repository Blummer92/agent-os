"""Publish one governed-runner handoff only after descriptor durability.

This thin Execution Service composition seam reuses #918 route/handoff
construction and #1218/#1228 descriptor/current-binding contracts. It performs
no Scheduler admission or execution, lease operation, process launch, provider
selection, transport, retry, GitHub write, or cloud operation.
"""

from __future__ import annotations

from pathlib import Path

from scripts.agent_os_candidate_packet.models import CandidatePacket
from scripts.agent_os_execution_capabilities.dependencies import DependencyReadinessEvidence
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    AppendInvocationDescriptorOutcome,
)
from scripts.agent_os_execution_checkpoint.models import ExecutionCheckpoint
from scripts.agent_os_execution_checkpoint.resume_planner import ResumePlan
from workflow_scheduler.execution.runtime_configuration import ConcreteRuntimeConfiguration
from workflow_scheduler.execution.single_issue_pilot import SingleIssuePilotInput

from .authorization import ExecutionAuthorizationEvidence
from .current_invocation_resolver import (
    build_current_invocation_descriptor,
    persist_current_invocation_descriptor,
    validate_current_invocation_bindings,
)
from .executor_routing import (
    ExecutorHandoff,
    ExecutorRoute,
    ExecutorRouteDecision,
    build_executor_handoff,
    select_executor_route,
)
from .invocation_reconstruction import CurrentInvocationEvidence, InvocationReconstructionReason
from .models import ExecutionServiceRequest
from .request_validation import validate_execution_service_request

_PUBLICATION_REASONS = frozenset(
    {
        "current-evidence-malformed",
        "request-invalid",
        "route-reselection-mismatch",
        "route-not-governed-runner",
        "request-binding-mismatch",
        "descriptor-persistence-failed",
        "descriptor-persistence-mismatch",
    }
) | frozenset(reason.value for reason in InvocationReconstructionReason)


class HandoffPublicationError(RuntimeError):
    """Bounded fail-closed publication evidence; no handoff is returned."""

    def __init__(self, *reasons: str) -> None:
        canonical = tuple(sorted(set(reasons)))
        if not canonical or any(
            reason not in _PUBLICATION_REASONS for reason in canonical
        ):
            raise ValueError("publication reasons must use the finite reason vocabulary")
        self.reason_codes = canonical
        super().__init__(
            "governed handoff publication blocked: " + ",".join(canonical)
        )


def _reselect(route: ExecutorRouteDecision) -> ExecutorRouteDecision:
    """Replay #918 using the exact inputs carried by one canonical decision."""
    return select_executor_route(
        repository=route.repository,
        issue_or_handoff_identity=route.issue_or_handoff_identity,
        requested_operation=route.requested_operation,
        required_capabilities=route.required_capabilities,
        governed_runner_capabilities=route.governed_runner_capabilities,
        governed_runner_available=route.governed_runner_available,
        external_fallback_available=route.external_fallback_available,
        external_fallback_explicitly_permitted=(
            route.external_fallback_explicitly_permitted
        ),
        created_at=route.created_at,
        expires_at=route.expires_at,
        invalidation_conditions=route.invalidation_conditions,
        authority_ambiguous=route.authority_ambiguous,
        ownership_ambiguous=route.ownership_ambiguous,
        source_of_truth_ambiguous=route.source_of_truth_ambiguous,
        target_ambiguous=route.target_ambiguous,
        scope_ambiguous=route.scope_ambiguous,
        excluded_surface_involved=route.excluded_surface_involved,
        evidence_stale=route.evidence_stale,
        evidence_contradictory=route.evidence_contradictory,
        irreversible_or_uncertain_mutation=(
            route.irreversible_or_uncertain_mutation
        ),
        execution_service_request_fingerprint_or_none=(
            route.execution_service_request_fingerprint_or_none
        ),
        authorization_id_or_none=route.authorization_id_or_none,
        validation_command_plan_id_or_none=(
            route.validation_command_plan_id_or_none
        ),
        operating_mode_decision_id_or_none=(
            route.operating_mode_decision_id_or_none
        ),
        executable_lane_selection_id_or_none=(
            route.executable_lane_selection_id_or_none
        ),
        repository_state_evidence_id_or_none=(
            route.repository_state_evidence_id_or_none
        ),
        worktree_preparation_evidence_id_or_none=(
            route.worktree_preparation_evidence_id_or_none
        ),
        exact_head_package_id_or_none=route.exact_head_package_id_or_none,
        environment_profile_id_or_none=route.environment_profile_id_or_none,
        environment_health_evidence_id_or_none=(
            route.environment_health_evidence_id_or_none
        ),
        checkpoint_id_or_none=route.checkpoint_id_or_none,
        resume_plan_id_or_none=route.resume_plan_id_or_none,
        workflow_runtime_identity_or_none=route.workflow_runtime_identity_or_none,
        execution_authorized=route.execution_authorized,
        github_writes_authorized=route.github_writes_authorized,
        external_writes_authorized=route.external_writes_authorized,
        merge_authorized=route.merge_authorized,
    )


def _request_repository(request: ExecutionServiceRequest) -> str:
    return f"{request.repository_identity.owner}/{request.repository_identity.repository}"


def publish_governed_handoff(
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
    """Return the existing immutable handoff only after descriptor persistence."""

    exact = (
        (request, ExecutionServiceRequest),
        (route_decision, ExecutorRouteDecision),
        (authorization, ExecutionAuthorizationEvidence),
        (checkpoint, ExecutionCheckpoint),
        (resume_plan, ResumePlan),
        (candidate_packet, CandidatePacket),
        (runtime_configuration, ConcreteRuntimeConfiguration),
        (dependency_readiness, DependencyReadinessEvidence),
    )
    if any(type(value) is not expected for value, expected in exact) or not isinstance(
        pilot_input, SingleIssuePilotInput
    ):
        raise HandoffPublicationError("current-evidence-malformed")
    if validate_execution_service_request(request, evaluated_at=evaluated_at):
        raise HandoffPublicationError("request-invalid")

    try:
        reselected = _reselect(route_decision)
    except (TypeError, ValueError) as exc:
        raise HandoffPublicationError("current-evidence-malformed") from exc
    if reselected != route_decision:
        raise HandoffPublicationError("route-reselection-mismatch")
    if route_decision.selected_route is not ExecutorRoute.CHATGPT_GOVERNED_RUNNER:
        raise HandoffPublicationError("route-not-governed-runner")

    repository = _request_repository(request)
    if (
        route_decision.repository.casefold() != repository.casefold()
        or route_decision.issue_or_handoff_identity != request.issue_or_handoff_identity
        or route_decision.execution_service_request_fingerprint_or_none
        != request.request_fingerprint
        or runtime_configuration.repository_identity != request.repository_identity
    ):
        raise HandoffPublicationError("request-binding-mismatch")

    try:
        handoff = build_executor_handoff(
            route_decision,
            source_ref_or_none=request.requested_ref,
            source_sha_or_none=request.expected_sha,
            allowed_paths=request.allowed_paths,
            forbidden_paths=request.forbidden_paths,
            required_return_evidence=required_return_evidence,
            stop_conditions=stop_conditions,
            checkpoint_id_or_none=checkpoint.checkpoint_id,
            resume_plan_id_or_none=resume_plan.plan_id,
            environment_profile_id_or_none=(
                route_decision.environment_profile_id_or_none
            ),
        )
        descriptor = build_current_invocation_descriptor(
            route_decision=route_decision,
            handoff=handoff,
            authorization=authorization,
            checkpoint=checkpoint,
            resume_plan=resume_plan,
            candidate_packet=candidate_packet,
            runtime_configuration=runtime_configuration,
            dependency_readiness=dependency_readiness,
            pilot_input=pilot_input,
        )
        current = CurrentInvocationEvidence(
            route_decision=route_decision,
            handoff=handoff,
            authorization=authorization,
            checkpoint=checkpoint,
            resume_plan=resume_plan,
            candidate_packet=candidate_packet,
            runtime_configuration=runtime_configuration,
            dependency_readiness=dependency_readiness,
            pilot_input=pilot_input,
        )
        binding_reasons = validate_current_invocation_bindings(
            descriptor,
            current,
            evaluated_at=evaluated_at,
        )
    except (TypeError, ValueError) as exc:
        raise HandoffPublicationError("current-evidence-malformed") from exc
    if binding_reasons:
        raise HandoffPublicationError(*(reason.value for reason in binding_reasons))

    if (
        descriptor.repository.casefold() != repository.casefold()
        or descriptor.issue_or_handoff_identity != request.issue_or_handoff_identity
        or descriptor.execution_service_request_fingerprint
        != request.request_fingerprint
        or descriptor.source_ref != request.requested_ref
        or descriptor.source_sha != request.expected_sha
    ):
        raise HandoffPublicationError("request-binding-mismatch")

    try:
        outcome = persist_current_invocation_descriptor(
            store_root,
            route_decision=route_decision,
            handoff=handoff,
            authorization=authorization,
            checkpoint=checkpoint,
            resume_plan=resume_plan,
            candidate_packet=candidate_packet,
            runtime_configuration=runtime_configuration,
            dependency_readiness=dependency_readiness,
            pilot_input=pilot_input,
        )
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except Exception as exc:  # noqa: BLE001 - persistence is the fail-closed boundary
        raise HandoffPublicationError("descriptor-persistence-failed") from exc

    if (
        type(outcome) is not AppendInvocationDescriptorOutcome
        or outcome.handoff_id != handoff.handoff_id
        or outcome.descriptor_id != descriptor.descriptor_id
    ):
        raise HandoffPublicationError("descriptor-persistence-mismatch")
    return handoff
