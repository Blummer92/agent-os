"""Focused tests for scripts/agent_os_execution_checkpoint/models.py."""
from __future__ import annotations

import hashlib

import pytest

from scripts.agent_os_execution_checkpoint.models import (
    CANONICAL_STAGE_ORDER,
    STAGE_KIND_MAP,
    CheckpointStage,
    ExecutionCheckpoint,
    InvalidationState,
    LifecycleState,
    StageKind,
    StageStatus,
    WorktreeRole,
    checkpoint_from_dict,
    deserialize_checkpoint,
    serialize_checkpoint,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import LifecycleStage

SHA40 = "7d01ad36d7f9c9cba41c9fee62a562b7689c2fbe"
HEX64 = hashlib.sha256(b"x").hexdigest()
HEX64_B = hashlib.sha256(b"y").hexdigest()
COMMAND_PLAN_ID = f"command-plan:{HEX64}"


def make_checkpoint(**overrides: object) -> ExecutionCheckpoint:
    fields: dict[str, object] = {
        "schema_name": "agent-os-execution-checkpoint",
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


# --- construction and round trip -------------------------------------------


def test_valid_checkpoint_constructs_and_computes_identity() -> None:
    checkpoint = make_checkpoint()
    assert checkpoint.checkpoint_id.startswith("agent-os.execution-checkpoint:")
    assert checkpoint.reuse_key.startswith("agent-os.execution-checkpoint.reuse-key:")


def test_serialize_deserialize_round_trip_is_byte_stable() -> None:
    checkpoint = make_checkpoint()
    payload = serialize_checkpoint(checkpoint)
    payload_again = serialize_checkpoint(checkpoint)
    assert payload == payload_again
    reconstructed = deserialize_checkpoint(payload)
    assert reconstructed == checkpoint
    assert reconstructed.checkpoint_id == checkpoint.checkpoint_id


def test_deterministic_identity_for_identical_immutable_inputs() -> None:
    a = make_checkpoint()
    b = make_checkpoint()
    assert a.checkpoint_id == b.checkpoint_id
    assert a.reuse_key == b.reuse_key


def test_different_invocation_id_changes_checkpoint_id_but_not_reuse_key() -> None:
    a = make_checkpoint(invocation_id="inv-1")
    b = make_checkpoint(invocation_id="inv-2")
    assert a.checkpoint_id != b.checkpoint_id
    assert a.reuse_key == b.reuse_key


def test_recorded_at_is_observational_and_excluded_from_identity() -> None:
    a = make_checkpoint(recorded_at="2026-08-05T12:00:00Z")
    b = make_checkpoint(recorded_at="2026-08-05T13:30:00Z")
    assert a.checkpoint_id == b.checkpoint_id


def test_actor_id_is_observational_and_excluded_from_identity() -> None:
    a = make_checkpoint(actor_id="github-service-agent")
    b = make_checkpoint(actor_id="integration-manager")
    assert a.checkpoint_id == b.checkpoint_id


def test_diagnostic_refs_are_observational_and_excluded_from_identity() -> None:
    a = make_checkpoint(diagnostic_refs=())
    b = make_checkpoint(diagnostic_refs=("some-diagnostic-ref",))
    assert a.checkpoint_id == b.checkpoint_id


def test_evidence_hashes_change_checkpoint_id() -> None:
    a = make_checkpoint(evidence_hashes=())
    b = make_checkpoint(evidence_hashes=(("validate_all_stdout", HEX64),))
    assert a.checkpoint_id != b.checkpoint_id


# --- unknown / missing field rejection --------------------------------------


def test_unsupported_schema_version_fails_closed() -> None:
    with pytest.raises(ValueError):
        make_checkpoint(schema_version="2.0")


def test_checkpoint_from_dict_rejects_unknown_field() -> None:
    payload = make_checkpoint().to_dict()
    payload["unexpected_field"] = "value"
    with pytest.raises(ValueError):
        checkpoint_from_dict(payload)


def test_checkpoint_from_dict_rejects_missing_field() -> None:
    payload = make_checkpoint().to_dict()
    del payload["repository"]
    with pytest.raises(ValueError):
        checkpoint_from_dict(payload)


def test_checkpoint_from_dict_rejects_claimed_authority() -> None:
    payload = make_checkpoint().to_dict()
    payload["merge_authorized"] = True
    with pytest.raises(ValueError):
        checkpoint_from_dict(payload)


# --- cross-field and bounds validation --------------------------------------


def test_lifecycle_stage_must_match_checkpoint_stage_canonical_mapping() -> None:
    with pytest.raises(ValueError):
        make_checkpoint(
            checkpoint_stage=CheckpointStage.PREFLIGHT_COMPLETE,
            lifecycle_stage=LifecycleStage.IMPLEMENTATION,
        )


def test_branch_cannot_be_main() -> None:
    with pytest.raises(ValueError):
        make_checkpoint(branch="main")


def test_read_only_stage_forbids_mutation_intent_id() -> None:
    with pytest.raises(ValueError):
        make_checkpoint(mutation_intent_id=f"agent-os.mutation-intent:{HEX64}")


def test_passed_mutating_stage_requires_mutation_intent_id() -> None:
    with pytest.raises(ValueError):
        make_checkpoint(
            checkpoint_stage=CheckpointStage.IMPLEMENTATION_COMPLETE,
            lifecycle_stage=LifecycleStage.IMPLEMENTATION,
            stage_status=StageStatus.PASSED,
            mutation_intent_id=None,
        )


def test_passed_mutating_stage_accepts_mutation_intent_id() -> None:
    checkpoint = make_checkpoint(
        checkpoint_stage=CheckpointStage.IMPLEMENTATION_COMPLETE,
        lifecycle_stage=LifecycleStage.IMPLEMENTATION,
        stage_status=StageStatus.PASSED,
        mutation_intent_id=f"agent-os.mutation-intent:{HEX64}",
    )
    assert checkpoint.mutation_intent_id is not None


def test_superseded_requires_supersession_state() -> None:
    with pytest.raises(ValueError):
        make_checkpoint(invalidation_state=InvalidationState.SUPERSEDED, supersession_state=None)


def test_supersession_state_forbidden_unless_superseded() -> None:
    with pytest.raises(ValueError):
        make_checkpoint(
            invalidation_state=InvalidationState.CURRENT,
            supersession_state=f"agent-os.execution-checkpoint:{HEX64_B}",
        )


def test_parent_checkpoint_id_links_a_child_and_affects_its_identity() -> None:
    parent = make_checkpoint()
    child = make_checkpoint(
        checkpoint_stage=CheckpointStage.IMPLEMENTATION_COMPLETE,
        lifecycle_stage=LifecycleStage.IMPLEMENTATION,
        stage_status=StageStatus.PASSED,
        mutation_intent_id=f"agent-os.mutation-intent:{HEX64}",
        parent_checkpoint_id=parent.checkpoint_id,
    )
    assert child.parent_checkpoint_id == parent.checkpoint_id
    orphan = make_checkpoint(
        checkpoint_stage=CheckpointStage.IMPLEMENTATION_COMPLETE,
        lifecycle_stage=LifecycleStage.IMPLEMENTATION,
        stage_status=StageStatus.PASSED,
        mutation_intent_id=f"agent-os.mutation-intent:{HEX64}",
        parent_checkpoint_id=None,
    )
    assert child.checkpoint_id != orphan.checkpoint_id


def test_evidence_hashes_rejects_duplicate_name() -> None:
    with pytest.raises(ValueError):
        make_checkpoint(evidence_hashes=(("pr_head_sha", HEX64), ("pr_head_sha", HEX64_B)))


def test_evidence_hashes_rejects_malformed_digest() -> None:
    with pytest.raises(ValueError):
        make_checkpoint(evidence_hashes=(("pr_head_sha", "not-hex"),))


def test_diagnostic_refs_bounded_count() -> None:
    with pytest.raises(ValueError):
        make_checkpoint(diagnostic_refs=tuple(f"ref-{i}" for i in range(9)))


def test_repository_must_be_owner_slash_name() -> None:
    with pytest.raises(ValueError):
        make_checkpoint(repository="not-a-valid-repository")


def test_source_sha_must_be_exact_forty_hex() -> None:
    with pytest.raises(ValueError):
        make_checkpoint(source_sha="abc123")


# --- authority always false -------------------------------------------------


def test_all_six_authority_fields_are_always_false() -> None:
    checkpoint = make_checkpoint()
    assert checkpoint.repository_implementation_authorized is False
    assert checkpoint.execution_authorized is False
    assert checkpoint.github_writes_authorized is False
    assert checkpoint.merge_authorized is False
    assert checkpoint.issue_closure_authorized is False
    assert checkpoint.external_writes_authorized is False


# --- stage table consistency -------------------------------------------------


def test_canonical_stage_order_has_eleven_stages() -> None:
    assert len(CANONICAL_STAGE_ORDER) == 11


def test_merged_and_closed_are_mutating_remote_and_never_auto_resumed() -> None:
    from scripts.agent_os_execution_checkpoint.models import STAGE_AUTO_RESUME_SAFE_MAP

    assert STAGE_KIND_MAP[CheckpointStage.MERGED] is StageKind.MUTATING_REMOTE
    assert STAGE_KIND_MAP[CheckpointStage.ISSUE_CLOSED] is StageKind.MUTATING_REMOTE
    assert STAGE_AUTO_RESUME_SAFE_MAP[CheckpointStage.MERGED] is False
    assert STAGE_AUTO_RESUME_SAFE_MAP[CheckpointStage.ISSUE_CLOSED] is False


# --- no secrets / bounded size -----------------------------------------------


def test_no_secret_looking_field_exists_on_the_model() -> None:
    field_names = set(ExecutionCheckpoint.__dataclass_fields__)
    for forbidden in ("secret", "token", "password", "credential", "api_key"):
        assert not any(forbidden in name.lower() for name in field_names), forbidden


def test_deserialize_rejects_oversized_payload() -> None:
    from scripts.agent_os_execution_checkpoint.models import MAX_SERIALIZED_BYTES

    with pytest.raises(ValueError):
        deserialize_checkpoint(b"x" * (MAX_SERIALIZED_BYTES + 1))
