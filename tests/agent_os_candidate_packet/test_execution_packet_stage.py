"""Focused AOS-AUTO1E execution-packet coordinator tests (#754)."""

from __future__ import annotations

import inspect
import sys
from dataclasses import replace
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXECUTION_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for path in (EXECUTION_SERVICE_SRC, SCHEDULER_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pytest  # noqa: E402

import scripts.agent_os_candidate_packet.execution_packet_stage as execution_packet_stage_module  # noqa: E402
from scripts.agent_os_candidate_packet.execution_packet_stage import (  # noqa: E402
    ExecutionPacketDisposition,
    ExecutionPacketStageResult,
    execution_packet_stage_result_from_dict,
    execution_packet_stage_result_to_dict,
    prepare_execution_packet,
)
from scripts.agent_os_candidate_packet.stage_models import STAGE_SCHEMA_VERSION  # noqa: E402
from scripts.agent_os_issue_acceptance.approved_execution_projection import (  # noqa: E402
    ApprovedExecutionProjectionResult,
)
from tests.agent_os_candidate_packet.test_proposal_stage import _observation  # noqa: E402
from tests.agent_os_candidate_packet.test_validation_stage import (  # noqa: E402
    _CANDIDATE_SHA,
    _approved,
    _inputs,
)
from workflow_scheduler.execution.runtime_configuration import (  # noqa: E402
    ConcreteRuntimeConfiguration,
    runtime_configuration_payload,
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
    assert first.runtime_configuration.lease_directory is None
    assert first.runtime_configuration.delegated_parent_cgroup is None
    assert first.runtime_configuration.required_test_commands[0].argv == first.command_plan.entries[0].argv
    assert first.request_fingerprint == second.request_fingerprint
    assert first.command_plan_id == second.command_plan_id
    assert first.runtime_configuration_fingerprint == second.runtime_configuration_fingerprint
    assert first.execution_authorized is False
    assert first.merge_authorized is False
    assert first.side_effects_performed is False


# --------------------------------------------------------------------------
# #1153: bind_candidate is the canonical runtime-construction path.
# --------------------------------------------------------------------------


def test_single_issue_pilot_input_is_no_longer_imported_or_constructed() -> None:
    """The stage must not import or fabricate a SingleIssuePilotInput."""
    assert not hasattr(execution_packet_stage_module, "SingleIssuePilotInput")
    source = inspect.getsource(execution_packet_stage_module)
    assert "SingleIssuePilotInput" not in source
    assert "runtime.verify(" not in source


def test_no_execution_capable_surface_is_reachable_from_this_module() -> None:
    """No Scheduler/process/provider/network/worktree/lease surface is reachable."""
    source = inspect.getsource(execution_packet_stage_module)
    for forbidden_token in (
        "SingleIssuePilotInput",
        "runtime.verify(",
        "subprocess",
        "Popen",
        "HostLocalLeaseAdapter",
        "PosixProcessExecutorAdapter",
    ):
        assert forbidden_token not in source


def test_bind_candidate_is_the_runtime_construction_path(tmp_path, monkeypatch) -> None:
    """``ConcreteRuntimeConfiguration.bind`` must never be used; ``bind_candidate`` must be."""
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)

    def _forbidden_bind(*args, **kwargs):
        raise AssertionError("ConcreteRuntimeConfiguration.bind must not be used by this stage")

    monkeypatch.setattr(ConcreteRuntimeConfiguration, "bind", _forbidden_bind)

    calls: list[int] = []
    original_bind_candidate = ConcreteRuntimeConfiguration.__dict__["bind_candidate"].__func__

    def _spy_bind_candidate(cls, *args, **kwargs):
        calls.append(1)
        return original_bind_candidate(cls, *args, **kwargs)

    monkeypatch.setattr(
        ConcreteRuntimeConfiguration, "bind_candidate", classmethod(_spy_bind_candidate)
    )

    result = prepare_execution_packet(approved, inputs)

    assert result.packet_complete is True
    assert calls == [1]


def test_runtime_configuration_payload_matches_bind_candidate_identities(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)

    result = prepare_execution_packet(approved, inputs)

    payload = runtime_configuration_payload(result.runtime_configuration)
    assert payload["execution_mode"] == "validation-only"
    assert payload["repository"] == result.validation_stage.repository
    assert payload["issue_number"] == inputs.issue_number
    assert payload["invocation_id"] == inputs.invocation_id
    assert payload["validation_bundle_id"] == inputs.validation_bundle_id
    assert payload["advisory_result_id"] == inputs.advisory_result_id
    assert payload["advisory_render_id"] == inputs.advisory_render_id
    assert payload["executor_argv"] is None
    assert payload["lease_directory"] is None
    assert payload["delegated_parent_cgroup"] is None


def test_evidence_ids_are_exact_and_fingerprint_sensitive(tmp_path) -> None:
    """validation_bundle_id, advisory_result_id, advisory_render_id are exact and drift the fingerprint."""
    approved, repository_evidence = _approved()
    base_inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    base = prepare_execution_packet(approved, base_inputs)

    for field_name in ("validation_bundle_id", "advisory_result_id", "advisory_render_id"):
        changed_inputs = replace(
            base_inputs, **{field_name: getattr(base_inputs, field_name) + "-changed"}
        )
        changed = prepare_execution_packet(approved, changed_inputs)

        assert changed.packet_complete is True
        assert getattr(changed.runtime_configuration, field_name) == getattr(
            changed_inputs, field_name
        )
        assert changed.runtime_configuration_fingerprint != base.runtime_configuration_fingerprint


def test_missing_repository_root_directory_fails_closed(tmp_path) -> None:
    """Path evidence that does not resolve to a real directory fails closed."""
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    missing_root_inputs = replace(inputs, repository_root=str(tmp_path / "does-not-exist"))

    result = prepare_execution_packet(approved, missing_root_inputs)

    assert result.disposition is ExecutionPacketDisposition.BLOCKED
    assert result.packet_complete is False
    assert result.runtime_configuration is None
    assert result.reason_codes == ("runtime-configuration-invalid",)


def test_conflicting_allowed_and_forbidden_paths_fail_closed(tmp_path) -> None:
    """Overlapping allowed/forbidden path evidence fails closed before runtime binding."""
    approved, repository_evidence = _approved()
    conflicting_projection = replace(
        approved.projection,
        forbidden_paths=approved.projection.allowed_files,
        projection_id="",
    )
    conflicting_projection_result = ApprovedExecutionProjectionResult(
        "complete", conflicting_projection, (), ()
    )
    conflicting_approved = replace(
        approved,
        projection_result=conflicting_projection_result,
        projection=conflicting_projection,
    )
    inputs = _inputs(tmp_path, conflicting_projection, repository_evidence)

    result = prepare_execution_packet(conflicting_approved, inputs)

    assert result.disposition is ExecutionPacketDisposition.BLOCKED
    assert result.packet_complete is False
    assert result.runtime_configuration is None


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


# --------------------------------------------------------------------------
# ExecutionPacketStageResult transport (#1054).
# --------------------------------------------------------------------------


def test_complete_packet_round_trips_to_an_identical_payload(tmp_path) -> None:
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

    payload = execution_packet_stage_result_to_dict(result)
    rebuilt = execution_packet_stage_result_from_dict(payload)

    assert type(rebuilt) is ExecutionPacketStageResult
    assert rebuilt == result
    assert execution_packet_stage_result_to_dict(rebuilt) == payload
    assert payload["schema_version"] == STAGE_SCHEMA_VERSION
    assert payload["execution_authorized"] is False
    assert payload["merge_authorized"] is False
    assert payload["automatic_retry"] is False
    assert payload["side_effects_performed"] is False


def test_incomplete_packet_round_trips_with_no_runtime_configuration(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(
        tmp_path,
        approved.projection,
        repository_evidence,
        runtime_capability_available=False,
    )
    result = prepare_execution_packet(approved, inputs)
    assert result.packet_complete is False
    assert result.request is not None
    assert result.command_plan is not None

    payload = execution_packet_stage_result_to_dict(result)
    rebuilt = execution_packet_stage_result_from_dict(payload)

    assert rebuilt == result
    assert payload["request"] is not None
    assert payload["command_plan"] is not None
    assert payload["runtime_configuration"] is None


def test_unsupported_schema_version_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = execution_packet_stage_result_to_dict(prepare_execution_packet(approved, inputs))
    bad = {**payload, "schema_version": "9.9"}

    with pytest.raises(ValueError, match="unsupported stage schema_version"):
        execution_packet_stage_result_from_dict(bad)


def test_unknown_field_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = execution_packet_stage_result_to_dict(prepare_execution_packet(approved, inputs))
    bad = {**payload, "surprise": 1}

    with pytest.raises(ValueError, match="unsupported field"):
        execution_packet_stage_result_from_dict(bad)


def test_missing_field_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = execution_packet_stage_result_to_dict(prepare_execution_packet(approved, inputs))
    bad = dict(payload)
    del bad["command_plan"]

    with pytest.raises(ValueError, match="missing field"):
        execution_packet_stage_result_from_dict(bad)


def test_malformed_disposition_enum_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = execution_packet_stage_result_to_dict(prepare_execution_packet(approved, inputs))
    bad = {**payload, "disposition": "NOT-A-REAL-DISPOSITION"}

    with pytest.raises(ValueError):
        execution_packet_stage_result_from_dict(bad)


def test_wrong_nested_request_type_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = execution_packet_stage_result_to_dict(prepare_execution_packet(approved, inputs))
    bad = {**payload, "request": "not-an-object"}

    with pytest.raises((ValueError, TypeError)):
        execution_packet_stage_result_from_dict(bad)


def test_packet_complete_boolean_misuse_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = execution_packet_stage_result_to_dict(prepare_execution_packet(approved, inputs))
    bad = {**payload, "packet_complete": 1}

    with pytest.raises(ValueError, match="exact boolean"):
        execution_packet_stage_result_from_dict(bad)


def test_request_fingerprint_drift_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = execution_packet_stage_result_to_dict(prepare_execution_packet(approved, inputs))
    bad = {**payload, "request_fingerprint": "0" * 64}

    with pytest.raises(ValueError, match="request_fingerprint does not match"):
        execution_packet_stage_result_from_dict(bad)


def test_command_plan_id_drift_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = execution_packet_stage_result_to_dict(prepare_execution_packet(approved, inputs))
    bad = {**payload, "command_plan_id": "command-plan:" + "0" * 64}

    with pytest.raises(ValueError, match="command_plan_id does not match"):
        execution_packet_stage_result_from_dict(bad)


def test_runtime_configuration_fingerprint_drift_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(
        tmp_path,
        approved.projection,
        repository_evidence,
        execution_authorization_present=True,
    )
    payload = execution_packet_stage_result_to_dict(prepare_execution_packet(approved, inputs))
    bad = {**payload, "runtime_configuration_fingerprint": "0" * 64}

    with pytest.raises(ValueError):
        execution_packet_stage_result_from_dict(bad)


def test_command_plan_request_binding_drift_is_rejected(tmp_path) -> None:
    """A command plan carrying a foreign request fingerprint must fail closed."""
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    result = prepare_execution_packet(approved, inputs)
    payload = execution_packet_stage_result_to_dict(result)

    other_inputs = _inputs(tmp_path, approved.projection, repository_evidence, request_revision=2)
    other = prepare_execution_packet(approved, other_inputs)
    other_payload = execution_packet_stage_result_to_dict(other)

    bad = {**payload, "command_plan": other_payload["command_plan"]}

    with pytest.raises(ValueError):
        execution_packet_stage_result_from_dict(bad)


def test_execution_authorized_set_true_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = execution_packet_stage_result_to_dict(prepare_execution_packet(approved, inputs))
    bad = {**payload, "execution_authorized": True}

    with pytest.raises(ValueError, match="execution_authorized must be false"):
        execution_packet_stage_result_from_dict(bad)


def test_merge_authorized_set_true_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = execution_packet_stage_result_to_dict(prepare_execution_packet(approved, inputs))
    bad = {**payload, "merge_authorized": True}

    with pytest.raises(ValueError, match="merge_authorized must be false"):
        execution_packet_stage_result_from_dict(bad)


def test_side_effects_performed_set_true_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = execution_packet_stage_result_to_dict(prepare_execution_packet(approved, inputs))
    bad = {**payload, "side_effects_performed": True}

    with pytest.raises(ValueError, match="side_effects_performed must be false"):
        execution_packet_stage_result_from_dict(bad)


def test_a_foreign_object_is_rejected_at_serialization() -> None:
    with pytest.raises(TypeError):
        execution_packet_stage_result_to_dict(_observation())


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