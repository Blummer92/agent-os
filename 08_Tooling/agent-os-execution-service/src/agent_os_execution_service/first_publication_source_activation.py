"""Bounded source-capsule activation for the #1428 first-publication producer.

This module consumes one exact #1412 source-capsule identity plus evidence already
reacquired by trusted host composition. It creates the truthful #1431 checkpoint,
binds the source capsule to that durable checkpoint, and composes the existing
#895/#918/#1197 stores. It never publishes, dispatches Scheduler, installs
dependencies, or accepts a store path from an external caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.agent_os_execution_capabilities.dependencies import DependencyReadinessEvidence
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
from scripts.agent_os_execution_checkpoint.dependency_readiness_store import append_dependency_readiness
from scripts.agent_os_execution_checkpoint.invalidation import binding_snapshot_from_checkpoint
from scripts.agent_os_execution_checkpoint.resume_plan_store import append_resume_plan
from scripts.agent_os_execution_checkpoint.resume_planner import plan_resume
from scripts.agent_os_execution_checkpoint.store import append_checkpoint

from .authorization import ExecutionAuthorizationEvidence
from .first_publication_producer import (
    FirstPublicationProducerError,
    FirstPublicationProducerResult,
    FirstPublicationProducerRequest,
    RouteSelectionEvidence,
    _require_current_authorization,
    _require_ready_dependencies,
    _select_route,
)
from .models import parse_canonical_utc
from .pre_publication_evidence_capsule import bind_source_capsule_to_checkpoint
from .pre_publication_evidence_store import (
    append_pre_publication_evidence,
    load_source_pre_publication_evidence,
)
from .route_decision_store import append_route_decision


@dataclass(frozen=True, slots=True, kw_only=True)
class FirstPublicationSourceActivationRequest:
    """Trusted-host evidence for one exact already-durable source capsule."""

    source_capsule_id: str
    execution: CanonicalExecutionEvidence
    worktree: WorktreeEvidence
    environment: EnvironmentEvidence
    dependencies: DependencyEvidence
    acceptance: AcceptanceCriteriaEvidence
    governance: GovernanceContractEvidence
    stage_observations: tuple[StageObservation, ...]
    actor_id: str
    dependency_readiness: DependencyReadinessEvidence
    authorization: ExecutionAuthorizationEvidence
    route: RouteSelectionEvidence
    evaluated_at: str
    expires_at: str


def activate_first_publication_source(
    store_root: Path | str,
    request: FirstPublicationSourceActivationRequest,
) -> FirstPublicationProducerResult:
    """Finalize one source capsule and persist canonical producer identities only."""
    if type(request) is not FirstPublicationSourceActivationRequest:
        raise TypeError("request must be an exact FirstPublicationSourceActivationRequest")
    parse_canonical_utc(request.evaluated_at)
    parse_canonical_utc(request.expires_at)

    source = load_source_pre_publication_evidence(store_root, request.source_capsule_id)
    packet = source.candidate_packet
    if (
        source.execution_id != request.execution.execution_id
        or packet.repository.casefold() != request.execution.repository.casefold()
        or packet.issue_number != request.execution.issue_number
        or packet.invocation_id != request.execution.invocation_id
        or source.candidate_branch != request.execution.branch
        or packet.candidate_sha != request.execution.source_sha
        or packet.tested_sha != request.execution.tested_sha
    ):
        raise FirstPublicationProducerError("source-capsule-binding-mismatch")

    compatibility_request = FirstPublicationProducerRequest(
        execution=request.execution,
        worktree=request.worktree,
        environment=request.environment,
        dependencies=request.dependencies,
        acceptance=request.acceptance,
        governance=request.governance,
        stage_observations=request.stage_observations,
        actor_id=request.actor_id,
        candidate_packet=packet,
        pilot_input=None,  # type: ignore[arg-type] -- source capsule replaces transient pilot input here.
        required_environment_spec=source.required_environment_spec,
        dependency_readiness=request.dependency_readiness,
        authorization=request.authorization,
        route=request.route,
        evaluated_at=request.evaluated_at,
        expires_at=request.expires_at,
    )
    _require_current_authorization(request.authorization, request=compatibility_request)
    _require_ready_dependencies(compatibility_request)

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

    bound_capsule = bind_source_capsule_to_checkpoint(source, checkpoint)
    append_pre_publication_evidence(store_root, bound_capsule)

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
        compatibility_request,
        checkpoint_id=checkpoint.checkpoint_id,
        resume_plan_id=resume_plan.plan_id,
    )
    append_route_decision(store_root, route_decision)
    dependency_outcome = append_dependency_readiness(store_root, request.dependency_readiness)

    return FirstPublicationProducerResult(
        checkpoint_id=checkpoint.checkpoint_id,
        resume_plan_id=resume_plan.plan_id,
        route_decision_id=route_decision.decision_id,
        dependency_readiness_id=dependency_outcome.evidence_id,
        pre_publication_evidence_id=bound_capsule.capsule_id,
        authorization_id=request.authorization.authorization_id,
        source_sha=checkpoint.source_sha,
        tested_sha=checkpoint.tested_sha,
    )
