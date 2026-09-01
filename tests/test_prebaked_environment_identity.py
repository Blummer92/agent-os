from dataclasses import replace

from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyArtifactIdentity,
    DependencyEcosystem,
    DependencyInstallMode,
    RequiredEnvironmentSpec,
)
from scripts.agent_os_prebaked_environment import (
    StableDependencyInput,
    admit_prebaked_environment,
    build_prebaked_environment_identity,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64


def spec(*, manifest=A, runtime="python-3.11") -> RequiredEnvironmentSpec:
    return RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
        runtime_requirement=runtime,
        dependency_manifest_identity=DependencyArtifactIdentity(
            relative_path="requirements-dev.txt", sha256=manifest
        ),
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity="pypi:approved",
        required_validation_command_ids=("aggregate-validation",),
    )


def image(current=None, *, build=A, manager="pip-25.2", repository="Blummer92/agent-os"):
    current = current or spec()
    return build_prebaked_environment_identity(
        spec=current,
        repository_identity=repository,
        runtime_version="python-3.11.13",
        package_manager_version=manager,
        build_definition_sha256=build,
        stable_dependency_inputs=(
            StableDependencyInput(relative_path="requirements-dev.txt", sha256=A),
            StableDependencyInput(
                relative_path="08_Tooling/workflow-scheduler/requirements.txt", sha256=B
            ),
        ),
    )


def test_equivalent_inputs_produce_stable_identity():
    assert image().environment_id == image().environment_id


def test_manifest_drift_changes_required_environment_and_image_identity():
    assert image(spec()).environment_id != image(spec(manifest=C)).environment_id


def test_runtime_requirement_drift_changes_identity():
    assert image(spec()).environment_id != image(spec(runtime="python-3.12")).environment_id


def test_package_manager_and_build_definition_drift_change_identity():
    base = image()
    assert base.environment_id != image(manager="pip-25.3").environment_id
    assert base.environment_id != image(build=C).environment_id


def test_matching_image_is_admissible():
    current = spec()
    assert admit_prebaked_environment(
        spec=current, selected=image(current), expected_repository_identity="Blummer92/agent-os"
    )


def test_stale_or_foreign_image_fails_closed():
    current = spec()
    stale = image(spec(manifest=C))
    foreign = image(current, repository="other/repo")
    assert not admit_prebaked_environment(
        spec=current, selected=stale, expected_repository_identity="Blummer92/agent-os"
    )
    assert not admit_prebaked_environment(
        spec=current, selected=foreign, expected_repository_identity="Blummer92/agent-os"
    )


def test_task_local_requirements_are_not_an_image_identity_input():
    fields = set(image().__dataclass_fields__)
    assert "local_project_requirements" not in fields
    assert "credentials" not in fields
    assert "authorization" not in fields
    assert "source_code" not in fields
    assert "checkpoint" not in fields
    assert "lease" not in fields
