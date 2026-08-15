from __future__ import annotations

from dataclasses import dataclass

from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyArtifactIdentity,
    DependencyCacheState,
    DependencyEcosystem,
    DependencyInstallMode,
    DependencyPreparationStatus,
    LocalProjectRequirement,
    QualificationOnlyDependencyPin,
    RequiredEnvironmentSpec,
)
from workflow_scheduler.execution.dependency_preparation import (
    DependencyCommandObservation,
    DependencyPreparationObservation,
    execute_dependency_preparation,
    plan_dependency_preparation,
)

SHA = "a" * 64
LOCK = "c" * 64
HEAD = "b" * 40


def artifact(path: str, digest: str = SHA) -> DependencyArtifactIdentity:
    return DependencyArtifactIdentity(relative_path=path, sha256=digest)


def observation(**changes) -> DependencyPreparationObservation:
    values = dict(
        execution_surface_id="surface:1",
        workspace_identity="workspace:1",
        source_sha=HEAD,
        environment_health_evidence_id="health:1",
        runtime_version="3.12.1",
        runtime_compatible=True,
        package_manager_version="24.0",
        manifest_matches=True,
        lock_matches=True,
        source_identity_matches=True,
        source_reachable=True,
        package_available=True,
        cache_state=DependencyCacheState.NOT_APPLICABLE,
    )
    values.update(changes)
    return DependencyPreparationObservation(**values)


def python_spec(*, qualification: bool = False) -> RequiredEnvironmentSpec:
    return RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root="repo",
        runtime_requirement=">=3.11",
        dependency_manifest_identity=artifact("requirements-dev.txt"),
        lock_or_constraints_identity=None,
        install_mode=(
            DependencyInstallMode.QUALIFICATION_ONLY
            if qualification
            else DependencyInstallMode.NORMAL
        ),
        qualification_only_pins=(
            (QualificationOnlyDependencyPin(package="hypothesis", version="6.165.9"),)
            if qualification
            else ()
        ),
        approved_source_identity="pypi.org/simple",
        required_validation_command_ids=("pytest",),
    )


def node_spec(*, lock: bool = True, lock_generation: bool = False) -> RequiredEnvironmentSpec:
    return RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.NODE_NPM,
        package_root="08_Tooling/instructional-materials-coach/picture-perfect-coach",
        runtime_requirement=">=20.19.0",
        dependency_manifest_identity=artifact(
            "08_Tooling/instructional-materials-coach/picture-perfect-coach/package.json"
        ),
        lock_or_constraints_identity=(
            artifact(
                "08_Tooling/instructional-materials-coach/picture-perfect-coach/package-lock.json",
                LOCK,
            )
            if lock
            else None
        ),
        install_mode=(
            DependencyInstallMode.ABSENT_AUTHORIZED_LOCK_GENERATION
            if lock_generation
            else DependencyInstallMode.NORMAL
        ),
        approved_source_identity="registry.npmjs.org",
        required_validation_command_ids=("npm-build", "npm-test"),
    )


def test_935_python_root_uses_one_bounded_pip_install() -> None:
    plan = plan_dependency_preparation(
        python_spec(), observation(), evaluated_at="2026-08-15T20:00:00Z"
    )
    assert plan.status is DependencyPreparationStatus.PREPARATION_REQUIRED
    assert plan.argv == (
        "python",
        "-m",
        "pip",
        "install",
        "-r",
        "requirements-dev.txt",
    )


