from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyCacheState,
    DependencyEcosystem,
    DependencyInstallMode,
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    ReproducibilityLevel,
    RequiredEnvironmentSpec,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyPreparationObservation:
    execution_surface_id: str
    workspace_identity: str
    source_sha: str
    environment_health_evidence_id: str
    runtime_version: str | None
    runtime_compatible: bool
    package_manager_version: str | None
    manifest_matches: bool
    lock_matches: bool | None
    source_identity_matches: bool
    source_reachable: bool
    package_available: bool
    cache_state: DependencyCacheState
    offline_source_identity: str | None = None
    existing_ready_evidence: DependencyReadinessEvidence | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyPreparationPlan:
    status: DependencyPreparationStatus
    argv: tuple[str, ...] | None
    source_identity: str
    cache_state: DependencyCacheState
    reason_codes: tuple[str, ...] = ()
    post_success_status: DependencyPreparationStatus = DependencyPreparationStatus.READY


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyCommandObservation:
    attempted: bool
    succeeded: bool
    resolved_dependency_identity: str | None = None
    failure_reason_code: str | None = None


class DependencyCommandRunner(Protocol):
    def run(
        self, argv: tuple[str, ...], *, workspace_identity: str
    ) -> DependencyCommandObservation: ...


def plan_dependency_preparation(
    spec: RequiredEnvironmentSpec,
    observation: DependencyPreparationObservation,
    *,
    evaluated_at: str,
) -> DependencyPreparationPlan:
    if type(spec) is not RequiredEnvironmentSpec:
        raise TypeError("spec must be exact RequiredEnvironmentSpec")
    if type(observation) is not DependencyPreparationObservation:
        raise TypeError("observation must be exact DependencyPreparationObservation")
    if observation.runtime_version is None or not observation.runtime_compatible:
        return _blocked(spec, observation, "runtime.incompatible")
    if observation.package_manager_version is None:
        return _blocked(
            spec, observation, "dependency.package-manager-unavailable"
        )
    if not observation.manifest_matches:
        return _blocked(spec, observation, "dependency.manifest-drift")
    if not observation.source_identity_matches:
        return _blocked(spec, observation, "dependency.package-source-drift")
    if (
        spec.lock_or_constraints_identity is not None
        and observation.lock_matches is not True
    ):
        return _blocked(spec, observation, "dependency.lock-mismatch")

    existing = observation.existing_ready_evidence
    if existing is not None:
        matches = (
            existing.preparation_status is DependencyPreparationStatus.READY
            and existing.required_environment_id == spec.required_environment_id
            and existing.execution_surface_id == observation.execution_surface_id
            and existing.workspace_identity == observation.workspace_identity
            and existing.source_sha == observation.source_sha
            and existing.source_or_registry_identity == spec.approved_source_identity
            and existing.runtime_version == observation.runtime_version
            and existing.package_manager_version == observation.package_manager_version
            and existing.is_current(evaluated_at)
        )
        if matches:
            return DependencyPreparationPlan(
                status=DependencyPreparationStatus.READY,
                argv=None,
                source_identity=spec.approved_source_identity,
                cache_state=observation.cache_state,
            )

    source_identity = spec.approved_source_identity
    offline = False
    if not observation.source_reachable:
        if (
            observation.cache_state is not DependencyCacheState.CURRENT_COMPLETE
            or not observation.offline_source_identity
        ):
            reason = (
                "dependency.cache-incomplete"
                if observation.cache_state
                in {DependencyCacheState.INCOMPLETE, DependencyCacheState.UNKNOWN}
                else "dependency.source-unavailable"
            )
            return _blocked(spec, observation, reason)
        source_identity = observation.offline_source_identity
        offline = True
    if not observation.package_available:
        return _blocked(spec, observation, "dependency.package-unavailable")

    if spec.ecosystem is DependencyEcosystem.PYTHON_PIP:
        argv = ["python", "-m", "pip", "install"]
        if offline:
            argv.extend(("--no-index", "--find-links", source_identity))
        argv.extend(("-r", spec.dependency_manifest_identity.relative_path))
        for project in spec.local_project_requirements:
            if project.editable:
                argv.extend(("-e", project.relative_path))
            else:
                argv.append(project.relative_path)
        argv.extend(pin.requirement for pin in spec.qualification_only_pins)
        return DependencyPreparationPlan(
            status=DependencyPreparationStatus.PREPARATION_REQUIRED,
            argv=tuple(argv),
            source_identity=source_identity,
            cache_state=observation.cache_state,
        )

    if spec.install_mode is DependencyInstallMode.ABSENT_AUTHORIZED_LOCK_GENERATION:
        if observation.source_reachable is False:
            return _blocked(spec, observation, "dependency.source-unavailable")
        return DependencyPreparationPlan(
            status=DependencyPreparationStatus.PREPARATION_REQUIRED,
            argv=("npm", "install", "--package-lock-only", "--ignore-scripts"),
            source_identity=source_identity,
            cache_state=observation.cache_state,
            post_success_status=DependencyPreparationStatus.SOURCE_UPDATE_REQUIRED,
        )
    if spec.lock_or_constraints_identity is None:
        return _blocked(spec, observation, "dependency.lock-required")
    argv = ["npm", "ci"]
    if offline:
        argv.append("--offline")
    return DependencyPreparationPlan(
        status=DependencyPreparationStatus.PREPARATION_REQUIRED,
        argv=tuple(argv),
        source_identity=source_identity,
        cache_state=observation.cache_state,
    )


