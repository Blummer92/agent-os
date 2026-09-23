from __future__ import annotations

import copy

import pytest

from instructional_workflow_contracts import AuthorityEvidence, ValidationStatus
from instructional_workflow_contracts.common import MAX_STRING_LENGTH
from instructional_workflow_contracts.conversational_unit_knowledge import (
    decide_conversational_unit_knowledge,
)


def _ref(suffix: str = "1") -> dict[str, str]:
    return {
        "system": "chatgpt",
        "stable_id": f"conversation-{suffix}",
        "exact_location": f"conversation:{suffix}",
        "verification_evidence": "teacher-supplied-resolved-meaning",
    }


def candidate(
    *,
    candidate_id: str = "candidate-1",
    knowledge_class: str = "working",
    subtype: str | None = "candidate-idea",
    value: object = "A cyanotype mini-project could work after composition.",
    persistence_intent: str = "suggest",
    target_entity_ref: str | None = None,
    temporal_scope: str | None = None,
    existing_relation: str = "none",
    existing_ref: str | None = None,
    freshness: str = "current",
    outbound_routes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "knowledge_class": knowledge_class,
        "subtype": subtype,
        "value": value,
        "persistence_intent": persistence_intent,
        "target_entity_ref": target_entity_ref,
        "source_reference": _ref(candidate_id),
        "temporal_scope": temporal_scope,
        "existing_relation": existing_relation,
        "existing_ref": existing_ref,
        "freshness": freshness,
        "outbound_routes": [] if outbound_routes is None else outbound_routes,
    }


def packet(*candidates: dict[str, object], current: str | None = "unit-photography") -> dict[str, object]:
    return {
        "context": {
            "current_entity_ref": current,
            "plausible_entity_refs": [] if current else ["unit-photography"],
        },
        "candidates": list(candidates),
        "existing_knowledge": [],
        "authority": {
            "execution_authorized": False,
            "external_write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
        },
    }


def payload(result) -> dict[str, object]:
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    return result.record.to_dict()


def decision(result, index: int = 0) -> dict[str, object]:
    return payload(result)["decisions"][index]  # type: ignore[index,return-value]


@pytest.mark.parametrize(
    ("item", "expected", "has_mutation"),
    [
        (candidate(knowledge_class="transient", persistence_intent="none"), "do-not-persist", False),
        (candidate(), "propose-persistence", True),
        (candidate(knowledge_class="durable", subtype="instructional-decision"), "propose-persistence", True),
        (candidate(knowledge_class="observation", subtype="lesson-observation"), "propose-persistence", True),
        (candidate(knowledge_class="observation", subtype="lesson-learned", persistence_intent="explicit"), "explicit-persistence", True),
        (candidate(persistence_intent="cancel"), "do-not-persist", False),
        (candidate(existing_relation="identical", existing_ref="knowledge-1"), "unchanged", False),
        (candidate(existing_relation="conflicting", existing_ref="knowledge-1"), "conflict", False),
        (candidate(existing_relation="supersedes", existing_ref="knowledge-1"), "correction", True),
        (candidate(temporal_scope="semester-2026-fall"), "temporal-update", True),
        (candidate(existing_relation="identical", existing_ref="knowledge-1", freshness="stale"), "reconfirm", False),
        (candidate(existing_relation="conflicting", existing_ref="knowledge-1", freshness="stale"), "reconfirm", False),
    ],
)
def test_core_dispositions(item: dict[str, object], expected: str, has_mutation: bool) -> None:
    actual = decision(decide_conversational_unit_knowledge(packet(item)))
    assert actual["disposition"] == expected
    assert (actual["mutation"] is not None) is has_mutation


