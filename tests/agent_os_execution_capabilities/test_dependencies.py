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
    LocalProjectRequirement,
    dependency_readiness_evidence_payload,
    reconstruct_required_environment_spec,
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


# --- AOS-GCE2F (#1320) canonical spec reconstruction --------------------------


def test_reconstruction_round_trips_the_exact_canonical_spec() -> None:
    spec = python_spec(
        lock_or_constraints_identity=artifact("constraints.txt", "c" * 64),
        local_project_requirements=(
            LocalProjectRequirement(
                relative_path="08_Tooling/workflow-scheduler",
                sha256="d" * 64,
                editable=True,
            ),
        ),
        required_validation_command_ids=("pytest", "structural"),
    )

    rebuilt = reconstruct_required_environment_spec(
        required_environment_spec_payload(spec)
    )

    assert type(rebuilt) is RequiredEnvironmentSpec
    assert rebuilt == spec
    assert rebuilt.required_environment_id == spec.required_environment_id


def test_reconstruction_preserves_qualification_only_pins() -> None:
    spec = python_spec(
        install_mode=DependencyInstallMode.QUALIFICATION_ONLY,
        qualification_only_pins=(
            QualificationOnlyDependencyPin(package="hypothesis", version="6.165.9"),
        ),
    )

    assert reconstruct_required_environment_spec(
        required_environment_spec_payload(spec)
    ) == spec


def test_reconstruction_identity_changes_when_canonical_inputs_change() -> None:
    baseline = python_spec()
    changed = python_spec(dependency_manifest_identity=artifact("requirements-dev.txt", "e" * 64))

    assert changed.required_environment_id != baseline.required_environment_id
    assert (
        reconstruct_required_environment_spec(
            required_environment_spec_payload(changed)
        ).required_environment_id
        == changed.required_environment_id
    )


def test_reconstruction_rejects_a_content_mismatched_identity() -> None:
    payload = required_environment_spec_payload(python_spec())
    payload["runtime_requirement"] = ">=3.12"

    with pytest.raises(ValueError, match="required_environment_id"):
        reconstruct_required_environment_spec(payload)


def test_reconstruction_requires_an_asserted_identity() -> None:
    payload = required_environment_spec_payload(python_spec(), include_id=False)
    payload["required_environment_id"] = ""

    with pytest.raises(ValueError, match="required_environment_id"):
        reconstruct_required_environment_spec(payload)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.pop("approved_source_identity"),
        lambda payload: payload.__setitem__("unexpected", True),
        lambda payload: payload.__setitem__("local_project_requirements", {}),
        lambda payload: payload.__setitem__("qualification_only_pins", {}),
        lambda payload: payload.__setitem__("required_validation_command_ids", "pytest"),
        lambda payload: payload.__setitem__("ecosystem", "rust-cargo"),
        lambda payload: payload.__setitem__("install_mode", "guess"),
        lambda payload: payload.__setitem__("dependency_manifest_identity", {"sha256": SHA}),
        lambda payload: payload.__setitem__(
            "local_project_requirements", [{"relative_path": "x", "sha256": SHA}]
        ),
        lambda payload: payload.__setitem__("qualification_only_pins", [{"package": "x"}]),
    ),
)
def test_reconstruction_fails_closed_on_malformed_payloads(mutate) -> None:
    payload = required_environment_spec_payload(python_spec())
    mutate(payload)

    with pytest.raises((TypeError, ValueError)):
        reconstruct_required_environment_spec(payload)


def test_reconstruction_rejects_non_object_payloads() -> None:
    for payload in (None, [], "required-environment:x", 7):
        with pytest.raises((TypeError, ValueError)):
            reconstruct_required_environment_spec(payload)


def test_reconstructed_spec_carries_no_runtime_readiness_fields() -> None:
    spec = reconstruct_required_environment_spec(
        required_environment_spec_payload(python_spec())
    )

    for name in (
        "preparation_status",
        "cache_state",
        "resolved_dependency_identity",
        "reproducibility_level",
        "observed_at",
        "expires_at",
        "dependency_readiness_evidence_id",
    ):
        assert not hasattr(spec, name)
