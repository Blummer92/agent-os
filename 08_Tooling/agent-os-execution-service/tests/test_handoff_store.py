from __future__ import annotations

import pytest

from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    build_executor_handoff,
    select_executor_route,
)
from agent_os_execution_service.handoff_store import (
    AppendExecutorHandoffOutcome,
    ExecutorHandoffNotFound,
    append_executor_handoff,
    load_executor_handoff,
)
from scripts.agent_os_execution_checkpoint.store import CheckpointStoreIntegrityConflict

BASE = {
    "repository": "Blummer92/agent-os",
    "issue_or_handoff_identity": "issue:1304",
    "requested_operation": "implement-recoverable-artifacts",
    "governed_runner_available": True,
    "external_fallback_available": False,
    "external_fallback_explicitly_permitted": False,
    "created_at": "2026-08-20T14:00:00Z",
    "expires_at": "2026-08-20T15:00:00Z",
    "invalidation_conditions": ("repository-head-changed",),
    "execution_service_request_fingerprint_or_none": "execution-request:" + "1" * 6,
    "operating_mode_decision_id_or_none": "operating-mode:current",
    "executable_lane_selection_id_or_none": "lane-selection:current",
    "environment_profile_id_or_none": "environment-profile:current",
    "environment_health_evidence_id_or_none": "environment-health:current",
    "workflow_runtime_identity_or_none": "workflow-runtime:current",
}


def _runner_decision(**overrides: object):
    payload = dict(BASE)
    payload.update(
        required_capabilities=(ExecutorCapability.CHECKOUT,),
        governed_runner_capabilities=(ExecutorCapability.CHECKOUT,),
    )
    payload.update(overrides)
    return select_executor_route(**payload)


def _handoff(decision_value=None, **overrides: object):
    decision_value = decision_value or _runner_decision()
    payload: dict[str, object] = {
        "source_ref_or_none": "refs/heads/agent/1304-recoverable-artifacts",
        "source_sha_or_none": "a" * 40,
        "allowed_paths": ("08_Tooling/agent-os-execution-service",),
        "forbidden_paths": (".github/workflows",),
        "required_return_evidence": ("exact-head-sha", "test-results"),
        "stop_conditions": ("excluded-surface-entered", "scope-expanded"),
    }
    payload.update(overrides)
    return build_executor_handoff(decision_value, **payload)


def test_append_and_load_round_trip_recomputes_identity(tmp_path) -> None:
    value = _handoff()
    outcome = append_executor_handoff(tmp_path, value)
    assert type(outcome) is AppendExecutorHandoffOutcome
    assert outcome.handoff_id == value.handoff_id
    assert outcome.already_present is False

    loaded = load_executor_handoff(tmp_path, value.handoff_id)
    assert loaded == value
    assert loaded.handoff_id == value.handoff_id
    assert loaded.route_decision_id == value.route_decision_id


def test_repeated_append_of_identical_handoff_is_idempotent(tmp_path) -> None:
    value = _handoff()
    first = append_executor_handoff(tmp_path, value)
    second = append_executor_handoff(tmp_path, value)
    assert first.already_present is False
    assert second.already_present is True
    assert first.path == second.path


def test_load_missing_handoff_fails_closed(tmp_path) -> None:
    missing_id = "executor-handoff:" + "0" * 64
    with pytest.raises(ExecutorHandoffNotFound):
        load_executor_handoff(tmp_path, missing_id)


def test_tampered_persisted_bytes_are_rejected_on_load(tmp_path) -> None:
    value = _handoff()
    outcome = append_executor_handoff(tmp_path, value)
    outcome.path.write_bytes(b'{"tampered": true}')
    with pytest.raises(CheckpointStoreIntegrityConflict):
        load_executor_handoff(tmp_path, value.handoff_id)


def test_malformed_handoff_id_is_rejected(tmp_path) -> None:
    with pytest.raises(TypeError):
        load_executor_handoff(tmp_path, "not-a-canonical-id")


def test_append_rejects_non_exact_type(tmp_path) -> None:
    with pytest.raises(TypeError):
        append_executor_handoff(tmp_path, object())


def test_checkpointed_resume_handoff_round_trips_with_bound_identities(tmp_path) -> None:
    decision_value = _runner_decision(
        required_capabilities=(ExecutorCapability.CHECKPOINTED_RESUME,),
        governed_runner_capabilities=(ExecutorCapability.CHECKPOINTED_RESUME,),
        checkpoint_id_or_none="agent-os.execution-checkpoint:" + "c" * 64,
        resume_plan_id_or_none="agent-os.execution-checkpoint.resume-plan:" + "d" * 64,
    )
    value = _handoff(decision_value)
    append_executor_handoff(tmp_path, value)
    loaded = load_executor_handoff(tmp_path, value.handoff_id)
    assert loaded.checkpoint_id_or_none == value.checkpoint_id_or_none == decision_value.checkpoint_id_or_none
    assert loaded.resume_plan_id_or_none == value.resume_plan_id_or_none == decision_value.resume_plan_id_or_none
