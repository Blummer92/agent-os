from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from types import SimpleNamespace

from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyArtifactIdentity,
    DependencyCacheState,
    DependencyEcosystem,
    DependencyInstallMode,
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    LocalProjectRequirement,
    QualificationOnlyDependencyPin,
    ReproducibilityLevel,
    RequiredEnvironmentSpec,
)
from workflow_scheduler.execution import single_issue_runtime as runtime_module
from workflow_scheduler.execution.single_issue_pilot import WorkspaceInspection
from workflow_scheduler.execution.concrete_runtime_adapters import (
    ConcreteDependencyCommandRunner,
    ConcreteDependencyObservationProvider,
    ConcreteDependencyPreparationInputs,
    _local_project_sha256,
    _python_dependency_environment_directory,
)
from workflow_scheduler.execution.dependency_preparation import (
    POST_PREPARATION_DRIFT,
    UNDECLARED_LOCAL_PROJECT,
    UNDECLARED_PACKAGE_SOURCE,
    UNSUPPORTED_SOURCE_INDIRECTION,
    BoundDependencyPreparationAdapter,
    DependencyCommandObservation,
    DependencyPreparationObservation,
    dependency_inputs_changed,
    execute_dependency_preparation,
    plan_dependency_preparation,
    validate_npm_lock_source_forms,
    validate_python_requirements_source_forms,
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
        environment_health_current=True,
        runtime_version="3.12.1",
        runtime_compatible=True,
        package_manager_version="24.0",
        manifest_matches=True,
        lock_matches=True,
        local_projects_match=True,
        source_identity_matches=True,
        source_reachable=True,
        package_available=True,
        cache_state=DependencyCacheState.NOT_APPLICABLE,
    )
    values.update(changes)
    return DependencyPreparationObservation(**values)


# The actual editable local projects declared by the repository-root
# `requirements-dev.txt`. #935 requires these to enter through the structured
# local-project contract rather than through raw manifest text.
ROOT_EDITABLE_PROJECTS = (
    "08_Tooling/agent-memory-context-manager",
    "08_Tooling/visual-asset-intake",
    "08_Tooling/workflow-scheduler",
    "src",
)

ROOT_REQUIREMENTS_TEXT = """\
# Development & Testing Dependencies
pytest>=7.0.0
pytest-mock>=3.10.0
PyGithub==2.9.1

# Local editable packages
-e ./src
-e ./08_Tooling/agent-memory-context-manager
-e ./08_Tooling/workflow-scheduler
-e ./08_Tooling/visual-asset-intake
"""


def local_projects(
    paths: tuple[str, ...] = ROOT_EDITABLE_PROJECTS, *, editable: bool = True
) -> tuple[LocalProjectRequirement, ...]:
    return tuple(
        LocalProjectRequirement(relative_path=path, sha256=SHA, editable=editable)
        for path in sorted(paths)
    )


