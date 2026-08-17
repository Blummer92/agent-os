from __future__ import annotations

import dataclasses

import pytest

from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyArtifactIdentity,
    DependencyCacheState,
    DependencyEcosystem,
    DependencyInstallMode,
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    QualificationOnlyDependencyPin,
    ReproducibilityLevel,
    RequiredEnvironmentSpec,
    dependency_readiness_evidence_payload,
    required_environment_spec_payload,
)

SHA = "a" * 64
HEAD = "b" * 40


def artifact(path: str, digest: str = SHA) -> DependencyArtifactIdentity:
    return DependencyArtifactIdentity(relative_path=path, sha256=digest)


def python_spec(**changes) -> RequiredEnvironmentSpec:
    values = dict(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
        runtime_requirement=">=3.11",
        dependency_manifest_identity=artifact("requirements-dev.txt"),
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity="pypi.org/simple",
        required_validation_command_ids=("pytest",),
    )
    values.update(changes)
    return RequiredEnvironmentSpec(**values)


def test_required_environment_is_immutable_and_content_addressed() -> None:
    spec = python_spec()
    same = python_spec(required_environment_id=spec.required_environment_id)
    assert same == spec
    assert spec.required_environment_id.startswith("required-environment:")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.package_root = "elsewhere"  # type: ignore[misc]


def test_qualification_pin_must_be_exact_and_isolated() -> None:
    pin = QualificationOnlyDependencyPin(package="hypothesis", version="6.165.9")
    spec = python_spec(
        install_mode=DependencyInstallMode.QUALIFICATION_ONLY,
        qualification_only_pins=(pin,),
    )
    assert spec.qualification_only_pins[0].requirement == "hypothesis==6.165.9"
    with pytest.raises(ValueError):
        QualificationOnlyDependencyPin(package="hypothesis", version=">=6")
    with pytest.raises(ValueError):
        python_spec(qualification_only_pins=(pin,))


def test_node_lock_generation_mode_requires_missing_lock() -> None:
    spec = RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.NODE_NPM,
        package_root="08_Tooling/app",
        runtime_requirement=">=20.19.0",
        dependency_manifest_identity=artifact("08_Tooling/app/package.json"),
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.ABSENT_AUTHORIZED_LOCK_GENERATION,
        approved_source_identity="registry.npmjs.org",
        required_validation_command_ids=("npm-test",),
    )
    assert spec.lock_or_constraints_identity is None
    with pytest.raises(ValueError):
        RequiredEnvironmentSpec(
            ecosystem=DependencyEcosystem.NODE_NPM,
            package_root="08_Tooling/app",
            runtime_requirement=">=20.19.0",
            dependency_manifest_identity=artifact("08_Tooling/app/package.json"),
            lock_or_constraints_identity=artifact("08_Tooling/app/package-lock.json"),
            install_mode=DependencyInstallMode.ABSENT_AUTHORIZED_LOCK_GENERATION,
            approved_source_identity="registry.npmjs.org",
            required_validation_command_ids=("npm-test",),
        )


def test_absolute_paths_and_unbounded_lists_are_rejected() -> None:
    with pytest.raises(ValueError):
        artifact("/tmp/requirements.txt")
    with pytest.raises(ValueError):
        python_spec(required_validation_command_ids=("z", "a"))


def test_evidence_currentness_and_serialization_are_deterministic() -> None:
    spec = python_spec()
    evidence = DependencyReadinessEvidence(
        execution_surface_id="codespaces:abc",
        workspace_identity="pilot-workspace:abc",
        source_sha=HEAD,
        required_environment_id=spec.required_environment_id,
        package_root="repo",
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        runtime_version="3.12.1",
        package_manager_version="24.0",
        declared_dependency_identity=SHA,
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        source_or_registry_identity="pypi.org/simple",
        cache_state=DependencyCacheState.NOT_APPLICABLE,
        preparation_status=DependencyPreparationStatus.READY,
        resolved_dependency_identity="resolved:abc",
        environment_health_evidence_id="environment-health:abc",
        observed_at="2026-08-15T20:00:00Z",
        expires_at="2026-08-15T21:00:00Z",
        reproducibility_level=ReproducibilityLevel.RESOLVED,
        reason_codes=(),
    )
    assert evidence.is_current("2026-08-15T20:30:00Z")
    assert not evidence.is_current("2026-08-15T21:00:00Z")
    assert dependency_readiness_evidence_payload(evidence)["execution_authorized"] is False
    assert required_environment_spec_payload(spec)["required_environment_id"] == spec.required_environment_id
