from __future__ import annotations

import hashlib

import pytest

from scripts.agent_os_execution_checkpoint.invalidation import BindingSnapshot
from scripts.agent_os_execution_checkpoint.resume_planner import plan_resume
from scripts.agent_os_execution_checkpoint.resume_plan_store import (
    AppendResumePlanOutcome,
    ResumePlanNotFound,
    append_resume_plan,
    load_resume_plan,
)
from scripts.agent_os_execution_checkpoint.store import CheckpointStoreIntegrityConflict

SHA40 = "a" * 40
HEX64 = hashlib.sha256(b"x").hexdigest()
REPOSITORY = "Blummer92/agent-os"
ISSUE_NUMBER = 1304
EVALUATED_AT = "2026-08-20T14:00:00Z"


def _bindings(**overrides: object) -> BindingSnapshot:
    fields: dict[str, object] = {
        "source_sha": SHA40,
        "tested_sha": SHA40,
        "dependency_fingerprint": HEX64,
        "environment_fingerprint": HEX64,
        "worktree_fingerprint": HEX64,
        "branch": "agent/1304-recoverable-artifacts",
        "acceptance_criteria_digest": HEX64,
        "governance_contract_digest": HEX64,
        "command_plan_id": f"command-plan:{HEX64}",
        "merge_base_sha": SHA40,
    }
    fields.update(overrides)
    return BindingSnapshot(**fields)


def _plan(execution_id: str = "exe-1"):
    return plan_resume(
        repository=REPOSITORY,
        issue_number=ISSUE_NUMBER,
        execution_id=execution_id,
        evaluated_at=EVALUATED_AT,
        current_bindings=_bindings(),
        stored_checkpoints=(),
    )


def test_append_and_load_round_trip_recomputes_identity(tmp_path) -> None:
    plan = _plan()
    outcome = append_resume_plan(tmp_path, plan)
    assert type(outcome) is AppendResumePlanOutcome
    assert outcome.plan_id == plan.plan_id
    assert outcome.already_present is False

    loaded = load_resume_plan(tmp_path, plan.plan_id)
    assert loaded == plan
    assert loaded.plan_id == plan.plan_id
    assert loaded.repository_implementation_authorized is False
    assert loaded.execution_authorized is False


def test_repeated_append_of_identical_plan_is_idempotent(tmp_path) -> None:
    plan = _plan()
    first = append_resume_plan(tmp_path, plan)
    second = append_resume_plan(tmp_path, plan)
    assert first.already_present is False
    assert second.already_present is True
    assert first.path == second.path


def test_load_missing_plan_fails_closed(tmp_path) -> None:
    missing_id = "agent-os.execution-checkpoint.resume-plan:" + "0" * 64
    with pytest.raises(ResumePlanNotFound):
        load_resume_plan(tmp_path, missing_id)


def test_tampered_persisted_bytes_are_rejected_on_load(tmp_path) -> None:
    plan = _plan()
    outcome = append_resume_plan(tmp_path, plan)
    outcome.path.write_bytes(b'{"tampered": true}')
    with pytest.raises(CheckpointStoreIntegrityConflict):
        load_resume_plan(tmp_path, plan.plan_id)


def test_malformed_plan_id_is_rejected(tmp_path) -> None:
    with pytest.raises(TypeError):
        load_resume_plan(tmp_path, "not-a-canonical-id")


def test_append_rejects_non_exact_type(tmp_path) -> None:
    with pytest.raises(TypeError):
        append_resume_plan(tmp_path, object())


def test_two_plans_from_different_executions_persist_independently(tmp_path) -> None:
    first = _plan("exe-1")
    second = _plan("exe-2")
    append_resume_plan(tmp_path, first)
    append_resume_plan(tmp_path, second)
    assert load_resume_plan(tmp_path, first.plan_id) == first
    assert load_resume_plan(tmp_path, second.plan_id) == second