def test_1138_qualification_pin_stays_structured_and_exact() -> None:
    plan = plan_dependency_preparation(
        python_spec(qualification=True),
        observation(),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.argv[-1] == "hypothesis==6.165.9"


def test_python_offline_requires_proven_complete_bundle() -> None:
    blocked = plan_dependency_preparation(
        python_spec(),
        observation(
            source_reachable=False,
            cache_state=DependencyCacheState.UNKNOWN,
        ),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert blocked.status is DependencyPreparationStatus.BLOCKED
    assert "dependency.cache-incomplete" in blocked.reason_codes
    allowed = plan_dependency_preparation(
        python_spec(),
        observation(
            source_reachable=False,
            cache_state=DependencyCacheState.CURRENT_COMPLETE,
            offline_source_identity="wheelhouse:sha256-abc",
        ),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert allowed.argv[:6] == (
        "python",
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
    )


def test_node_lock_uses_npm_ci_and_never_npm_install() -> None:
    plan = plan_dependency_preparation(
        node_spec(),
        observation(runtime_version="22.16.0", package_manager_version="10.9.2"),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.argv == ("npm", "ci")


def test_node_offline_uses_only_npm_ci_offline() -> None:
    plan = plan_dependency_preparation(
        node_spec(),
        observation(
            runtime_version="22.16.0",
            package_manager_version="10.9.2",
            source_reachable=False,
            cache_state=DependencyCacheState.CURRENT_COMPLETE,
            offline_source_identity="npm-cache:sha256-abc",
        ),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.argv == ("npm", "ci", "--offline")
    assert "--prefer-offline" not in plan.argv


def test_1183_exact_failure_blocks_without_lock_or_network() -> None:
    plan = plan_dependency_preparation(
        node_spec(lock=False, lock_generation=True),
        observation(
            runtime_version="22.16.0",
            package_manager_version="10.9.2",
            lock_matches=None,
            source_reachable=False,
            cache_state=DependencyCacheState.UNKNOWN,
        ),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.status is DependencyPreparationStatus.BLOCKED
    assert plan.argv is None


def test_authorized_lock_generation_returns_source_update_required_after_success() -> None:
    spec = node_spec(lock=False, lock_generation=True)

    @dataclass
    class Runner:
        calls: int = 0
        argv: tuple[str, ...] | None = None

        def run(
            self, argv: tuple[str, ...], *, workspace_identity: str
        ) -> DependencyCommandObservation:
            self.calls += 1
            self.argv = argv
            return DependencyCommandObservation(
                attempted=True,
                succeeded=True,
                resolved_dependency_identity="lock:generated",
            )

    runner = Runner()
    evidence = execute_dependency_preparation(
        spec,
        observation(
            runtime_version="22.16.0",
            package_manager_version="10.9.2",
            lock_matches=None,
        ),
        runner,
        evaluated_at="2026-08-15T20:00:00Z",
        expires_at="2026-08-15T21:00:00Z",
    )
    assert runner.calls == 1
    assert runner.argv == (
        "npm",
        "install",
        "--package-lock-only",
        "--ignore-scripts",
    )
    assert (
        evidence.preparation_status
        is DependencyPreparationStatus.SOURCE_UPDATE_REQUIRED
    )
    assert evidence.reason_codes == ("dependency.source-update-required",)


def test_missing_package_manager_or_manifest_drift_blocks_before_runner() -> None:
    assert plan_dependency_preparation(
        python_spec(),
        observation(package_manager_version=None),
        evaluated_at="2026-08-15T20:00:00Z",
    ).reason_codes == ("dependency.package-manager-unavailable",)
    assert plan_dependency_preparation(
        python_spec(),
        observation(manifest_matches=False),
        evaluated_at="2026-08-15T20:00:00Z",
    ).reason_codes == ("dependency.manifest-drift",)


def test_runtime_mismatch_blocks_before_preparation() -> None:
    plan = plan_dependency_preparation(
        python_spec(),
        observation(runtime_compatible=False),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.status is DependencyPreparationStatus.BLOCKED
    assert plan.reason_codes == ("runtime.incompatible",)


def test_local_projects_make_editability_explicit() -> None:
    editable = RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
        runtime_requirement=">=3.11",
        dependency_manifest_identity=artifact("requirements-dev.txt"),
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        local_project_requirements=(
            LocalProjectRequirement(
                relative_path="src", sha256=SHA, editable=True
            ),
        ),
        approved_source_identity="pypi.org/simple",
        required_validation_command_ids=("pytest",),
    )
    plan = plan_dependency_preparation(
        editable, observation(), evaluated_at="2026-08-15T20:00:00Z"
    )
    assert plan.argv[-2:] == ("-e", "src")