def test_explicit_target_override_single_plausible_and_ambiguous_target() -> None:
    override = candidate(target_entity_ref="unit-typography", persistence_intent="explicit")
    actual = decision(decide_conversational_unit_knowledge(packet(override)))
    assert actual["target_entity_ref"] == "unit-typography"

    single = packet(candidate(persistence_intent="explicit"), current=None)
    single_actual = decision(decide_conversational_unit_knowledge(single))
    assert single_actual["target_entity_ref"] == "unit-photography"
    assert single_actual["disposition"] == "explicit-persistence"

    ambiguous_packet = packet(candidate(persistence_intent="explicit"), current=None)
    ambiguous_packet["context"]["plausible_entity_refs"] = ["unit-photography", "unit-typography"]  # type: ignore[index]
    ambiguous = decision(decide_conversational_unit_knowledge(ambiguous_packet))
    assert ambiguous["disposition"] == "needs-clarification"
    assert ambiguous["mutation"] is None

    missing = packet(candidate(persistence_intent="explicit"), current=None)
    missing["context"]["plausible_entity_refs"] = []  # type: ignore[index]
    missing_actual = decision(decide_conversational_unit_knowledge(missing))
    assert missing_actual["disposition"] == "needs-clarification"


def test_batch_output_supports_compact_save_proposal_and_is_candidate_local() -> None:
    items = [
        candidate(candidate_id="composition", knowledge_class="durable", value="Move composition earlier."),
        candidate(candidate_id="photo-walk", knowledge_class="transient", persistence_intent="none", value="Maybe walk."),
        candidate(candidate_id="exposure", knowledge_class="durable", value="Move exposure later."),
    ]
    result = payload(decide_conversational_unit_knowledge(packet(*items)))
    assert [item["candidate_id"] for item in result["decisions"]] == ["composition", "photo-walk", "exposure"]  # type: ignore[index]
    assert [item["disposition"] for item in result["decisions"]] == [  # type: ignore[index]
        "propose-persistence",
        "do-not-persist",
        "propose-persistence",
    ]


def test_temporal_update_does_not_supersede_typical_value() -> None:
    actual = decision(
        decide_conversational_unit_knowledge(
            packet(
                candidate(
                    value="Five weeks",
                    temporal_scope="semester-2026-fall",
                    existing_relation="conflicting",
                    existing_ref="typical-duration",
                )
            )
        )
    )
    assert actual["disposition"] == "conflict"
    assert actual["mutation"] is None

    scoped = decision(
        decide_conversational_unit_knowledge(
            packet(candidate(value="Five weeks", temporal_scope="semester-2026-fall"))
        )
    )
    assert scoped["disposition"] == "temporal-update"
    assert scoped["mutation"]["operation"] == "add-temporal"  # type: ignore[index]
    assert scoped["mutation"]["supersedes_ref"] is None  # type: ignore[index]


def test_correction_supersedes_existing_reference() -> None:
    actual = decision(
        decide_conversational_unit_knowledge(
            packet(
                candidate(
                    knowledge_class="durable",
                    value="Seven weeks",
                    existing_relation="supersedes",
                    existing_ref="duration-six-weeks",
                )
            )
        )
    )
    assert actual["disposition"] == "correction"
    assert actual["mutation"]["operation"] == "supersede"  # type: ignore[index]
    assert actual["mutation"]["supersedes_ref"] == "duration-six-weeks"  # type: ignore[index]


@pytest.mark.parametrize(
    ("existing_relation", "existing_ref"),
    [
        ("identical", None),
        ("conflicting", None),
        ("supersedes", None),
        ("none", "knowledge-1"),
    ],
)
def test_existing_relation_and_reference_must_be_consistent(
    existing_relation: str,
    existing_ref: str | None,
) -> None:
    result = decide_conversational_unit_knowledge(
        packet(candidate(existing_relation=existing_relation, existing_ref=existing_ref))
    )
    assert result.status is ValidationStatus.INVALID
    assert result.record is None
    assert "handoff-invalid" in result.reason_codes


def test_asset_requirement_is_only_routed_to_961_boundary() -> None:
    result = decide_conversational_unit_knowledge(
        packet(
            candidate(
                candidate_id="lesson-learned",
                knowledge_class="observation",
                subtype="lesson-learned",
                persistence_intent="explicit",
            ),
            candidate(
                candidate_id="visual-need",
                knowledge_class="requirement",
                subtype="visual-requirement",
                outbound_routes=["issue-961"],
            ),
        )
    )
    visual = decision(result, 1)
    assert visual["outbound_routes"] == ["issue-961"]
    assert visual["mutation"] is not None

    lesson = decision(result, 0)
    assert lesson["outbound_routes"] == []
    assert lesson["disposition"] == "explicit-persistence"


