"""Focused AOS-AUTO1E execution-packet coordinator tests (#754)."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXECUTION_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for path in (EXECUTION_SERVICE_SRC, SCHEDULER_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.agent_os_candidate_packet.execution_packet_stage import (  # noqa: E402
    ExecutionPacketDisposition,
    prepare_execution_packet,
)
from tests.agent_os_candidate_packet.test_validation_stage import (  # noqa: E402
    _CANDIDATE_SHA,
    _approved,
    _inputs,
)


def test_one_call_builds_request_command_plan_and_runtime_configuration(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)

    first = prepare_execution_packet(approved, inputs)
    second = prepare_execution_packet(approved, inputs)

    assert first.disposition is ExecutionPacketDisposition.NEEDS_DECISION
    assert first.packet_complete is True
    assert first.runtime_capability_available is True
    assert first.execution_authorization_present is False
    assert first.request.expected_sha == _CANDIDATE_SHA
    assert first.request.base_sha == approved.projection.evaluated_repository_sha
    assert first.validation_stage.tested_sha == approved.projection.tested_repository_sha
    assert first.command_plan.entries[0].argv == (
        "python",
        "-m",
        "pytest",
        "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py",
    )
    assert first.runtime_configuration.execution_mode == "validation-only"
    assert first.runtime_configuration.executor_argv is None
    assert first.runtime_configuration.required_test_commands[0].argv == first.command_plan.entries[0].argv
    assert first.request_fingerprint == second.request_fingerprint
    assert first.command_plan_id == second.command_plan_id
    assert first.runtime_configuration_fingerprint == second.runtime_configuration_fingerprint
    assert first.execution_authorized is False
    assert first.merge_authorized is False
    assert first.side_effects_performed is False


def test_expected_path_drift_changes_packet_identities(tmp_path) -> None:
    approved, repository_evidence = _approved()
    first_inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    first = prepare_execution_packet(approved, first_inputs)

    second_inputs = replace(first_inputs, expected_changed_paths=())
    second = prepare_execution_packet(approved, second_inputs)

    assert first.packet_complete is True
    assert second.packet_complete is True
    assert first.validation_stage.subject_id != second.validation_stage.subject_id
    assert first.validation_stage.validation_plan_id != second.validation_stage.validation_plan_id
    assert first.request_fingerprint != second.request_fingerprint
    assert first.command_plan_id != second.command_plan_id
    assert first.runtime_configuration_fingerprint != second.runtime_configuration_fingerprint


def test_execution_authorization_presence_changes_disposition_not_authority(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(
        tmp_path,
        approved.projection,
        repository_evidence,
        execution_authorization_present=True,
    )

    result = prepare_execution_packet(approved, inputs)

    assert result.disposition is ExecutionPacketDisposition.GO
    assert result.packet_complete is True
    assert result.execution_authorization_present is True
    assert result.execution_authorized is False
    assert result.automatic_retry is False
    assert result.side_effects_performed is False


def test_runtime_capability_unavailable_keeps_non_runtime_objects_and_blocks(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(
        tmp_path,
        approved.projection,
        repository_evidence,
        runtime_capability_available=False,
    )

    result = prepare_execution_packet(approved, inputs)

    assert result.disposition is ExecutionPacketDisposition.BLOCKED
    assert result.packet_complete is False
    assert result.request is not None
    assert result.command_plan is not None
    assert result.runtime_configuration is None
    assert result.reason_codes == ("runtime-capability-unavailable",)


def test_expired_request_fails_before_runtime_configuration(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(
        tmp_path,
        approved.projection,
        repository_evidence,
        evaluated_at="2026-08-11T13:00:00Z",
    )

    result = prepare_execution_packet(approved, inputs)

    assert result.disposition is ExecutionPacketDisposition.BLOCKED
    assert result.packet_complete is False
    assert result.runtime_configuration is None
    assert result.reason_codes == ("execution-request-or-command-plan-invalid",)


def test_candidate_sha_drift_changes_request_and_runtime_fingerprints(tmp_path) -> None:
    approved, repository_evidence = _approved()
    first_inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    first = prepare_execution_packet(approved, first_inputs)

    other_root = tmp_path / "second"
    other_root.mkdir()
    other_worktrees = tmp_path / "second-worktrees"
    other_worktrees.mkdir()
    second_inputs = replace(
        first_inputs,
        candidate_sha="e" * 40,
        repository_root=str(other_root.resolve()),
        workspace_parent=str(other_worktrees.resolve()),
    )
    second = prepare_execution_packet(approved, second_inputs)

    assert first.packet_complete is True
    assert second.packet_complete is True
    assert first.request_fingerprint != second.request_fingerprint
    assert first.runtime_configuration_fingerprint != second.runtime_configuration_fingerprint
    assert first.command_plan_id != second.command_plan_id