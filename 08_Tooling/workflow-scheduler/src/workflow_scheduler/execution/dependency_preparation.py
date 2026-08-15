from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

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
    environment_health_current: bool
    runtime_version: str | None
    runtime_compatible: bool
    package_manager_version: str | None
    manifest_matches: bool
    lock_matches: bool | None
    source_identity_matches: bool
    source_reachable: bool
    package_available: bool
    cache_state: DependencyCacheState
    local_projects_match: bool = False
    offline_source_identity: str | None = None
    offline_source_location: str | None = None
    existing_ready_evidence: DependencyReadinessEvidence | None = None

    def __post_init__(self) -> None:
        if type(self.environment_health_current) is not bool:
            raise TypeError("environment_health_current must be exact bool")
        if type(self.local_projects_match) is not bool:
            raise TypeError("local_projects_match must be exact bool")


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


class DependencyPreparationObservationProvider(Protocol):
    def observe(
        self,
        *,
        workspace_identity: str,
        existing_ready_evidence: DependencyReadinessEvidence | None,
    ) -> DependencyPreparationObservation: ...


@runtime_checkable
class DependencyPreparationAdapter(Protocol):
    """One task-scoped readiness/preparation seam owned by the Scheduler runtime."""

    def prepare(self, *, workspace_identity: str) -> DependencyReadinessEvidence: ...

    def requires_recheck(self, changed_paths: tuple[str, ...]) -> bool: ...


class BoundDependencyPreparationAdapter:
    """Bind one frozen environment spec to observation and command adapters.

    This adapter performs no retry. A second ``prepare`` call is permitted only
    after dependency inputs changed and therefore represents a new readiness
    state, not a retry of the prior attempt.
    """

    def __init__(
        self,
        *,
        spec: RequiredEnvironmentSpec,
        observations: DependencyPreparationObservationProvider,
        runner: DependencyCommandRunner,
        evaluated_at: str,
        expires_at: str,
    ) -> None:
        if type(spec) is not RequiredEnvironmentSpec:
            raise TypeError("spec must be exact RequiredEnvironmentSpec")
        self._spec = spec
        self._observations = observations
        self._runner = runner
        self._evaluated_at = evaluated_at
        self._expires_at = expires_at
        self._last_ready: DependencyReadinessEvidence | None = None
        self._attempts = 0

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def last_ready_evidence(self) -> DependencyReadinessEvidence | None:
        return self._last_ready

    def prepare(self, *, workspace_identity: str) -> DependencyReadinessEvidence:
        if self._attempts >= 2:
            raise RuntimeError(
                "dependency preparation may run only for initial readiness and one changed-input recheck"
            )
        self._attempts += 1
        observation = self._observations.observe(
            workspace_identity=workspace_identity,
            existing_ready_evidence=self._last_ready,
        )
        if type(observation) is not DependencyPreparationObservation:
            raise TypeError(
                "dependency observation provider must return DependencyPreparationObservation"
            )
        if observation.workspace_identity != workspace_identity:
            raise ValueError("dependency observation workspace identity drifted")
        evidence = execute_dependency_preparation(
            self._spec,
            observation,
            self._runner,
            evaluated_at=self._evaluated_at,
            expires_at=self._expires_at,
        )
        if evidence.preparation_status is DependencyPreparationStatus.READY:
            self._last_ready = evidence
        else:
            self._last_ready = None
        return evidence

    def requires_recheck(self, changed_paths: tuple[str, ...]) -> bool:
        return dependency_inputs_changed(self._spec, changed_paths)


def dependency_inputs_changed(
    spec: RequiredEnvironmentSpec, changed_paths: tuple[str, ...]
) -> bool:
    if type(spec) is not RequiredEnvironmentSpec:
        raise TypeError("spec must be exact RequiredEnvironmentSpec")
    if type(changed_paths) is not tuple or not all(
        type(path) is str and path for path in changed_paths
    ):
        raise TypeError("changed_paths must be an exact tuple of non-empty strings")
    watched = {spec.dependency_manifest_identity.relative_path}
    if spec.lock_or_constraints_identity is not None:
        watched.add(spec.lock_or_constraints_identity.relative_path)
    project_roots = tuple(
        requirement.relative_path.rstrip("/") + "/"
        for requirement in spec.local_project_requirements
    )
    return any(
        path in watched or any(path.startswith(root) for root in project_roots)
        for path in changed_paths
    )


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
    if not observation.environment_health_current:
        return _blocked(spec, observation, "dependency.environment-stale")
    if observation.runtime_version is None or not observation.runtime_compatible:
        return _blocked(spec, observation, "runtime.incompatible")
    if observation.package_manager_version is None:
        return _blocked(
            spec, observation, "dependency.package-manager-unavailable"
        )

    existing = observation.existing_ready_evidence
    if (
        existing is not None
        and existing.preparation_status is DependencyPreparationStatus.READY
        and existing.execution_surface_id != observation.execution_surface_id
    ):
        return _blocked(
            spec, observation, "dependency.environment-surface-mismatch"
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
    if spec.local_project_requirements and not observation.local_projects_match:
        return _blocked(spec, observation, "dependency.editable-source-drift")

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
            and existing.declared_dependency_identity
            == spec.dependency_manifest_identity.sha256
            and existing.lock_or_constraints_identity
            == (
                None
                if spec.lock_or_constraints_identity is None
                else spec.lock_or_constraints_identity.sha256
            )
            and existing.environment_health_evidence_id
            == observation.environment_health_evidence_id
            and existing.cache_state == observation.cache_state
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
        complete_offline = (
            observation.cache_state is DependencyCacheState.CURRENT_COMPLETE
            and observation.offline_source_identity is not None
            and (
                spec.ecosystem is DependencyEcosystem.NODE_NPM
                or observation.offline_source_location is not None
            )
        )
        if not complete_offline:
            reason = (
                "dependency.cache-incomplete"
                if observation.cache_state
                in {DependencyCacheState.INCOMPLETE, DependencyCacheState.UNKNOWN}
                else "dependency.source-unavailable"
            )
            return _blocked(spec, observation, reason)
        source_identity = observation.offline_source_identity or source_identity
        offline = True
    if not observation.package_available:
        return _blocked(spec, observation, "dependency.package-unavailable")

    if spec.ecosystem is DependencyEcosystem.PYTHON_PIP:
        argv = ["python", "-m", "pip", "install"]
        if offline:
            assert observation.offline_source_location is not None
            argv.extend(
                ("--no-index", "--find-links", observation.offline_source_location)
            )
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
    resolved = result.resolved_dependency_identity
    if final.status is DependencyPreparationStatus.READY and not resolved:
        failed = DependencyPreparationPlan(
            status=DependencyPreparationStatus.FAILED,
            argv=plan.argv,
            source_identity=plan.source_identity,
            cache_state=plan.cache_state,
            reason_codes=("dependency.resolved-evidence-missing",),
        )
        return _evidence(spec, observation, failed, evaluated_at, expires_at, None)
    return _evidence(
        spec,
        observation,
        final,
        evaluated_at,
        expires_at,
        resolved,
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