def test_all_authority_remains_false_and_escalation_fails_closed() -> None:
    result = decide_conversational_unit_knowledge(packet(candidate(persistence_intent="explicit")))
    output = payload(result)
    assert output["authority"] == {
        "execution_authorized": False,
        "external_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
    }
    assert result.authority == AuthorityEvidence()
    mutation = output["decisions"][0]["mutation"]  # type: ignore[index]
    assert mutation["execution_authorized"] is False
    assert mutation["external_write_authorized"] is False
    assert mutation["production_authorized"] is False
    assert mutation["publication_authorized"] is False

    attack = packet(candidate())
    attack["authority"]["external_write_authorized"] = True  # type: ignore[index]
    rejected = decide_conversational_unit_knowledge(attack)
    assert rejected.status is ValidationStatus.INVALID
    assert "authority-invalid" in rejected.reason_codes


def test_determinism_order_normalization_and_input_immutability() -> None:
    supplied = packet(candidate(outbound_routes=["issue-961", "issue-937"]))
    supplied["context"]["plausible_entity_refs"] = ["unit-typography", "unit-photography"]  # type: ignore[index]
    before = copy.deepcopy(supplied)
    first = decide_conversational_unit_knowledge(supplied)
    reordered = copy.deepcopy(supplied)
    reordered["context"]["plausible_entity_refs"].reverse()  # type: ignore[index,union-attr]
    reordered["candidates"][0]["outbound_routes"].reverse()  # type: ignore[index,union-attr]
    second = decide_conversational_unit_knowledge(reordered)
    assert first.record is not None and second.record is not None
    assert first.record.fingerprint == second.record.fingerprint
    assert supplied == before


def test_candidate_order_is_meaningful_and_preserved() -> None:
    left = packet(candidate(candidate_id="first"), candidate(candidate_id="second"))
    right = packet(candidate(candidate_id="second"), candidate(candidate_id="first"))
    left_result = decide_conversational_unit_knowledge(left)
    right_result = decide_conversational_unit_knowledge(right)
    assert left_result.record is not None and right_result.record is not None
    assert left_result.record.fingerprint != right_result.record.fingerprint
    assert [item["candidate_id"] for item in left_result.record.to_dict()["decisions"]] == ["first", "second"]


def test_duplicate_candidate_ids_fail_closed() -> None:
    result = decide_conversational_unit_knowledge(packet(candidate(), candidate()))
    assert result.status is ValidationStatus.INVALID
    assert "identity-duplicate" in result.reason_codes


def test_malformed_wrong_type_unsupported_and_oversized_input_fail_closed() -> None:
    malformed = packet(candidate())
    malformed["candidates"][0]["unknown"] = "field"  # type: ignore[index]
    result = decide_conversational_unit_knowledge(malformed)
    assert result.status is ValidationStatus.INVALID
    assert "handoff-unknown-field" in result.reason_codes

    wrong_type = packet(candidate())
    wrong_type["candidates"][0]["candidate_id"] = 7  # type: ignore[index]
    wrong_type_result = decide_conversational_unit_knowledge(wrong_type)
    assert wrong_type_result.status is ValidationStatus.INVALID
    assert "handoff-wrong-type" in wrong_type_result.reason_codes

    unsupported = packet(candidate(knowledge_class="magic"))
    unsupported_result = decide_conversational_unit_knowledge(unsupported)
    assert unsupported_result.status is ValidationStatus.INVALID
    assert "handoff-invalid" in unsupported_result.reason_codes

    malformed_id = packet(candidate(candidate_id="bad id"))
    malformed_id_result = decide_conversational_unit_knowledge(malformed_id)
    assert malformed_id_result.status is ValidationStatus.INVALID
    assert "identity-invalid" in malformed_id_result.reason_codes

    oversized = packet(candidate(value="x" * (MAX_STRING_LENGTH + 1)))
    oversized_result = decide_conversational_unit_knowledge(oversized)
    assert oversized_result.status is ValidationStatus.INVALID
    assert oversized_result.record is None
    assert "handoff-invalid" in oversized_result.reason_codes
