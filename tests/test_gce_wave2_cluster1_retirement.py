"""Wave 2 Cluster 1: retired first-run paths remain absent, Codespaces survives.

This is a repository-local scope guard. External/dynamic callers are an
explicit evidence limitation, not proof of safety or execution authorization.
"""
from __future__ import annotations

from importlib.machinery import PathFinder
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

RETIRED_PATHS = (
    "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/first_run_dev_validation_gce.py",
    "08_Tooling/workflow-scheduler/tests/test_first_run_dev_validation_gce.py",
    "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/first_run_invalidation_projection.py",
    "08_Tooling/agent-os-execution-service/tests/test_first_run_invalidation_projection.py",
    "08_Tooling/agent-os-execution-service/docs/FIRST_RUN_INVALIDATION_PROJECTION.md",
)
PRESERVED_PATHS = (
    "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/first_run_validation_observation.py",
    "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/dev_validation_codespaces.py",
    "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/gce_gcloud_adapter.py",
    "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/ppux_projection_gce.py",
    "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/authorized_validation.py",
    "08_Tooling/workflow-scheduler/tests/test_first_run_validation_profile_match.py",
    "08_Tooling/workflow-scheduler/tests/test_first_run_validation_observation.py",
)


@pytest.mark.parametrize("path", RETIRED_PATHS)
def test_orphaned_first_run_paths_absent(path: str) -> None:
    assert not (ROOT / path).exists(), path


@pytest.mark.parametrize("path", PRESERVED_PATHS)
def test_required_existing_paths_preserved(path: str) -> None:
    assert (ROOT / path).is_file(), path


@pytest.mark.parametrize(
    "name,parent",
    (
        (
            "workflow_scheduler.governance.first_run_dev_validation_gce",
            "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance",
        ),
        (
            "agent_os_execution_service.first_run_invalidation_projection",
            "08_Tooling/agent-os-execution-service/src/agent_os_execution_service",
        ),
    ),
)
def test_retired_module_absent_from_repo_tree(name: str, parent: str) -> None:
    assert PathFinder.find_spec(name, [str(ROOT / parent)]) is None


def test_codespaces_projection_and_profile_matcher_survive() -> None:
    from workflow_scheduler.governance.first_run_validation_observation import (
        CODESPACES_RUNNER_ID,
        FirstRunValidationObservationError,
        observed_command_from_codespaces_evidence,
        resolve_fixed_first_run_validation_id,
    )

    assert CODESPACES_RUNNER_ID == "agent-os-codespaces-dev-validation-v1"
    assert callable(observed_command_from_codespaces_evidence)
    assert callable(resolve_fixed_first_run_validation_id)
    assert issubclass(FirstRunValidationObservationError, ValueError)


def test_gce_first_run_projector_is_not_exported() -> None:
    from workflow_scheduler.governance import first_run_validation_observation as module

    assert not hasattr(module, "FIXED_GCE_RUNNER_ID")
    assert not hasattr(module, "observed_command_from_fixed_gce_evidence")
    assert "FIXED_GCE_RUNNER_ID" not in module.__all__
    assert "observed_command_from_fixed_gce_evidence" not in module.__all__
