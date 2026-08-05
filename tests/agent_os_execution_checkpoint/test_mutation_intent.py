"""Focused tests for scripts/agent_os_execution_checkpoint/mutation_intent.py."""
from __future__ import annotations

import hashlib

import pytest

from scripts.agent_os_execution_checkpoint.mutation_intent import (
    MUTATION_INTENT_DOMAIN,
    compute_mutation_intent_id,
)

HEX64 = hashlib.sha256(b"x").hexdigest()
HEX64_B = hashlib.sha256(b"y").hexdigest()
PARENT_ID = f"agent-os.execution-checkpoint:{HEX64}"


def base_kwargs(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "repository": "Blummer92/agent-os",
        "issue_number": 895,
        "execution_id": "exe-1",
        "checkpoint_stage": "implementation-complete",
        "target_ref": "agent/895-execution-checkpoint",
        "content_digest": HEX64,
        "parent_checkpoint_id": PARENT_ID,
    }
    fields.update(overrides)
    return fields


def test_mutation_intent_id_has_expected_domain_prefix() -> None:
    value = compute_mutation_intent_id(**base_kwargs())
    assert value.startswith(f"{MUTATION_INTENT_DOMAIN}:")


def test_stable_across_repeated_calls_with_identical_arguments() -> None:
    a = compute_mutation_intent_id(**base_kwargs())
    b = compute_mutation_intent_id(**base_kwargs())
    assert a == b


def test_differs_when_content_digest_differs() -> None:
    a = compute_mutation_intent_id(**base_kwargs(content_digest=HEX64))
    b = compute_mutation_intent_id(**base_kwargs(content_digest=HEX64_B))
    assert a != b


def test_differs_when_target_ref_differs() -> None:
    a = compute_mutation_intent_id(**base_kwargs(target_ref="agent/895-a"))
    b = compute_mutation_intent_id(**base_kwargs(target_ref="agent/895-b"))
    assert a != b


def test_differs_when_checkpoint_stage_differs() -> None:
    a = compute_mutation_intent_id(**base_kwargs(checkpoint_stage="pushed"))
    b = compute_mutation_intent_id(**base_kwargs(checkpoint_stage="draft-pr-opened"))
    assert a != b


def test_differs_when_execution_id_differs() -> None:
    a = compute_mutation_intent_id(**base_kwargs(execution_id="exe-1"))
    b = compute_mutation_intent_id(**base_kwargs(execution_id="exe-2"))
    assert a != b


def test_differs_when_parent_checkpoint_id_differs() -> None:
    a = compute_mutation_intent_id(**base_kwargs(parent_checkpoint_id=PARENT_ID))
    b = compute_mutation_intent_id(**base_kwargs(parent_checkpoint_id=None))
    assert a != b


def test_none_parent_checkpoint_id_is_accepted_for_a_genesis_mutation() -> None:
    value = compute_mutation_intent_id(**base_kwargs(parent_checkpoint_id=None))
    assert value.startswith(f"{MUTATION_INTENT_DOMAIN}:")


def test_rejects_malformed_target_ref() -> None:
    with pytest.raises(ValueError):
        compute_mutation_intent_id(**base_kwargs(target_ref="not a ref!"))


def test_rejects_malformed_content_digest() -> None:
    with pytest.raises(ValueError):
        compute_mutation_intent_id(**base_kwargs(content_digest="too-short"))


def test_rejects_malformed_repository() -> None:
    with pytest.raises(ValueError):
        compute_mutation_intent_id(**base_kwargs(repository="not-owner-slash-name"))