def python_spec(
    *,
    qualification: bool = False,
    projects: tuple[LocalProjectRequirement, ...] | None = None,
) -> RequiredEnvironmentSpec:
    return RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
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
        local_project_requirements=(
            local_projects() if projects is None else projects
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


def ready_evidence(
    spec: RequiredEnvironmentSpec, *, execution_surface_id: str = "surface:1"
) -> DependencyReadinessEvidence:
    return DependencyReadinessEvidence(
        execution_surface_id=execution_surface_id,
        workspace_identity="workspace:1",
        source_sha=HEAD,
        required_environment_id=spec.required_environment_id,
        package_root=spec.package_root,
        ecosystem=spec.ecosystem,
        runtime_version="3.12.1",
        package_manager_version="24.0",
        declared_dependency_identity=spec.dependency_manifest_identity.sha256,
        lock_or_constraints_identity=(
            None
            if spec.lock_or_constraints_identity is None
            else spec.lock_or_constraints_identity.sha256
        ),
        install_mode=spec.install_mode,
        source_or_registry_identity=spec.approved_source_identity,
        cache_state=DependencyCacheState.NOT_APPLICABLE,
        preparation_status=DependencyPreparationStatus.READY,
        resolved_dependency_identity="resolved:abc",
        environment_health_evidence_id="health:1",
        observed_at="2026-08-15T19:30:00Z",
        expires_at="2026-08-15T21:00:00Z",
        reproducibility_level=(
            ReproducibilityLevel.LOCKED
            if spec.lock_or_constraints_identity is not None
            else ReproducibilityLevel.RESOLVED
        ),
        reason_codes=(),
    )


def test_935_python_root_uses_one_bounded_pip_install() -> None:
    spec = python_spec()
    plan = plan_dependency_preparation(
        spec, observation(), evaluated_at="2026-08-15T20:00:00Z"
    )
    assert plan.status is DependencyPreparationStatus.PREPARATION_REQUIRED
    assert plan.argv == (
        "python",
        "-m",
        "pip",
        "install",
        "--only-binary=:all:",
        "--index-url=https://pypi.org/simple",
        "-r",
        "requirements-dev.txt",
        "-e",
        "08_Tooling/agent-memory-context-manager",
        "-e",
        "08_Tooling/visual-asset-intake",
        "-e",
        "08_Tooling/workflow-scheduler",
        "-e",
        "src",
    )


def test_935_root_fixture_structurally_binds_every_actual_editable_project() -> None:
    """#935: the four real `requirements-dev.txt` editables are structural, not raw text."""
    spec = python_spec()
    declared = {
        requirement.relative_path: requirement
        for requirement in spec.local_project_requirements
    }
    assert tuple(sorted(declared)) == ROOT_EDITABLE_PROJECTS
    assert all(requirement.editable for requirement in declared.values())
    # The same four projects are exactly what the manifest text declares, so the
    # raw manifest introduces no local project the frozen contract does not carry.
    assert validate_python_requirements_source_forms(ROOT_REQUIREMENTS_TEXT, spec) == ()


def test_1138_qualification_pin_stays_structured_and_exact() -> None:
    plan = plan_dependency_preparation(
        python_spec(qualification=True),
        observation(),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.argv[-1] == "hypothesis==6.165.9"


def test_stale_environment_health_blocks_before_preparation() -> None:
    plan = plan_dependency_preparation(
        python_spec(),
        observation(environment_health_current=False),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.status is DependencyPreparationStatus.BLOCKED
    assert plan.argv is None
    assert plan.reason_codes == ("dependency.environment-stale",)


def test_other_surface_ready_evidence_blocks_instead_of_repreparing() -> None:
    spec = python_spec()
    plan = plan_dependency_preparation(
        spec,
        observation(
            existing_ready_evidence=ready_evidence(
                spec, execution_surface_id="surface:other"
            )
        ),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.status is DependencyPreparationStatus.BLOCKED
    assert plan.argv is None
    assert plan.reason_codes == ("dependency.environment-surface-mismatch",)


def test_python_offline_requires_proven_complete_bundle_and_separate_location() -> None:
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
    identity_only = plan_dependency_preparation(
        python_spec(),
        observation(
            source_reachable=False,
            cache_state=DependencyCacheState.CURRENT_COMPLETE,
            offline_source_identity="wheelhouse:sha256-abc",
        ),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert identity_only.status is DependencyPreparationStatus.BLOCKED
    allowed = plan_dependency_preparation(
        python_spec(),
        observation(
            source_reachable=False,
            cache_state=DependencyCacheState.CURRENT_COMPLETE,
            offline_source_identity="wheelhouse:sha256-abc",
            offline_source_location=".agent-os/wheelhouse",
        ),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert allowed.argv[:7] == (
        "python",
        "-m",
        "pip",
        "install",
        "--only-binary=:all:",
        "--no-index",
        "--find-links",
    )
    assert allowed.argv[7] == ".agent-os/wheelhouse"
    assert allowed.source_identity == "wheelhouse:sha256-abc"
    # Offline preparation must not also carry an index URL.
    assert not any(item.startswith("--index-url") for item in allowed.argv)


def test_node_lock_uses_npm_ci_and_never_npm_install() -> None:
    plan = plan_dependency_preparation(
        node_spec(),
        observation(runtime_version="22.16.0", package_manager_version="10.9.2"),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.argv == (
        "npm",
        "ci",
        "--ignore-scripts",
        "--no-audit",
        "--registry=https://registry.npmjs.org",
    )


def test_npm_preparation_governs_install_scripts_audit_and_registry() -> None:
    """R2: install-time code execution and audit traffic are explicit, not inherited."""
    plan = plan_dependency_preparation(
        node_spec(),
        observation(runtime_version="22.16.0", package_manager_version="10.9.2"),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert "--ignore-scripts" in plan.argv
    assert "--no-audit" in plan.argv
    assert "--registry=https://registry.npmjs.org" in plan.argv
    assert "npm" == plan.argv[0] and "ci" == plan.argv[1]


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
    assert plan.argv == (
        "npm",
        "ci",
        "--ignore-scripts",
        "--no-audit",
        "--registry=https://registry.npmjs.org",
        "--offline",
    )
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
        "--no-audit",
        "--registry=https://registry.npmjs.org",
    )
    assert (
        evidence.preparation_status
        is DependencyPreparationStatus.SOURCE_UPDATE_REQUIRED
    )
    assert evidence.reason_codes == ("dependency.source-update-required",)


def test_missing_resolved_environment_evidence_fails_closed() -> None:
    @dataclass
    class Runner:
        def run(
            self, argv: tuple[str, ...], *, workspace_identity: str
        ) -> DependencyCommandObservation:
            return DependencyCommandObservation(attempted=True, succeeded=True)

    evidence = execute_dependency_preparation(
        python_spec(),
        observation(),
        Runner(),
        evaluated_at="2026-08-15T20:00:00Z",
        expires_at="2026-08-15T21:00:00Z",
    )
    assert evidence.preparation_status is DependencyPreparationStatus.FAILED
    assert evidence.reason_codes == ("dependency.resolved-evidence-missing",)


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
        editable,
        observation(local_projects_match=True),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.argv[-2:] == ("-e", "src")


def test_editable_source_drift_blocks_before_preparation() -> None:
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
        editable,
        observation(local_projects_match=False),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.status is DependencyPreparationStatus.BLOCKED
    assert plan.argv is None
    assert plan.reason_codes == ("dependency.editable-source-drift",)


def test_dependency_input_drift_requires_recheck_only_for_bound_inputs() -> None:
    spec = node_spec()
    assert dependency_inputs_changed(
        spec,
        (
            "08_Tooling/instructional-materials-coach/picture-perfect-coach/package-lock.json",
        ),
    )
    assert not dependency_inputs_changed(spec, ("README.md",))


def test_bound_adapter_allows_initial_check_plus_one_changed_input_recheck() -> None:
    spec = python_spec()

    @dataclass
    class Provider:
        calls: int = 0

        def observe(self, *, workspace_identity, existing_ready_evidence):
            self.calls += 1
            return observation(
                workspace_identity=workspace_identity,
                existing_ready_evidence=existing_ready_evidence,
            )

    @dataclass
    class Runner:
        calls: int = 0

        def run(self, argv, *, workspace_identity):
            self.calls += 1
            return DependencyCommandObservation(
                attempted=True,
                succeeded=True,
                resolved_dependency_identity=f"resolved:{self.calls}",
            )

    provider = Provider()
    runner = Runner()
    adapter = BoundDependencyPreparationAdapter(
        spec=spec,
        observations=provider,
        runner=runner,
        evaluated_at="2026-08-15T20:00:00Z",
        expires_at="2026-08-15T21:00:00Z",
    )
    first = adapter.prepare(workspace_identity="workspace:1")
    second = adapter.prepare(workspace_identity="workspace:1")
    assert first.preparation_status is DependencyPreparationStatus.READY
    assert second.preparation_status is DependencyPreparationStatus.READY
    assert runner.calls == 1
    assert provider.calls == 2
    try:
        adapter.prepare(workspace_identity="workspace:1")
    except RuntimeError as exc:
        assert "initial readiness and one changed-input recheck" in str(exc)
    else:
        raise AssertionError("third preparation call must fail closed")


def test_concrete_observer_verifies_workspace_manifest_and_lock_hashes(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    package = workspace / "app"
    package.mkdir(parents=True)
    manifest = package / "package.json"
    lock = package / "package-lock.json"
    manifest.write_text('{"name":"app"}\n', encoding="utf-8")
    lock.write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    lock_sha = hashlib.sha256(lock.read_bytes()).hexdigest()
    spec = RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.NODE_NPM,
        package_root="app",
        runtime_requirement=">=20.19.0",
        dependency_manifest_identity=artifact("app/package.json", manifest_sha),
        lock_or_constraints_identity=artifact("app/package-lock.json", lock_sha),
        install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity="registry.npmjs.org",
        required_validation_command_ids=("npm-test",),
    )
    inputs = ConcreteDependencyPreparationInputs(
        execution_surface_id="surface:1",
        environment_health_evidence_id="health:1",
        environment_health_current=True,
        runtime_version="22.16.0",
        runtime_compatible=True,
        package_manager_version="10.9.2",
        observed_source_identity="registry.npmjs.org",
        source_reachable=True,
        package_available=True,
        cache_state=DependencyCacheState.NOT_APPLICABLE,
        expires_at="2026-08-15T21:00:00Z",
    )
    provider = ConcreteDependencyObservationProvider(
        SimpleNamespace(executor_cwd=str(workspace), source_head_sha=HEAD),
        spec,
        inputs,
    )
    first = provider.observe(
        workspace_identity="workspace:1", existing_ready_evidence=None
    )
    assert first.manifest_matches is True
    assert first.lock_matches is True
    assert first.local_projects_match is True
    assert first.execution_surface_id == "surface:1"
    assert first.environment_health_evidence_id == "health:1"
    lock.write_text('{"lockfileVersion":2}\n', encoding="utf-8")
    second = provider.observe(
        workspace_identity="workspace:1", existing_ready_evidence=None
    )
    assert second.lock_matches is False


def test_concrete_observer_binds_local_project_directory_identity(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = workspace / "requirements-dev.txt"
    manifest.write_text("pytest>=8\n", encoding="utf-8")
    source = workspace / "src"
    source.mkdir()
    module = source / "module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    source_sha = _local_project_sha256(str(source))
    assert source_sha is not None
    spec = RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
        runtime_requirement=">=3.11",
        dependency_manifest_identity=artifact("requirements-dev.txt", manifest_sha),
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        local_project_requirements=(
            LocalProjectRequirement(
                relative_path="src", sha256=source_sha, editable=True
            ),
        ),
        approved_source_identity="pypi.org/simple",
        required_validation_command_ids=("pytest",),
    )
    inputs = ConcreteDependencyPreparationInputs(
        execution_surface_id="surface:1",
        environment_health_evidence_id="health:1",
        environment_health_current=True,
        runtime_version="3.12.1",
        runtime_compatible=True,
        package_manager_version="24.0",
        observed_source_identity="pypi.org/simple",
        source_reachable=True,
        package_available=True,
        cache_state=DependencyCacheState.NOT_APPLICABLE,
        expires_at="2026-08-15T21:00:00Z",
    )
    provider = ConcreteDependencyObservationProvider(
        SimpleNamespace(executor_cwd=str(workspace), source_head_sha=HEAD),
        spec,
        inputs,
    )
    first = provider.observe(
        workspace_identity="workspace:1", existing_ready_evidence=None
    )
    assert first.local_projects_match is True
    module.write_text("VALUE = 2\n", encoding="utf-8")
    second = provider.observe(
        workspace_identity="workspace:1", existing_ready_evidence=None
    )
    assert second.local_projects_match is False


def test_concrete_observer_preserves_other_surface_evidence_for_blocking(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = workspace / "requirements-dev.txt"
    manifest.write_bytes(b"x")
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    spec = RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
        runtime_requirement=">=3.11",
        dependency_manifest_identity=artifact("requirements-dev.txt", manifest_sha),
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity="pypi.org/simple",
        required_validation_command_ids=("pytest",),
    )
    wrong_surface = ready_evidence(spec, execution_surface_id="surface:other")
    inputs = ConcreteDependencyPreparationInputs(
        execution_surface_id="surface:1",
        environment_health_evidence_id="health:1",
        environment_health_current=True,
        runtime_version="3.12.1",
        runtime_compatible=True,
        package_manager_version="24.0",
        observed_source_identity="pypi.org/simple",
        source_reachable=True,
        package_available=True,
        cache_state=DependencyCacheState.NOT_APPLICABLE,
        expires_at="2026-08-15T21:00:00Z",
        existing_ready_evidence=wrong_surface,
    )
    provider = ConcreteDependencyObservationProvider(
        SimpleNamespace(executor_cwd=str(workspace), source_head_sha=HEAD),
        spec,
        inputs,
    )
    observed = provider.observe(
        workspace_identity="workspace:1", existing_ready_evidence=None
    )
    assert observed.existing_ready_evidence is wrong_surface
    plan = plan_dependency_preparation(
        spec, observed, evaluated_at="2026-08-15T20:00:00Z"
    )
    assert plan.reason_codes == ("dependency.environment-surface-mismatch",)


def test_python_concrete_runner_creates_clean_external_venv_before_install(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    configuration = SimpleNamespace(
        configuration_fingerprint="concrete-adapters:test",
        workspace_parent=str(tmp_path),
        executor_cwd=str(workspace),
        validation_total_timeout_seconds=30.0,
        executor_grace_period_seconds=1.0,
        validation_max_output_bytes=65_536,
        delegated_parent_cgroup=None,
        invocation_id="invocation:1",
        environment_policy="isolated-path-home-c-locale",
        repository_root=str(workspace),
        required_environment_spec=python_spec(),
    )
    runner = ConcreteDependencyCommandRunner(configuration, python_spec())
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, *, suffix, include_dependency_environment=True):
        calls.append(tuple(argv))
        return SimpleNamespace(
            return_code=0,
            termination_confirmed=True,
            timeout_observed=False,
            cancellation_requested=False,
            stderr_text="",
            reason="",
            stdout_text="pkg==1.0\n",
        )

    runner._run = fake_run  # type: ignore[method-assign]
    result = runner.run(
        ("python", "-m", "pip", "install", "-r", "requirements-dev.txt"),
        workspace_identity="workspace:1",
    )
    venv = _python_dependency_environment_directory(configuration)
    assert result.succeeded is True
    assert calls[0] == ("python", "-m", "venv", "--clear", venv)
    assert calls[1][0] == f"{venv}/bin/python"
    assert calls[1][1:] == ("-m", "pip", "install", "-r", "requirements-dev.txt")
    assert calls[2] == (f"{venv}/bin/python", "-m", "pip", "freeze", "--all")


def test_runtime_wrappers_refuse_executor_and_validator_before_ready() -> None:
    class Executor:
        calls = 0

        def run(self, request):
            self.calls += 1
            raise AssertionError("executor must not be delegated before READY")

    class Validator:
        calls = 0

        def validate(self, request):
            self.calls += 1
            raise AssertionError("validator must not be delegated before READY")

    gate = SimpleNamespace(
        ready=False,
        recheck_required=False,
        blocker_summary="dependency-readiness:blocked",
        note_executor_changes=lambda changed_paths: None,
    )
    executor = Executor()
    validator = Validator()
    wrapped_executor = runtime_module._DependencyReadyExecutor(executor, gate)
    wrapped_validator = runtime_module._DependencyReadyValidator(validator, gate)
    try:
        wrapped_executor.run(object())
    except RuntimeError as exc:
        assert "READY dependency evidence" in str(exc)
    else:
        raise AssertionError("executor dispatch must fail closed")
    validation = wrapped_validator.validate(SimpleNamespace(workspace_identity="workspace:1"))
    assert validation.attempted is False
    assert validation.passed is False
    # AOS-VALTERM1 (#1205): nothing was ever dispatched, so this is
    # vacuously terminal -- not silently read as unresolved.
    assert validation.started is False
    assert validation.termination_confirmed is True
    assert validation.possible_partial_effects is False
    assert executor.calls == 0
    assert validator.calls == 0


# ---------------------------------------------------------------------------
# R1 -- structured dependency/source enforcement
# ---------------------------------------------------------------------------


def python_source_forms(text: str, **spec_changes) -> tuple[str, ...]:
    return validate_python_requirements_source_forms(text, python_spec(**spec_changes))


def test_r1_undeclared_python_editable_local_project_is_blocked() -> None:
    assert python_source_forms("-e ./08_Tooling/not-declared") == (
        UNDECLARED_LOCAL_PROJECT,
    )
    # An otherwise-declared project may not enter without editable authorization.
    assert python_source_forms(
        "-e ./src", projects=local_projects(("src",), editable=False)
    ) == (UNDECLARED_LOCAL_PROJECT,)


def test_r1_declared_editable_project_with_source_drift_is_blocked() -> None:
    spec = python_spec()
    plan = plan_dependency_preparation(
        spec,
        observation(local_projects_match=False),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.status is DependencyPreparationStatus.BLOCKED
    assert plan.reason_codes == ("dependency.editable-source-drift",)
    assert plan.argv is None


def test_r1_undeclared_python_package_sources_are_blocked() -> None:
    cases = {
        "alternate index": "--index-url https://internal.example/simple",
        "extra index": "--extra-index-url https://internal.example/simple",
        "short alternate index": "-i https://internal.example/simple",
        "find links": "--find-links ./vendor-wheels",
        "short find links": "-f https://internal.example/wheels",
        "direct url": "requests @ https://internal.example/requests-2.0.0.whl",
        "bare url": "https://internal.example/requests-2.0.0.tar.gz",
        "vcs": "package @ git+https://github.com/example/package@main",
        "bare vcs": "git+https://github.com/example/package@main#egg=package",
        "archive": "./vendor/requests-2.0.0.tar.gz",
        "interpolated": "--index-url https://${TOKEN}@internal.example/simple",
        "trusted host": "--trusted-host internal.example",
        "no index": "--no-index",
    }
    for label, line in cases.items():
        assert python_source_forms(line) == (UNDECLARED_PACKAGE_SOURCE,), label


def test_r1_nested_python_source_indirection_is_blocked() -> None:
    for line in ("-r other-requirements.txt", "--requirement nested.txt",
                 "-c constraints.txt", "--constraint constraints.txt"):
        assert python_source_forms(line) == (UNSUPPORTED_SOURCE_INDIRECTION,), line
    # An unrecognised directive is never delegated to pip unvalidated.
    assert python_source_forms("--some-future-option value") == (
        UNSUPPORTED_SOURCE_INDIRECTION,
    )


def test_r1_ordinary_named_requirements_and_comments_stay_authorized() -> None:
    text = (
        "# comment line\n"
        "pytest>=7.0.0  # trailing comment\n"
        "\n"
        "PyGithub==2.9.1\n"
        "coverage[toml]>=6.0.0\n"
        'black>=22.0.0 ; python_version >= "3.11"\n'
        "pytest-\\\n"
        "mock>=3.10.0\n"
    )
    assert python_source_forms(text) == ()


def test_r1_approved_python_source_binding_is_explicit() -> None:
    plan = plan_dependency_preparation(
        python_spec(), observation(), evaluated_at="2026-08-15T20:00:00Z"
    )
    assert "--index-url=https://pypi.org/simple" in plan.argv
    assert plan.source_identity == "pypi.org/simple"


def test_r1_ambient_pip_and_npm_config_cannot_redirect_the_approved_source() -> None:
    """Ambient config files are disabled with each tool's own documented value."""
    from workflow_scheduler.execution.concrete_runtime_adapters import _environment

    configuration = SimpleNamespace(
        environment_policy=None,
        repository_root="/repo",
        required_environment_spec=None,
    )
    # `_environment` validates the policy identity first; reuse the real one.
    from workflow_scheduler.execution.runtime_configuration import ENVIRONMENT_POLICY

    configuration.environment_policy = ENVIRONMENT_POLICY
    environment = _environment(configuration)
    assert environment["PIP_CONFIG_FILE"] == os.devnull
    assert environment["NPM_CONFIG_USERCONFIG"] == os.devnull
    assert environment["NPM_CONFIG_GLOBALCONFIG"] == os.devnull
    # No ambient index/registry variable is forwarded into preparation.
    assert not any(
        key.startswith(("PIP_INDEX", "PIP_EXTRA", "NPM_CONFIG_REGISTRY"))
        for key in environment
    )


def npm_lock(*entries: tuple[str, dict]) -> dict:
    packages = {"": {"name": "picture-perfect-coach", "version": "1.0.0"}}
    packages.update(dict(entries))
    return {"lockfileVersion": 3, "packages": packages}


def test_r1_npm_lockfile_with_unapproved_remote_source_is_blocked() -> None:
    payload = npm_lock(
        (
            "node_modules/left-pad",
            {
                "version": "1.3.0",
                "resolved": "https://internal.example/left-pad-1.3.0.tgz",
            },
        )
    )
    assert validate_npm_lock_source_forms(payload, node_spec()) == (
        UNDECLARED_PACKAGE_SOURCE,
    )
    insecure = npm_lock(
        (
            "node_modules/left-pad",
            {
                "version": "1.3.0",
                "resolved": "http://registry.npmjs.org/left-pad-1.3.0.tgz",
            },
        )
    )
    assert validate_npm_lock_source_forms(insecure, node_spec()) == (
        UNDECLARED_PACKAGE_SOURCE,
    )


def test_r1_npm_lockfile_with_unapproved_git_file_or_directory_source_is_blocked() -> None:
    git_entry = npm_lock(
        (
            "node_modules/tool",
            {"version": "1.0.0", "resolved": "git+ssh://git@github.com/example/tool.git#abc"},
        )
    )
    assert validate_npm_lock_source_forms(git_entry, node_spec()) == (
        UNDECLARED_PACKAGE_SOURCE,
    )
    file_entry = npm_lock(
        ("node_modules/tool", {"version": "1.0.0", "resolved": "file:../vendor/tool"})
    )
    assert validate_npm_lock_source_forms(file_entry, node_spec()) == (
        UNDECLARED_LOCAL_PROJECT,
    )
    directory_entry = npm_lock(("packages/helper", {"version": "1.0.0"}))
    assert validate_npm_lock_source_forms(directory_entry, node_spec()) == (
        UNDECLARED_LOCAL_PROJECT,
    )
    link_entry = npm_lock(
        ("node_modules/helper", {"link": True, "resolved": "packages/helper"})
    )
    assert validate_npm_lock_source_forms(link_entry, node_spec()) == (
        UNDECLARED_LOCAL_PROJECT,
    )


def test_r1_npm_registry_binding_matches_the_approved_identity() -> None:
    approved = npm_lock(
        (
            "node_modules/left-pad",
            {
                "version": "1.3.0",
                "resolved": "https://registry.npmjs.org/left-pad/-/left-pad-1.3.0.tgz",
            },
        )
    )
    assert validate_npm_lock_source_forms(approved, node_spec()) == ()
    plan = plan_dependency_preparation(
        node_spec(),
        observation(runtime_version="22.16.0", package_manager_version="10.9.2"),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert "--registry=https://registry.npmjs.org" in plan.argv


def test_r1_malformed_or_absent_npm_lock_payload_fails_closed() -> None:
    assert validate_npm_lock_source_forms(["not", "a", "mapping"], node_spec()) == (
        UNDECLARED_PACKAGE_SOURCE,
    )
    assert validate_npm_lock_source_forms({"lockfileVersion": 3}, node_spec()) == (
        UNDECLARED_PACKAGE_SOURCE,
    )


def test_r1_observed_source_form_findings_block_before_any_command() -> None:
    plan = plan_dependency_preparation(
        python_spec(),
        observation(source_form_reason_codes=(UNDECLARED_PACKAGE_SOURCE,)),
        evaluated_at="2026-08-15T20:00:00Z",
    )
    assert plan.status is DependencyPreparationStatus.BLOCKED
    assert plan.argv is None
    assert plan.reason_codes == (UNDECLARED_PACKAGE_SOURCE,)


# ---------------------------------------------------------------------------
# R2 -- post-preparation workspace integrity and install-time code policy
# ---------------------------------------------------------------------------


def safe_inspection() -> WorkspaceInspection:
    return WorkspaceInspection(
        resolved=True,
        repository="Blummer92/agent-os",
        branch="agent/1185-dependency-readiness",
        expected_revision=HEAD,
        actual_revision=HEAD,
        clean=True,
        detached=False,
        reused=False,
        locked=True,
        locked_expected=True,
        missing=False,
        prunable=False,
    )


class _FakeWorkspace:
    """Minimal stand-in exposing the same inspect/complete-state seam #760 owns."""

    def __init__(self, *, complete=True, is_clean=True, observed_sha=HEAD) -> None:
        self._observation = SimpleNamespace(
            complete=complete, is_clean=is_clean, observed_sha=observed_sha
        )
        self.complete_state_calls = 0

    def create(self, request):
        raise AssertionError("create must not be called by this test")

    def inspect(self, handle):
        return safe_inspection()

    def inspect_complete_state(self, handle, *, observation_kind):
        self.complete_state_calls += 1
        assert observation_kind in ("initial", "final")
        return self._observation

    def cleanup(self, handle):
        raise AssertionError("cleanup must not be called by this test")


class _ReadyPreparer:
    def __init__(self, spec: RequiredEnvironmentSpec) -> None:
        self._spec = spec
        self.prepare_calls = 0

    def prepare(self, *, workspace_identity: str) -> DependencyReadinessEvidence:
        self.prepare_calls += 1
        return ready_evidence(self._spec)

    def requires_recheck(self, changed_paths: tuple[str, ...]) -> bool:
        return False


def _wire_gate(workspace: _FakeWorkspace, preparer: _ReadyPreparer):
    pilot_input = SimpleNamespace(
        source_head_sha=HEAD,
        evaluated_at="2026-08-15T20:00:00Z",
        repository="Blummer92/agent-os",
        branch="agent/1185-dependency-readiness",
    )
    gate = runtime_module._DependencyRuntimeGate(preparer, pilot_input)
    wrapped = runtime_module._DependencyReadyWorkspaceAdapter(
        workspace, gate, pilot_input
    )
    return gate, wrapped


def test_r2_clean_post_preparation_reinspection_allows_continuation() -> None:
    spec = python_spec()
    workspace = _FakeWorkspace()
    preparer = _ReadyPreparer(spec)
    gate, wrapped = _wire_gate(workspace, preparer)
    inspection = wrapped.inspect(SimpleNamespace(workspace_identity="workspace:1"))
    assert inspection.resolved is True
    assert gate.ready is True
    # The existing complete workspace-state inspection is reused, not duplicated.
    assert workspace.complete_state_calls == 1
    assert len(gate.post_preparation_observations) == 1


def test_r2_preparation_created_tracked_drift_forbids_ready_provider_and_validation() -> None:
    spec = python_spec()
    workspace = _FakeWorkspace(is_clean=False)
    preparer = _ReadyPreparer(spec)
    gate, wrapped = _wire_gate(workspace, preparer)
    inspection = wrapped.inspect(SimpleNamespace(workspace_identity="workspace:1"))

    assert inspection.resolved is False
    assert gate.ready is False
    assert POST_PREPARATION_DRIFT in inspection.reason

    class Executor:
        def run(self, request):
            raise AssertionError("provider dispatch must be refused after drift")

    class Validator:
        def validate(self, request):
            raise AssertionError("validation dispatch must be refused after drift")

    try:
        runtime_module._DependencyReadyExecutor(Executor(), gate).run(object())
    except RuntimeError as exc:
        assert "READY dependency evidence" in str(exc)
    else:
        raise AssertionError("executor dispatch must fail closed")
    result = runtime_module._DependencyReadyValidator(Validator(), gate).validate(
        SimpleNamespace(workspace_identity="workspace:1")
    )
    assert result.attempted is False and result.passed is False
    assert result.started is False
    assert result.termination_confirmed is True
    assert result.possible_partial_effects is False


def test_r2_incomplete_or_source_drifted_reinspection_fails_closed() -> None:
    spec = python_spec()
    for workspace in (
        _FakeWorkspace(complete=False),
        _FakeWorkspace(observed_sha="d" * 40),
    ):
        gate, wrapped = _wire_gate(workspace, _ReadyPreparer(spec))
        inspection = wrapped.inspect(SimpleNamespace(workspace_identity="workspace:1"))
        assert inspection.resolved is False
        assert gate.ready is False


def test_r2_missing_complete_state_inspection_fails_closed() -> None:
    class WithoutCompleteState:
        def inspect(self, handle):
            return safe_inspection()

    spec = python_spec()
    gate, wrapped = _wire_gate(WithoutCompleteState(), _ReadyPreparer(spec))
    inspection = wrapped.inspect(SimpleNamespace(workspace_identity="workspace:1"))
    assert inspection.resolved is False
    assert gate.ready is False
    assert "complete-state-inspection-unavailable" in inspection.reason


def test_r2_claimed_complete_npm_cache_with_failed_offline_install_fails_closed() -> None:
    """Required npm cache hardening: one attempt, FAILED, zero retry, zero fallback."""
    spec = node_spec()

    @dataclass
    class Runner:
        calls: list = None

        def __post_init__(self) -> None:
            self.calls = []

        def run(
            self, argv: tuple[str, ...], *, workspace_identity: str
        ) -> DependencyCommandObservation:
            self.calls.append(argv)
            return DependencyCommandObservation(
                attempted=True,
                succeeded=False,
                failure_reason_code="dependency.package-unavailable",
            )

    runner = Runner()
    evidence = execute_dependency_preparation(
        spec,
        observation(
            runtime_version="22.16.0",
            package_manager_version="10.9.2",
            source_reachable=False,
            cache_state=DependencyCacheState.CURRENT_COMPLETE,
            offline_source_identity="npm-cache:sha256-abc",
        ),
        runner,
        evaluated_at="2026-08-15T20:00:00Z",
        expires_at="2026-08-15T21:00:00Z",
    )
    assert evidence.preparation_status is DependencyPreparationStatus.FAILED
    assert evidence.reason_codes == ("dependency.package-unavailable",)
    assert evidence.retry_attempted is False
    # Exactly one `npm ci --offline` attempt: no retry and no online fallback.
    assert len(runner.calls) == 1
    assert runner.calls[0][:2] == ("npm", "ci")
    assert "--offline" in runner.calls[0]
    assert evidence.resolved_dependency_identity is None


def test_r2_concrete_observer_reports_source_forms_from_the_real_manifest(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = workspace / "requirements-dev.txt"
    manifest.write_text("pytest>=7.0.0\n--extra-index-url https://internal.example\n")
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()

    spec = RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
        runtime_requirement=">=3.11",
        dependency_manifest_identity=artifact("requirements-dev.txt", digest),
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity="pypi.org/simple",
        required_validation_command_ids=("pytest",),
    )
    configuration = SimpleNamespace(
        executor_cwd=str(workspace), source_head_sha=HEAD
    )
    inputs = ConcreteDependencyPreparationInputs(
        execution_surface_id="surface:1",
        environment_health_evidence_id="health:1",
        environment_health_current=True,
        runtime_version="3.12.1",
        runtime_compatible=True,
        package_manager_version="24.0",
        observed_source_identity="pypi.org/simple",
        source_reachable=True,
        package_available=True,
        cache_state=DependencyCacheState.NOT_APPLICABLE,
        expires_at="2026-08-15T21:00:00Z",
    )
    provider = ConcreteDependencyObservationProvider(configuration, spec, inputs)
    observed = provider.observe(
        workspace_identity="workspace:1", existing_ready_evidence=None
    )
    assert observed.manifest_matches is True
    assert observed.source_form_reason_codes == (UNDECLARED_PACKAGE_SOURCE,)

    plan = plan_dependency_preparation(
        spec, observed, evaluated_at="2026-08-15T20:00:00Z"
    )
    assert plan.status is DependencyPreparationStatus.BLOCKED
    assert plan.argv is None


def test_r2_unreadable_dependency_input_fails_closed(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
        runtime_requirement=">=3.11",
        dependency_manifest_identity=artifact("requirements-dev.txt"),
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity="pypi.org/simple",
        required_validation_command_ids=("pytest",),
    )
    configuration = SimpleNamespace(executor_cwd=str(workspace), source_head_sha=HEAD)
    from workflow_scheduler.execution.concrete_runtime_adapters import (
        _observed_source_form_reason_codes,
    )

    assert _observed_source_form_reason_codes(configuration, spec) == (
        UNSUPPORTED_SOURCE_INDIRECTION,
    )
