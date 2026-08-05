"""Focused tests for scripts/agent_os_execution_checkpoint/store.py.

Every test runs against an isolated tmp_path root. No git subprocess,
network, or GitHub access is used anywhere in this file or in store.py.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.agent_os_execution_checkpoint import store
from scripts.agent_os_execution_checkpoint.models import (
    CheckpointStage,
    ExecutionCheckpoint,
    InvalidationState,
    LifecycleState,
    StageStatus,
    WorktreeRole,
)
from scripts.agent_os_execution_checkpoint.mutation_intent import compute_mutation_intent_id
from scripts.agent_os_issue_acceptance.issue_operational_state import LifecycleStage

SHA40 = "7d01ad36d7f9c9cba41c9fee62a562b7689c2fbe"
HEX64 = hashlib.sha256(b"x").hexdigest()
COMMAND_PLAN_ID = f"command-plan:{HEX64}"


def make_checkpoint(**overrides: object) -> ExecutionCheckpoint:
    fields: dict[str, object] = {
        "schema": "agent-os.execution-checkpoint",
        "schema_version": "1.0",
        "repository": "Blummer92/agent-os",
        "issue_number": 895,
        "invocation_id": "inv-1",
        "execution_id": "exe-1",
        "branch": "agent/895-execution-checkpoint",
        "worktree_fingerprint": HEX64,
        "worktree_role": WorktreeRole.PRIMARY,
        "environment_fingerprint": HEX64,
        "source_sha": SHA40,
        "tested_sha": SHA40,
        "merge_base_sha": SHA40,
        "dependency_fingerprint": HEX64,
        "command_plan_id": COMMAND_PLAN_ID,
        "acceptance_criteria_digest": HEX64,
        "governance_contract_digest": HEX64,
        "lifecycle_stage": LifecycleStage.PLANNING,
        "checkpoint_stage": CheckpointStage.PREFLIGHT_COMPLETE,
        "stage_status": StageStatus.PASSED,
        "evidence_hashes": (),
        "invalidation_state": InvalidationState.CURRENT,
        "lifecycle_state": LifecycleState.ACTIVE,
        "recorded_at": "2026-08-05T12:00:00Z",
        "actor_id": "github-service-agent",
    }
    fields.update(overrides)
    return ExecutionCheckpoint(**fields)


def make_mutating(
    parent_id: str | None = None,
    *,
    stage: CheckpointStage = CheckpointStage.IMPLEMENTATION_COMPLETE,
    lifecycle: LifecycleStage = LifecycleStage.IMPLEMENTATION,
    execution_id: str = "exe-1",
    invocation_id: str = "inv-1",
) -> ExecutionCheckpoint:
    intent = compute_mutation_intent_id(
        repository="Blummer92/agent-os",
        issue_number=895,
        execution_id=execution_id,
        checkpoint_stage=stage.value,
        target_ref="agent/895-execution-checkpoint",
        content_digest=HEX64,
        parent_checkpoint_id=parent_id,
    )
    return make_checkpoint(
        checkpoint_stage=stage,
        lifecycle_stage=lifecycle,
        execution_id=execution_id,
        invocation_id=invocation_id,
        mutation_intent_id=intent,
        pre_read_digest=HEX64,
        post_write_digest=HEX64,
        parent_checkpoint_id=parent_id,
    )


# --- append / idempotent duplicate ------------------------------------------


def test_append_then_load_round_trips(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    checkpoint = make_checkpoint()
    outcome = store.append_checkpoint(root, checkpoint)
    assert outcome.already_present is False
    result = store.load_checkpoints(root, 895)
    assert len(result.valid) == 1
    assert result.valid[0].checkpoint.checkpoint_id == checkpoint.checkpoint_id
    assert result.quarantined == ()


def test_appending_identical_checkpoint_twice_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    checkpoint = make_checkpoint()
    store.append_checkpoint(root, checkpoint)
    outcome2 = store.append_checkpoint(root, checkpoint)
    assert outcome2.already_present is True
    result = store.load_checkpoints(root, 895)
    assert len(result.valid) == 1


def test_append_rejects_non_execution_checkpoint(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        store.append_checkpoint(tmp_path, {"not": "a checkpoint"})


# --- HEAD pointer -------------------------------------------------------


def test_head_reflects_last_append_and_is_reconstructable_hint(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    cp1 = make_checkpoint()
    store.append_checkpoint(root, cp1)
    assert store.read_head(root, 895) == cp1.checkpoint_id

    cp2 = make_mutating(parent_id=cp1.checkpoint_id)
    store.append_checkpoint(root, cp2)
    assert store.read_head(root, 895) == cp2.checkpoint_id


def test_read_head_returns_none_when_absent(tmp_path: Path) -> None:
    assert store.read_head(tmp_path / "agent-os-checkpoints", 895) is None


# --- tamper detection / quarantine (never raises for one bad file) --------


def test_tampered_record_is_quarantined_not_raised(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    checkpoint = make_checkpoint()
    store.append_checkpoint(root, checkpoint)

    checkpoints_dir = store.issue_store_dir(root, 895) / "checkpoints"
    path = next(checkpoints_dir.glob("*.json"))
    original = path.read_bytes()
    path.write_bytes(original.replace(b"passed", b"failed"))

    result = store.load_checkpoints(root, 895)
    assert result.valid == ()
    assert len(result.quarantined) == 1
    assert "invalid" in result.quarantined[0].reason


def test_filename_hex_mismatch_is_quarantined(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    cp1 = make_checkpoint()
    cp2 = make_mutating(parent_id=cp1.checkpoint_id)
    store.append_checkpoint(root, cp1)
    store.append_checkpoint(root, cp2)

    checkpoints_dir = store.issue_store_dir(root, 895) / "checkpoints"
    files = sorted(checkpoints_dir.glob("*.json"))
    # Swap the two files' names, so each file's content no longer matches
    # its own filename's embedded checkpoint_id.
    a_bytes, b_bytes = files[0].read_bytes(), files[1].read_bytes()
    files[0].write_bytes(b_bytes)
    files[1].write_bytes(a_bytes)

    result = store.load_checkpoints(root, 895)
    assert result.valid == ()
    assert len(result.quarantined) == 2
    assert all("filename does not match" in q.reason for q in result.quarantined)


def test_descendant_of_quarantined_checkpoint_is_also_quarantined(tmp_path: Path) -> None:
    """A checkpoint whose parent has been directly quarantined (via
    write_quarantine_record) must itself be reported as quarantined, even
    though its own file content is untampered and independently valid."""

    root = tmp_path / "agent-os-checkpoints"
    cp1 = make_checkpoint()
    cp2 = make_mutating(parent_id=cp1.checkpoint_id)
    store.append_checkpoint(root, cp1)
    store.append_checkpoint(root, cp2)

    store.write_quarantine_record(root, 895, cp1.checkpoint_id, "manually quarantined for testing")

    result = store.load_checkpoints(root, 895)
    assert result.valid == ()
    assert cp1.checkpoint_id in result.quarantined_checkpoint_ids
    assert cp2.checkpoint_id in result.quarantined_checkpoint_ids
    reasons = {q.checkpoint_id: q.reason for q in result.quarantined if q.checkpoint_id}
    assert "descendant of a quarantined checkpoint" in reasons.get(cp2.checkpoint_id, "")
    assert reasons.get(cp1.checkpoint_id) == "previously quarantined"



def test_missing_parent_is_quarantined(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    missing = f"agent-os.execution-checkpoint:{'f' * 64}"
    child = make_mutating(parent_id=missing)
    store.append_checkpoint(root, child)

    result = store.load_checkpoints(root, 895)

    assert result.valid == ()
    assert child.checkpoint_id in result.quarantined_checkpoint_ids
    assert any("missing parent" in item.reason for item in result.quarantined)


def test_cross_execution_parent_is_quarantined(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    parent = make_checkpoint()
    child = make_mutating(
        parent_id=parent.checkpoint_id,
        execution_id="exe-2",
        invocation_id="inv-2",
    )
    store.append_checkpoint(root, parent)
    store.append_checkpoint(root, child)

    result = store.load_checkpoints(root, 895)

    assert tuple(item.checkpoint for item in result.valid) == (parent,)
    assert child.checkpoint_id in result.quarantined_checkpoint_ids
    assert any("different execution_id" in item.reason for item in result.quarantined)


def test_reordered_stage_is_quarantined(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    parent = make_mutating(
        stage=CheckpointStage.COMMITTED,
        lifecycle=LifecycleStage.IMPLEMENTATION,
    )
    child = make_mutating(
        parent_id=parent.checkpoint_id,
        stage=CheckpointStage.IMPLEMENTATION_COMPLETE,
        lifecycle=LifecycleStage.IMPLEMENTATION,
        invocation_id="inv-2",
    )
    store.append_checkpoint(root, parent)
    store.append_checkpoint(root, child)

    result = store.load_checkpoints(root, 895)

    assert tuple(item.checkpoint for item in result.valid) == (parent,)
    assert child.checkpoint_id in result.quarantined_checkpoint_ids
    assert any("stage order" in item.reason for item in result.quarantined)


def test_forked_chain_children_are_quarantined(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    parent = make_checkpoint()
    child_a = make_mutating(
        parent_id=parent.checkpoint_id,
        invocation_id="inv-a",
    )
    child_b = make_mutating(
        parent_id=parent.checkpoint_id,
        invocation_id="inv-b",
    )
    store.append_checkpoint(root, parent)
    store.append_checkpoint(root, child_a)
    store.append_checkpoint(root, child_b)

    result = store.load_checkpoints(root, 895)

    assert tuple(item.checkpoint for item in result.valid) == (parent,)
    assert child_a.checkpoint_id in result.quarantined_checkpoint_ids
    assert child_b.checkpoint_id in result.quarantined_checkpoint_ids
    assert sum(
        "forked execution chain" in item.reason
        for item in result.quarantined
    ) == 2


def test_multiple_genesis_records_for_one_execution_are_quarantined(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agent-os-checkpoints"
    first = make_checkpoint(invocation_id="inv-a")
    second = make_checkpoint(invocation_id="inv-b")
    store.append_checkpoint(root, first)
    store.append_checkpoint(root, second)

    result = store.load_checkpoints(root, 895)

    assert result.valid == ()
    assert first.checkpoint_id in result.quarantined_checkpoint_ids
    assert second.checkpoint_id in result.quarantined_checkpoint_ids


def test_tampered_parent_quarantines_valid_descendant(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    parent = make_checkpoint()
    child = make_mutating(parent_id=parent.checkpoint_id)
    store.append_checkpoint(root, parent)
    store.append_checkpoint(root, child)

    parent_path = (
        store.issue_store_dir(root, 895)
        / "checkpoints"
        / store._filename_for_checkpoint_id(parent.checkpoint_id)
    )
    parent_path.write_bytes(
        parent_path.read_bytes().replace(
            b'"stage_status":"passed"',
            b'"stage_status":"failed"',
        )
    )

    result = store.load_checkpoints(root, 895)

    assert result.valid == ()
    assert parent.checkpoint_id in result.quarantined_checkpoint_ids
    assert child.checkpoint_id in result.quarantined_checkpoint_ids


def test_write_quarantine_record_is_additive_and_original_untouched(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    checkpoint = make_checkpoint()
    store.append_checkpoint(root, checkpoint)
    before = (store.issue_store_dir(root, 895) / "checkpoints" / store._filename_for_checkpoint_id(checkpoint.checkpoint_id)).read_bytes()

    store.write_quarantine_record(root, 895, checkpoint.checkpoint_id, "manual quarantine for testing")

    after = (store.issue_store_dir(root, 895) / "checkpoints" / store._filename_for_checkpoint_id(checkpoint.checkpoint_id)).read_bytes()
    assert before == after

    result = store.load_checkpoints(root, 895)
    assert result.valid == ()
    assert checkpoint.checkpoint_id in result.quarantined_checkpoint_ids


# --- capacity enforcement ----------------------------------------------------


def test_capacity_exceeded_refuses_new_write_but_not_idempotent_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "MAX_RECORDS_PER_ISSUE", 1)
    root = tmp_path / "agent-os-checkpoints"
    cp1 = make_checkpoint()
    store.append_checkpoint(root, cp1)

    cp2 = make_mutating(parent_id=cp1.checkpoint_id)
    with pytest.raises(store.CheckpointStoreCapacityExceeded):
        store.append_checkpoint(root, cp2)

    # Re-appending the already-present record is still accepted (idempotent).
    outcome = store.append_checkpoint(root, cp1)
    assert outcome.already_present is True


def test_capacity_exceeded_by_bytes_refuses_new_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "MAX_BYTES_PER_ISSUE", 1)
    root = tmp_path / "agent-os-checkpoints"
    with pytest.raises(store.CheckpointStoreCapacityExceeded):
        store.append_checkpoint(root, make_checkpoint())


# --- integrity conflict (content-addressed path holding different bytes) --


def test_integrity_conflict_when_content_addressed_path_disagrees(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    checkpoint = make_checkpoint()
    store.append_checkpoint(root, checkpoint)

    checkpoints_dir = store.issue_store_dir(root, 895) / "checkpoints"
    path = next(checkpoints_dir.glob("*.json"))
    path.write_bytes(b"not the real content, but same filename")

    with pytest.raises(store.CheckpointStoreIntegrityConflict):
        store.append_checkpoint(root, checkpoint)


# --- store availability ------------------------------------------------------


def test_store_is_available_for_a_fresh_writable_directory(tmp_path: Path) -> None:
    assert store.store_is_available(tmp_path / "agent-os-checkpoints") is True


def test_store_is_available_false_when_root_is_a_file(tmp_path: Path) -> None:
    blocker = tmp_path / "agent-os-checkpoints"
    blocker.write_text("not a directory")
    assert store.store_is_available(blocker) is False


# --- retention ----------------------------------------------------------


def test_retention_cutoff_terminal_is_thirty_days() -> None:
    now = 1_000_000.0
    cutoff = store.retention_cutoff_epoch_seconds(terminal=True, now=now)
    assert now - cutoff == pytest.approx(30 * 24 * 60 * 60)


def test_retention_cutoff_non_terminal_is_fourteen_days() -> None:
    now = 1_000_000.0
    cutoff = store.retention_cutoff_epoch_seconds(terminal=False, now=now)
    assert now - cutoff == pytest.approx(14 * 24 * 60 * 60)


# --- symlink rejection --------------------------------------------------


def test_append_rejects_symlinked_issue_directory(tmp_path: Path) -> None:
    root = tmp_path / "agent-os-checkpoints"
    root.mkdir()
    real_target = tmp_path / "elsewhere"
    real_target.mkdir()
    (root / "issue-895").symlink_to(real_target)

    with pytest.raises(store.CheckpointStoreUnavailable):
        store.append_checkpoint(root, make_checkpoint())