def execute_dependency_preparation(
    spec: RequiredEnvironmentSpec,
    observation: DependencyPreparationObservation,
    runner: DependencyCommandRunner,
    *,
    evaluated_at: str,
    expires_at: str,
) -> DependencyReadinessEvidence:
    plan = plan_dependency_preparation(spec, observation, evaluated_at=evaluated_at)
    if plan.status is DependencyPreparationStatus.READY:
        assert observation.existing_ready_evidence is not None
        return observation.existing_ready_evidence
    if plan.status is DependencyPreparationStatus.BLOCKED:
        return _evidence(spec, observation, plan, evaluated_at, expires_at, None)
    assert plan.argv is not None
    result = runner.run(plan.argv, workspace_identity=observation.workspace_identity)
    if type(result) is not DependencyCommandObservation or not result.attempted:
        failed = DependencyPreparationPlan(
            status=DependencyPreparationStatus.FAILED,
            argv=plan.argv,
            source_identity=plan.source_identity,
            cache_state=plan.cache_state,
            reason_codes=("dependency.preparation-failed",),
        )
        return _evidence(spec, observation, failed, evaluated_at, expires_at, None)
    if not result.succeeded:
        reason = result.failure_reason_code or "dependency.preparation-failed"
        failed = DependencyPreparationPlan(
            status=DependencyPreparationStatus.FAILED,
            argv=plan.argv,
            source_identity=plan.source_identity,
            cache_state=plan.cache_state,
            reason_codes=(reason,),
        )
        return _evidence(spec, observation, failed, evaluated_at, expires_at, None)
    final = DependencyPreparationPlan(
        status=plan.post_success_status,
        argv=plan.argv,
        source_identity=plan.source_identity,
        cache_state=plan.cache_state,
        reason_codes=("dependency.source-update-required",)
        if plan.post_success_status is DependencyPreparationStatus.SOURCE_UPDATE_REQUIRED
        else (),
    )
    return _evidence(
        spec,
        observation,
        final,
        evaluated_at,
        expires_at,
        result.resolved_dependency_identity,
    )


def _blocked(
    spec: RequiredEnvironmentSpec,
    observation: DependencyPreparationObservation,
    reason: str,
) -> DependencyPreparationPlan:
    return DependencyPreparationPlan(
        status=DependencyPreparationStatus.BLOCKED,
        argv=None,
        source_identity=spec.approved_source_identity,
        cache_state=observation.cache_state,
        reason_codes=(reason,),
    )


def _evidence(
    spec: RequiredEnvironmentSpec,
    observation: DependencyPreparationObservation,
    plan: DependencyPreparationPlan,
    observed_at: str,
    expires_at: str,
    resolved: str | None,
) -> DependencyReadinessEvidence:
    if plan.status is DependencyPreparationStatus.READY:
        level = (
            ReproducibilityLevel.LOCKED
            if spec.lock_or_constraints_identity
            else ReproducibilityLevel.RESOLVED
        )
    else:
        level = ReproducibilityLevel.DECLARED
    declared = spec.dependency_manifest_identity.sha256
    lock = (
        None
        if spec.lock_or_constraints_identity is None
        else spec.lock_or_constraints_identity.sha256
    )
    return DependencyReadinessEvidence(
        execution_surface_id=observation.execution_surface_id,
        workspace_identity=observation.workspace_identity,
        source_sha=observation.source_sha,
        required_environment_id=spec.required_environment_id,
        package_root=spec.package_root,
        ecosystem=spec.ecosystem,
        runtime_version=observation.runtime_version or "unavailable",
        package_manager_version=observation.package_manager_version or "unavailable",
        declared_dependency_identity=declared,
        lock_or_constraints_identity=lock,
        install_mode=spec.install_mode,
        source_or_registry_identity=plan.source_identity,
        cache_state=plan.cache_state,
        preparation_status=plan.status,
        resolved_dependency_identity=(
            resolved
            if plan.status is DependencyPreparationStatus.READY
            else None
        ),
        environment_health_evidence_id=observation.environment_health_evidence_id,
        observed_at=observed_at,
        expires_at=expires_at,
        reproducibility_level=level,
        reason_codes=tuple(sorted(plan.reason_codes)),
    )
