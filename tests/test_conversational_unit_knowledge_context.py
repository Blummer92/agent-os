from __future__ import annotations

import copy

import pytest

from instructional_workflow_contracts import ValidationStatus
from instructional_workflow_contracts.conversational_unit_knowledge import (
    decide_conversational_unit_knowledge,
)
from instructional_workflow_contracts.conversational_unit_knowledge_context import (
    MAX_CANDIDATES,
    ConversationalKnowledgeContextError,
    prepare_conversational_unit_knowledge_input,
)


def _candidate(candidate_id: str = "candidate-1", target: str | None = None) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "knowledge_class": "working",
        "subtype": "candidate-idea",
        "value": "Move composition earlier.",
        "persistence_intent": "suggest",
        "target_entity_ref": target,
        "source_reference": {
            "system": "chatgpt",
            "stable_id": f"conversation-{candidate_id}",
            "exact_location": f"conversation:{candidate_id}",
            "verification_evidence": "teacher-supplied-resolved-meaning",
        },
        "temporal_scope": None,
        "existing_relation": "none",
        "existing_ref": None,
        "freshness": "unknown",
        "outbound_routes": [],
    }


def _packet(*candidates: dict[str, object]) -> dict[str, object]:
    return {
        "context": {"current_entity_ref": "unit-photography", "plausible_entity_refs": []},
        "candidates": list(candidates),
        "existing_knowledge": [],
        "authority": {
            "execution_authorized": False,
            "external_write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
        },
    }


def _evidence(
    candidate_id: str = "candidate-1",
    *,
    relation: str = "none",
    existing_ref: str | None = None,
    freshness: str = "current",
    target: str = "unit-photography",
    verified: bool = True,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "target_entity_ref": target,
        "existing_relation": relation,
        "existing_ref": existing_ref,
        "freshness": freshness,
        "identity_verified": verified,
    }


@pytest.mark.parametrize("relation", ["identical", "conflicting", "supersedes"])
def test_preserves_exact_relation_reference_and_freshness(relation: str) -> None:
    source = _packet(_candidate())
    original = copy.deepcopy(source)
    result = prepare_conversational_unit_knowledge_input(
        source,
        [_evidence(relation=relation, existing_ref="knowledge-1", freshness="stale")],
    )

    assert source == original
    candidate = result["candidates"][0]
    assert candidate["target_entity_ref"] == "unit-photography"
    assert candidate["existing_relation"] == relation
    assert candidate["existing_ref"] == "knowledge-1"
    assert candidate["freshness"] == "stale"
    assert result["existing_knowledge"] == [
        {
            "candidate_id": "candidate-1",
            "target_entity_ref": "unit-photography",
            "existing_relation": relation,
            "existing_ref": "knowledge-1",
            "freshness": "stale",
        }
    ]


def test_no_match_preserves_none_without_inventing_reference() -> None:
    result = prepare_conversational_unit_knowledge_input(_packet(_candidate()), [_evidence()])
    candidate = result["candidates"][0]
    assert candidate["existing_relation"] == "none"
    assert candidate["existing_ref"] is None
    assert candidate["freshness"] == "current"


@pytest.mark.parametrize(
    "evidence, message",
    [
        ([], "missing candidate-specific context evidence"),
        ([_evidence(verified=False)], "identity is unverified"),
        ([_evidence(relation="similar")], "unsupported existing_relation"),
        ([_evidence(relation="identical")], "existing_ref must be non-empty text"),
        ([_evidence(existing_ref="knowledge-1")], "existing_ref requires an existing relation"),
        ([_evidence(freshness="fresh-ish")], "unsupported freshness"),
        ([_evidence(target="unit-typography")], "verified target conflicts with current entity context"),
    ],
)
def test_fail_closed_on_missing_ambiguous_or_unverified_evidence(
    evidence: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(ConversationalKnowledgeContextError, match=message):
        prepare_conversational_unit_knowledge_input(_packet(_candidate()), evidence)


def test_duplicate_or_unknown_candidate_evidence_fails_closed() -> None:
    packet = _packet(_candidate())
    with pytest.raises(ConversationalKnowledgeContextError, match="ambiguous duplicate"):
        prepare_conversational_unit_knowledge_input(packet, [_evidence(), _evidence()])

    with pytest.raises(ConversationalKnowledgeContextError, match="unknown candidate"):
        prepare_conversational_unit_knowledge_input(
            packet,
            [_evidence(), _evidence("candidate-2")],
        )


def test_existing_explicit_target_must_match_verified_target() -> None:
    packet = _packet(_candidate(target="unit-typography"))
    with pytest.raises(ConversationalKnowledgeContextError, match="candidate target conflicts"):
        prepare_conversational_unit_knowledge_input(packet, [_evidence()])


def test_multiple_candidates_are_candidate_local_and_order_preserving() -> None:
    packet = _packet(_candidate("candidate-1"), _candidate("candidate-2"))
    result = prepare_conversational_unit_knowledge_input(
        packet,
        [
            _evidence("candidate-2", relation="conflicting", existing_ref="knowledge-2"),
            _evidence("candidate-1", relation="identical", existing_ref="knowledge-1"),
        ],
    )
    assert [item["candidate_id"] for item in result["candidates"]] == ["candidate-1", "candidate-2"]
    assert [item["existing_relation"] for item in result["candidates"]] == ["identical", "conflicting"]
    assert result["authority"] == packet["authority"]


def test_candidate_evidence_bound_accepts_32_and_rejects_33_before_processing() -> None:
    candidates = [_candidate(f"candidate-{index}") for index in range(MAX_CANDIDATES)]
    evidence = [_evidence(f"candidate-{index}") for index in range(MAX_CANDIDATES)]
    result = prepare_conversational_unit_knowledge_input(_packet(*candidates), evidence)
    assert len(result["candidates"]) == MAX_CANDIDATES

    oversized = evidence + [_evidence("candidate-overflow")]
    with pytest.raises(ConversationalKnowledgeContextError, match="candidate evidence count exceeds bound"):
        prepare_conversational_unit_knowledge_input(_packet(*candidates), oversized)


@pytest.mark.parametrize(
    ("relation", "freshness", "existing_ref", "expected"),
    [
        ("identical", "current", "knowledge-1", "unchanged"),
        ("identical", "stale", "knowledge-1", "reconfirm"),
        ("conflicting", "current", "knowledge-1", "conflict"),
        ("supersedes", "current", "knowledge-1", "correction"),
        ("none", "current", None, "propose-persistence"),
    ],
)
def test_prepared_input_is_phase1_compatible(
    relation: str, freshness: str, existing_ref: str | None, expected: str
) -> None:
    prepared = prepare_conversational_unit_knowledge_input(
        _packet(_candidate()),
        [_evidence(relation=relation, freshness=freshness, existing_ref=existing_ref)],
    )
    result = decide_conversational_unit_knowledge(prepared)
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["decisions"][0]["disposition"] == expected
    assert payload["authority"] == {
        "execution_authorized": False,
        "external_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
    }
