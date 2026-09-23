from __future__ import annotations

from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorRoute,
    ExecutorRouteReason,
    select_executor_route,
)
from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyArtifactIdentity,
    DependencyCacheState,
    DependencyEcosystem,
    DependencyInstallMode,
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    ReproducibilityLevel,
    RequiredEnvironmentSpec,
)
from scripts.agent_os_execution_interface.pre_pr_runtime_compatibility import (
    project_pre_pr_runtime_capabilities,
)

SHA256 = "a" * 64
HEAD = "b" * 40
NOW = "2026-08-19T05:30:00Z"


def artifact(path: str) -> DependencyArtifactIdentity:
    return DependencyArtifactIdentity(relative_path=path, sha256=SHA256)


def spec(*, ecosystem: DependencyEcosystem = DependencyEcosystem.NODE_NPM) -> RequiredEnvironmentSpec:
    manifest = "package.json" if ecosystem is DependencyEcosystem.NODE_NPM else "requirements-dev.txt"
    return RequiredEnvironmentSpec(
        ecosystem=ecosystem,
        package_root=".",
        runtime_requirement=">=22" if ecosystem is DependencyEcosystem.NODE_NPM else ">=3.11",
        dependency_manifest_identity=artifact(manifest),
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity=(
            "registry.npmjs.org"
            if ecosystem is DependencyEcosystem.NODE_NPM
            else "pypi.org/simple"
        ),
        required_validation_command_ids=("focused-tests",),
    )


def readiness(
    environment: RequiredEnvironmentSpec,
    *,
    status: DependencyPreparationStatus = DependencyPreparationStatus.READY,
    execution_surface_id: str = "surface:runner",
    observed_at: str = "2026-08-19T05:00:00Z",
    expires_at: str = "2026-08-19T06:00:00Z",
) -> DependencyReadinessEvidence:
    return DependencyReadinessEvidence(
        execution_surface_id=execution_surface_id,
        workspace_identity="workspace:1278",
        source_sha=HEAD,
        required_environment_id=environment.required_environment_id,
        package_root=environment.package_root,
        ecosystem=environment.ecosystem,
        runtime_version="22.18.0" if environment.ecosystem is DependencyEcosystem.NODE_NPM else "3.12.1",
        package_manager_version="10.9.3" if environment.ecosystem is DependencyEcosystem.NODE_NPM else "24.0",
        declared_dependency_identity=SHA256,
        lock_or_constraints_identity=None,
        install_mode=environment.install_mode,
        source_or_registry_identity=environment.approved_source_identity,
        cache_state=(
            DependencyCacheState.CURRENT_COMPLETE
            if status is DependencyPreparationStatus.READY
            else DependencyCacheState.INCOMPLETE
        ),
        preparation_status=status,
        resolved_dependency_identity=(
            "resolved:1278" if status is DependencyPreparationStatus.READY else None
        ),
        environment_health_evidence_id="environment-health:1278",
        observed_at=observed_at,
        expires_at=expires_at,
        reproducibility_level=ReproducibilityLevel.RESOLVED,
        reason_codes=(),
    )


def route(projection, *, runner_caps=None, runner_available=True):
    capabilities = projection.required_capabilities if runner_caps is None else runner_caps
    return select_executor_route(
        repository="Blummer92/agent-os",
        issue_or_handoff_identity="issue:1278",
        requested_operation="pre-pr-developer-loop",
        required_capabilities=projection.required_capabilities,
        governed_runner_capabilities=capabilities,
        governed_runner_available=runner_available,
        external_fallback_available=False,
        external_fallback_explicitly_permitted=False,
        created_at="2026-08-19T05:30:00Z",
        expires_at="2026-08-19T06:30:00Z",
        invalidation_conditions=("environment-changed",),
        execution_service_request_fingerprint_or_none="execution-request:1278",
        validation_command_plan_id_or_none="command-plan:1278",
        operating_mode_decision_id_or_none="operating-mode:1278",
        executable_lane_selection_id_or_none="lane-selection:1278",
        environment_profile_id_or_none=(
            "environment-profile:1278" if runner_available else None
        ),
        environment_health_evidence_id_or_none=(
            projection.environment_health_evidence_id if runner_available else None
        ),
        workflow_runtime_identity_or_none=("workflow-runtime:1278" if runner_available else None),
        evidence_stale=projection.evidence_stale,
        evidence_contradictory=projection.evidence_contradictory,
    )


def test_ready_node_developer_loop_requires_governed_runtime_capabilities() -> None:
    environment = spec()
    projection = project_pre_pr_runtime_capabilities(
        required_environment=environment,
        dependency_readiness=readiness(environment),
        evaluated_at=NOW,
    )
    assert set(projection.required_capabilities) >= {
        ExecutorCapability.CHECKOUT,
        ExecutorCapability.ISOLATED_WORKTREE,
        ExecutorCapability.PROCESS_EXECUTION,
        ExecutorCapability.RUNTIME_INSPECTION,
        ExecutorCapability.TEST_EXECUTION,
        ExecutorCapability.EXACT_HEAD_VALIDATION,
    }
    assert route(projection).selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER


def test_1280_connector_read_write_is_not_runtime_compatibility() -> None:
    environment = spec()
    projection = project_pre_pr_runtime_capabilities(
        required_environment=environment,
        dependency_readiness=readiness(environment),
        evaluated_at=NOW,
    )
    result = route(projection, runner_caps=())
    assert result.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
    assert ExecutorRouteReason.GOVERNED_RUNNER_MISSING_REQUIRED_CAPABILITY in result.route_reasons
    assert ExecutorRouteReason.NO_CAPABLE_APPROVED_ROUTE in result.route_reasons
    assert result.selected_route is not ExecutorRoute.CHATGPT_CONNECTOR_NATIVE


def test_preparation_required_adds_dependency_installation_capability() -> None:
    environment = spec()
    projection = project_pre_pr_runtime_capabilities(
        required_environment=environment,
        dependency_readiness=readiness(
            environment, status=DependencyPreparationStatus.PREPARATION_REQUIRED
        ),
        evaluated_at=NOW,
    )
    assert ExecutorCapability.DEPENDENCY_INSTALLATION in projection.required_capabilities
    assert projection.dependency_preparation_status is DependencyPreparationStatus.PREPARATION_REQUIRED


def test_stale_readiness_fails_closed_through_existing_918_flag() -> None:
    environment = spec()
    projection = project_pre_pr_runtime_capabilities(
        required_environment=environment,
        dependency_readiness=readiness(
            environment,
            observed_at="2026-08-19T03:00:00Z",
            expires_at="2026-08-19T04:00:00Z",
        ),
        evaluated_at=NOW,
    )
    assert projection.evidence_stale is True
    result = route(projection)
    assert result.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
    assert result.route_reasons == (ExecutorRouteReason.EVIDENCE_STALE,)


def test_python_capable_runner_uses_same_projection_without_new_route() -> None:
    environment = spec(ecosystem=DependencyEcosystem.PYTHON_PIP)
    projection = project_pre_pr_runtime_capabilities(
        required_environment=environment,
        dependency_readiness=readiness(environment),
        evaluated_at=NOW,
    )
    assert route(projection).selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER


def test_projection_creates_no_authority_or_side_effects() -> None:
    environment = spec()
    projection = project_pre_pr_runtime_capabilities(
        required_environment=environment,
        dependency_readiness=readiness(environment),
        evaluated_at=NOW,
    )
    assert projection.execution_authorized is False
    assert projection.github_writes_authorized is False
    assert projection.external_writes_authorized is False
    assert projection.merge_authorized is False
    assert projection.side_effects_performed is False
