from __future__ import annotations

from pathlib import Path

from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyArtifactIdentity,
    DependencyEcosystem,
    DependencyInstallMode,
    LocalProjectRequirement,
    RequiredEnvironmentSpec,
)
from workflow_scheduler.execution.dependency_preparation import (
    UNDECLARED_LOCAL_PROJECT,
    UNSUPPORTED_SOURCE_INDIRECTION,
    validate_python_requirements_source_forms,
)

SHA = "a" * 64
ROOT_EDITABLE_PROJECTS = (
    "08_Tooling/agent-memory-context-manager",
    "08_Tooling/reusable-capability-registry",
    "08_Tooling/visual-asset-intake",
    "08_Tooling/workflow-scheduler",
    "src",
)


def _root_spec() -> RequiredEnvironmentSpec:
    return RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
        runtime_requirement=">=3.11",
        dependency_manifest_identity=DependencyArtifactIdentity(
            relative_path="requirements-dev.txt", sha256=SHA
        ),
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        local_project_requirements=tuple(
            LocalProjectRequirement(relative_path=path, sha256=SHA, editable=True)
            for path in ROOT_EDITABLE_PROJECTS
        ),
        approved_source_identity="pypi.org/simple",
        required_validation_command_ids=("pytest",),
    )


def test_current_root_manifest_is_structurally_representable() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    text = (repository_root / "requirements-dev.txt").read_text(encoding="utf-8")
    assert validate_python_requirements_source_forms(text, _root_spec()) == ()


def test_editable_extra_binds_to_declared_filesystem_path() -> None:
    assert validate_python_requirements_source_forms(
        "-e ./08_Tooling/reusable-capability-registry[test]\n", _root_spec()
    ) == ()


def test_editable_extra_cannot_authorize_an_undeclared_path() -> None:
    assert validate_python_requirements_source_forms(
        "-e ./08_Tooling/not-declared[test]\n", _root_spec()
    ) == (UNDECLARED_LOCAL_PROJECT,)


def test_malformed_editable_extras_fail_closed() -> None:
    for target in (
        "-e ./08_Tooling/reusable-capability-registry[]\n",
        "-e ./08_Tooling/reusable-capability-registry[test\n",
        "-e ./08_Tooling/reusable-capability-registry[test]]\n",
        "-e ./08_Tooling/reusable-capability-registry[test,,dev]\n",
        "-e ./08_Tooling/reusable-capability-registry[test,test]\n",
    ):
        assert validate_python_requirements_source_forms(target, _root_spec()) == (
            UNSUPPORTED_SOURCE_INDIRECTION,
        )
