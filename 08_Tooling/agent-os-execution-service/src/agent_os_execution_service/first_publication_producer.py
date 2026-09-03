"""Canonical first-publication producer activation (#1428).

This module composes existing evidence owners only. It creates no publication,
Scheduler, lease, retry, authorization, or dependency-installation authority.
All durable writes use the existing checkpoint-root stores.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.agent_os_candidate_packet.models import CandidatePacket
from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    RequiredEnvironmentSpec,
)
from scripts.agent_os_execution_checkpoint.construction import (
    AcceptanceCriteriaEvidence,
    CanonicalExecutionEvidence,
    DependencyEvidence,
    EnvironmentEvidence,
    GovernanceContractEvidence,
    StageObservation,
    WorktreeEvidence,
    construct_execution_checkpoint,
)
from scripts.agent_os_execution_checkpoint.dependency_readiness_store import (
    append_dependency_readiness,
)
from scripts.agent_os_execution_checkpoint.invalidation import (
    binding_snapshot_from_checkpoint,
)
from scripts.agent_os_execution_checkpoint.resume_plan_store import append_resume_plan
from scripts.agent_os_execution_checkpoint.resume_planner import plan_resume
from scripts.agent_os_execution_checkpoint.store import append_checkpoint
from workflow_scheduler.execution.single_issue_pilot import SingleIssuePilotInput

from .authorization import ExecutionAuthorizationEvidence
from .executor_routing import (
    ExecutorCapability,
    ExecutorRouteDecision,
    select_executor_route,
)
from .models import parse_canonical_utc
from .pre_publication_evidence_capsule import build_pre_publication_evidence
from .pre_publication_evidence_store import append_pre_publication_evidence
from .route_decision_store import append_route_decision


class FirstPublicationProducerError(RuntimeError):
    """Finite fail-closed producer failure before publication."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RouteSelectionEvidence:
    """Already-owned #918 routing inputs; checkpoint/ResumePlan are filled here."""

    repository: str
    issue_or_handoff_identity: str
    requested_operation: str
    required_capabilities: tuple[ExecutorCapability, ...]
    governed_runner_capabilities: tuple[ExecutorCapability, ...]
    governed_runner_available: bool
    external_fallback_available: bool
    external_fallback_explicitly_permitted: bool
    created_at: str
    expires_at: str
    invalidation_conditions: tuple[str, ...]
    operating_mode_decision_id: str
    executable_lane_selection_id: str
    execution_service_request_fingerprint: str
    validation_command_plan_id: str | None = None
    repository_state_evidence_id: str | None = None
    worktree_preparation_evidence_id: str | None = None
    exact_head_package_id: str | None = None
    environment_profile_id: str | None = None
    environment_health_evidence_id: str | None = None
    workflow_runtime_identity: str | None = None
    external_fallback_capabilities: tuple[ExecutorCapability, ...] | None = None
    authority_ambiguous: bool = False
    ownership_ambiguous: bool = False
    source_of_truth_ambiguous: bool = False
    target_ambiguous: bool = False
    scope_ambiguous: bool = False
    excluded_surface_involved: bool = False
    evidence_stale: bool = False
    evidence_contradictory: bool = False
    irreversible_or_uncertain_mutation: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class FirstPublicationProducerRequest:
    execution: CanonicalExecutionEvidence
    worktree: WorktreeEvidence
    environment: EnvironmentEvidence
    dependencies: DependencyEvidence
    acceptance: AcceptanceCriteriaEvidence
    governance: GovernanceContractEvidence
    stage_observations: tuple[StageObservation, ...]
    actor_id: str
    candidate_packet: CandidatePacket
    pilot_input: SingleIssuePilotInput
    required_environment_spec: RequiredEnvironmentSpec
    dependency_readiness: DependencyReadinessEvidence
    authorization: ExecutionAuthorizationEvidence
    route: RouteSelectionEvidence
    evaluated_at: str
    expires_at: str


@dataclass(frozen=True, slots=True, kw_only=True)
class FirstPublicationProducerResult:
    checkpoint_id: str
    resume_plan_id: str
    route_decision_id: str
    dependency_readiness_id: str
    pre_publication_evidence_id: str
    authorization_id: str
    source_sha: str
    tested_sha: str
    publication_invoked: bool = False
    scheduler_invoked: bool = False


def _require_current_authorization(
    authorization: ExecutionAuthorizationEvidence,
    *,
    request: FirstPublicationProducerRequest,
) -> None:
    if type(authorization) is not ExecutionAuthorizationEvidence:
        raise FirstPublicationProducerError("authorization-invalid")
    evaluated = parse_canonical_utc(request.evaluated_at)
    authorized_at = parse_canonical_utc(authorization.authorized_at)
    expires_at = parse_canonical_utc(authorization.expires_at)
    if not authorization.execution_authorized or not (authorized_at <= evaluated < expires_at):
        raise FirstPublicationProducerError("authorization-not-current")
    if (
        authorization.repository.casefold() != request.execution.repository.casefold()
        or authorization.expected_sha != request.execution.tested_sha
        or authorization.command_plan_id != request.execution.command_plan_id
    ):
        raise FirstPublicationProducerError("authorization-binding-mismatch")
    snapshot = request.execution.authorization_snapshot_id
    if snapshot is not None and snapshot != authorization.authorization_id:
        raise FirstPublicationProducerError("authorization-snapshot-mismatch")


