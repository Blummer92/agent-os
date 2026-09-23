"""Offline regression tests for the candidate-bound runtime configuration (#1034)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
TESTS_DIR = Path(__file__).resolve().parent
for path in (REPOSITORY_ROOT, SCHEDULER_SRC, TESTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import test_single_issue_pilot as tsp  # noqa: E402

from workflow_scheduler.execution.frozen_test_validation_adapter import (  # noqa: E402
    FrozenTestCommand,
)
from workflow_scheduler.execution.runtime_configuration import (  # noqa: E402
    ConcreteRuntimeConfiguration,
    ConcreteRuntimeConfigurationError,
    reconstruct_concrete_runtime_configuration,
    runtime_configuration_payload,
)
from workflow_scheduler.execution.single_issue_pilot import (  # noqa: E402
    VALIDATION_ONLY_EXECUTION_MODE,
)


def _commands() -> tuple[FrozenTestCommand, ...]:
    return tuple(
        FrozenTestCommand(test_id=test_id, argv=(sys.executable, "-c", "pass"))
        for test_id in tsp.REQUIRED_TESTS
    )


def _candidate_kwargs(tmp_path: Path) -> dict[str, object]:
    pilot = tsp._pilot_input(execution_mode=VALIDATION_ONLY_EXECUTION_MODE)
    root = tmp_path / "repository"
    parent = tmp_path / "worktrees"
    root.mkdir()
    parent.mkdir()
    return {
        "repository": pilot.repository,
        "issue_number": pilot.issue_numbers[0],
        "invocation_id": pilot.invocation_id,
        "workspace_request_id": pilot.workspace_request_id,
        "base_branch": pilot.base_branch,
        "base_sha": pilot.base_sha,
        "source_head_sha": pilot.source_head_sha,
        "tested_sha": pilot.tested_sha,
        "branch": pilot.branch,
        "projection_id": pilot.expected_projection_id,
        "approval_id": pilot.expected_approval_id,
        "validation_plan_id": pilot.expected_plan_id,
        "validation_bundle_id": pilot.expected_bundle_id,
        "advisory_result_id": pilot.expected_advisory_result_id,
        "advisory_render_id": pilot.expected_advisory_render_id,
        "repository_identity": tsp._identity(),
        "repository_root": str(root),
        "workspace_parent": str(parent),
        "required_test_commands": _commands(),
        "allowed_files": tuple(pilot.allowed_files),
        "forbidden_paths": tuple(pilot.forbidden_paths),
        "executor_timeout_seconds": 1.0,
        "executor_grace_period_seconds": 0.05,
        "validation_per_command_timeout_seconds": 1.0,
        "validation_total_timeout_seconds": 5.0,
    }


def test_candidate_binding_is_validation_only_deterministic_and_reconstructable(
    tmp_path: Path,
) -> None:
    kwargs = _candidate_kwargs(tmp_path)
    first = ConcreteRuntimeConfiguration.bind_candidate(**kwargs)
    second = ConcreteRuntimeConfiguration.bind_candidate(**kwargs)

    assert first == second
    assert first.execution_mode == VALIDATION_ONLY_EXECUTION_MODE
    assert first.executor_argv is None
    assert first.configuration_fingerprint == second.configuration_fingerprint

    payload = runtime_configuration_payload(first)
    reconstructed = reconstruct_concrete_runtime_configuration(
        copy.deepcopy(payload),
        configuration_fingerprint=first.configuration_fingerprint,
    )
    assert reconstructed == first
    assert runtime_configuration_payload(reconstructed) == payload


def test_candidate_binding_preserves_legacy_fingerprint_domain_for_equivalent_input(
    tmp_path: Path,
) -> None:
    kwargs = _candidate_kwargs(tmp_path)
    candidate = ConcreteRuntimeConfiguration.bind_candidate(**kwargs)
    pilot = tsp._pilot_input(execution_mode=VALIDATION_ONLY_EXECUTION_MODE)
    legacy = ConcreteRuntimeConfiguration.bind(
        pilot,
        repository_identity=tsp._identity(),
        repository_root=kwargs["repository_root"],
        workspace_parent=kwargs["workspace_parent"],
        required_test_commands=_commands(),
        execution_mode=VALIDATION_ONLY_EXECUTION_MODE,
        executor_timeout_seconds=1.0,
        executor_grace_period_seconds=0.05,
        validation_per_command_timeout_seconds=1.0,
        validation_total_timeout_seconds=5.0,
    )

    assert runtime_configuration_payload(candidate) == runtime_configuration_payload(legacy)
    assert candidate.configuration_fingerprint == legacy.configuration_fingerprint


@pytest.mark.parametrize(
    "field",
    ("validation_bundle_id", "advisory_result_id", "advisory_render_id"),
)
def test_candidate_evidence_reference_drift_changes_fingerprint(
    tmp_path: Path, field: str
) -> None:
    kwargs = _candidate_kwargs(tmp_path)
    original = ConcreteRuntimeConfiguration.bind_candidate(**kwargs)
    drifted = dict(kwargs)
    drifted[field] = str(drifted[field]) + "-drifted"
    changed = ConcreteRuntimeConfiguration.bind_candidate(**drifted)

    assert changed.configuration_fingerprint != original.configuration_fingerprint


def test_candidate_binding_rejects_allowed_forbidden_scope_conflict(tmp_path: Path) -> None:
    kwargs = _candidate_kwargs(tmp_path)
    kwargs["forbidden_paths"] = tuple(kwargs["allowed_files"])

    with pytest.raises(ConcreteRuntimeConfigurationError, match="paths conflict"):
        ConcreteRuntimeConfiguration.bind_candidate(**kwargs)


def test_candidate_binding_rejects_duplicate_required_test_ids(tmp_path: Path) -> None:
    kwargs = _candidate_kwargs(tmp_path)
    command = _commands()[0]
    kwargs["required_test_commands"] = (command, command)

    with pytest.raises(ConcreteRuntimeConfigurationError, match="required test identities"):
        ConcreteRuntimeConfiguration.bind_candidate(**kwargs)


def test_candidate_binding_rejects_invalid_bounds_and_environment(tmp_path: Path) -> None:
    kwargs = _candidate_kwargs(tmp_path)
    invalid_timeout = dict(kwargs, validation_total_timeout_seconds=0)
    with pytest.raises(ConcreteRuntimeConfigurationError):
        ConcreteRuntimeConfiguration.bind_candidate(**invalid_timeout)

    invalid_environment = dict(kwargs, environment_policy="ambient-environment")
    with pytest.raises(ConcreteRuntimeConfigurationError, match="environment authority"):
        ConcreteRuntimeConfiguration.bind_candidate(**invalid_environment)