def _require_ready_dependencies(request: FirstPublicationProducerRequest) -> None:
    evidence = request.dependency_readiness
    if type(evidence) is not DependencyReadinessEvidence:
        raise FirstPublicationProducerError("dependency-readiness-invalid")
    if evidence.preparation_status is not DependencyPreparationStatus.READY:
        # #1428 never performs dependency installation. PREPARATION_REQUIRED and
        # every other non-ready state stop before any durable producer write.
        raise FirstPublicationProducerError("dependency-preparation-required")
    if not evidence.is_current(request.evaluated_at):
        raise FirstPublicationProducerError("dependency-readiness-stale")
    if (
        evidence.source_sha != request.execution.source_sha
        or evidence.required_environment_id
        != request.required_environment_spec.required_environment_id
    ):
        raise FirstPublicationProducerError("dependency-readiness-binding-mismatch")


def _select_route(
    request: FirstPublicationProducerRequest,
    *,
    checkpoint_id: str,
    resume_plan_id: str,
) -> ExecutorRouteDecision:
    route = request.route
    if type(route) is not RouteSelectionEvidence:
        raise FirstPublicationProducerError("route-evidence-invalid")
    if route.repository.casefold() != request.execution.repository.casefold():
        raise FirstPublicationProducerError("route-repository-mismatch")
    return select_executor_route(
        repository=route.repository,
        issue_or_handoff_identity=route.issue_or_handoff_identity,
        requested_operation=route.requested_operation,
        required_capabilities=route.required_capabilities,
        governed_runner_capabilities=route.governed_runner_capabilities,
        governed_runner_available=route.governed_runner_available,
        external_fallback_available=route.external_fallback_available,
        external_fallback_explicitly_permitted=route.external_fallback_explicitly_permitted,
        external_fallback_capabilities=route.external_fallback_capabilities,
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
        irreversible_or_uncertain_mutation=route.irreversible_or_uncertain_mutation,
        execution_service_request_fingerprint_or_none=route.execution_service_request_fingerprint,
        authorization_id_or_none=request.authorization.authorization_id,
        validation_command_plan_id_or_none=route.validation_command_plan_id,
        operating_mode_decision_id_or_none=route.operating_mode_decision_id,
        executable_lane_selection_id_or_none=route.executable_lane_selection_id,
        repository_state_evidence_id_or_none=route.repository_state_evidence_id,
        worktree_preparation_evidence_id_or_none=route.worktree_preparation_evidence_id,
        exact_head_package_id_or_none=route.exact_head_package_id,
        environment_profile_id_or_none=route.environment_profile_id,
        environment_health_evidence_id_or_none=route.environment_health_evidence_id,
        checkpoint_id_or_none=checkpoint_id,
        resume_plan_id_or_none=resume_plan_id,
        workflow_runtime_identity_or_none=route.workflow_runtime_identity,
        execution_authorized=request.authorization.execution_authorized,
        github_writes_authorized=False,
        external_writes_authorized=False,
        merge_authorized=False,
    )


def produce_first_publication_evidence(
    store_root: Path | str,
    request: FirstPublicationProducerRequest,
) -> FirstPublicationProducerResult:
    """Persist existing canonical producer artifacts and stop before publication."""
    if type(request) is not FirstPublicationProducerRequest:
        raise TypeError("request must be an exact FirstPublicationProducerRequest")
    parse_canonical_utc(request.evaluated_at)
    parse_canonical_utc(request.expires_at)
    _require_current_authorization(request.authorization, request=request)
    _require_ready_dependencies(request)

    checkpoint = construct_execution_checkpoint(
        execution=request.execution,
        worktree=request.worktree,
        environment=request.environment,
        dependencies=request.dependencies,
        acceptance=request.acceptance,
        governance=request.governance,
        stage_observations=request.stage_observations,
        recorded_at=request.evaluated_at,
        actor_id=request.actor_id,
    )
    append_checkpoint(store_root, checkpoint)

    resume_plan = plan_resume(
        repository=checkpoint.repository,
        issue_number=checkpoint.issue_number,
        execution_id=checkpoint.execution_id,
        evaluated_at=request.evaluated_at,
        current_bindings=binding_snapshot_from_checkpoint(checkpoint),
        stored_checkpoints=(checkpoint,),
    )
    append_resume_plan(store_root, resume_plan)

    route_decision = _select_route(
        request,
        checkpoint_id=checkpoint.checkpoint_id,
        resume_plan_id=resume_plan.plan_id,
    )
    append_route_decision(store_root, route_decision)
    dependency_outcome = append_dependency_readiness(
        store_root, request.dependency_readiness
    )

    capsule = build_pre_publication_evidence(
        candidate_packet=request.candidate_packet,
        pilot_input=request.pilot_input,
        required_environment_spec=request.required_environment_spec,
        checkpoint=checkpoint,
        created_at=request.evaluated_at,
        expires_at=request.expires_at,
    )
    append_pre_publication_evidence(store_root, capsule)

    return FirstPublicationProducerResult(
        checkpoint_id=checkpoint.checkpoint_id,
        resume_plan_id=resume_plan.plan_id,
        route_decision_id=route_decision.decision_id,
        dependency_readiness_id=dependency_outcome.evidence_id,
        pre_publication_evidence_id=capsule.capsule_id,
        authorization_id=request.authorization.authorization_id,
        source_sha=checkpoint.source_sha,
        tested_sha=checkpoint.tested_sha,
    )
