from __future__ import annotations

import copy

import pytest

from instructional_workflow_contracts import (
    ANALYZE_RESPONSE_EVIDENCE_ACTION,
    CTA_ACTIONS,
    GUIDED_PRACTICE_ACTION,
    GUIDED_PRACTICE_ARTIFACT_TYPE,
    GUIDED_PRACTICE_MAPPING_CONSTRAINT,
    ROUTING_MATRIX,
    ValidationStatus,
    route_action,
    validate_contextual_teacher_action,
)
from instructional_workflow_contracts.common import sha256_hex

EXPECTED_ACTIONS = {
    "improve",
    "differentiate",
    "clarify",
    "check-alignment",
    "generate-modeling",
    "generate-guided-practice",
    "generate-assessment",
    "generate-lesson-bundle",
    "analyze-response-evidence",
}


def payload(**overrides):
    value = {
        "schema_name": "contextual-teacher-action",
        "contract_version": "cta-v1.0.0",
        "record_revision": 1,
        "observed_at": "2026-10-01T00:00:00Z",
        "producer_id": "chatgpt-orchestrator",
        "raw_input_digest": sha256_hex("Improve the ZAP lesson worksheet."),
        "instruction_origin": "direct-user",
        "action": "improve",
        "requested_effect": "propose",
        "continuation_mode": "new",
        "artifact": {
            "stable_id": "worksheet-42",
            "record_revision": 1,
            "source_fingerprint": "fp-1",
            "course_ref": "digital-media",
            "unit_ref": "candy-motion-spot",
            "lesson_ref": "day-3",
            "source_system": "google-docs",
            "artifact_type": "worksheet",
        },
        "selection": {"selection_kind": "none", "selector": None, "verified": True},
        "requested_output": "Tighten the exit-ticket wording.",
        "destination": None,
        "constraints": [],
        "reason_codes": [],
        "evidence_references": [],
    }
    value.update(overrides)
    return value


def test_action_vocabulary_is_the_closed_nine():
    assert CTA_ACTIONS == EXPECTED_ACTIONS


@pytest.mark.parametrize("action", sorted(EXPECTED_ACTIONS))
def test_valid_record_for_each_action(action):
    extra = {}
    if action == GUIDED_PRACTICE_ACTION:
        extra["constraints"] = [
            {"name": GUIDED_PRACTICE_MAPPING_CONSTRAINT, "value": GUIDED_PRACTICE_ARTIFACT_TYPE}
        ]
    result = validate_contextual_teacher_action(payload(action=action, **extra))
    if action == ANALYZE_RESPONSE_EVIDENCE_ACTION:
        # Unsupported terminal is still a governed record: manual review.
        assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
        assert result.record is not None
        assert "action.unsupported" in result.record.to_dict()["reason_codes"]
    else:
        assert result.status is ValidationStatus.VALID
        assert result.record is not None


def test_valid_record_is_deterministic_authority_false_and_input_immutable():
    value = payload()
    original = copy.deepcopy(value)
    first = validate_contextual_teacher_action(value)
    second = validate_contextual_teacher_action(copy.deepcopy(value))
    assert first.status is ValidationStatus.VALID
    assert first.record.fingerprint == second.record.fingerprint
    assert value == original
    data = first.record.to_dict()
    assert data["side_effects_performed"] is False
    assert data["authorization_created"] is False
    assert first.record.record_id.startswith("cta-")
    assert first.record.contract_version == "cta-v1.0.0"


def test_mutate_without_destination_is_rejected():
    result = validate_contextual_teacher_action(payload(requested_effect="mutate", destination=None))
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-destination-required",)


def test_mutate_with_destination_is_valid():
    result = validate_contextual_teacher_action(
        payload(requested_effect="mutate", destination="manual-review")
    )
    assert result.status is ValidationStatus.VALID


def test_mutate_with_unknown_destination_is_rejected():
    result = validate_contextual_teacher_action(
        payload(requested_effect="mutate", destination="publish-to-web")
    )
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-destination-unclear",)


def test_unknown_action_is_rejected():
    result = validate_contextual_teacher_action(payload(action="summon"))
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-invalid",)


def test_unresolvable_selector_fails_closed():
    result = validate_contextual_teacher_action(
        payload(
            selection={"selection_kind": "slide", "selector": "slides:other-deck:slide-4", "verified": True}
        )
    )
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-selection-out-of-artifact",)


def test_resolvable_selector_is_valid():
    result = validate_contextual_teacher_action(
        payload(
            selection={"selection_kind": "slide", "selector": "slides:worksheet-42:slide-4", "verified": True}
        )
    )
    assert result.status is ValidationStatus.VALID
    assert result.record.to_dict()["selection"]["selection_kind"] == "slide"


def test_unverified_selector_degrades_to_whole_artifact_with_reason():
    result = validate_contextual_teacher_action(
        payload(
            selection={"selection_kind": "range", "selector": "docs:worksheet-42:chars-10-99", "verified": False}
        )
    )
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    data = result.record.to_dict()
    assert "target.selection-unverified" in data["reason_codes"]
    assert data["selection"]["selection_kind"] == "none"
    assert data["selection"]["selector"] is None


def test_selection_is_first_class_not_a_constraint():
    result = validate_contextual_teacher_action(payload())
    data = result.record.to_dict()
    assert "selection" in data
    constraint_names = {item["name"] for item in data["constraints"]}
    assert not any("selection" in name for name in constraint_names)


def test_unidentified_artifact_fails_closed():
    artifact = payload()["artifact"]
    artifact = dict(artifact, stable_id=None)
    result = validate_contextual_teacher_action(payload(artifact=artifact))
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("identity-artifact-unidentified",)


def test_analyze_response_evidence_is_unsupported_terminal():
    route = route_action(ANALYZE_RESPONSE_EVIDENCE_ACTION)
    assert route.terminal == "unsupported"
    assert route.owners == ()
    assert "manual-review" in route.notes


def test_guided_practice_requires_explicit_mapping_constraint():
    result = validate_contextual_teacher_action(payload(action=GUIDED_PRACTICE_ACTION))
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-mapping-missing",)


def test_guided_practice_with_mapping_constraint_is_valid():
    result = validate_contextual_teacher_action(
        payload(
            action=GUIDED_PRACTICE_ACTION,
            constraints=[{"name": GUIDED_PRACTICE_MAPPING_CONSTRAINT, "value": GUIDED_PRACTICE_ARTIFACT_TYPE}],
        )
    )
    assert result.status is ValidationStatus.VALID
    route = route_action(GUIDED_PRACTICE_ACTION)
    assert route.capability_reference == "Instructional Materials Coach (guided-notes)"


def test_guided_practice_wrong_mapping_value_is_rejected():
    result = validate_contextual_teacher_action(
        payload(
            action=GUIDED_PRACTICE_ACTION,
            constraints=[{"name": GUIDED_PRACTICE_MAPPING_CONSTRAINT, "value": "guided-practice"}],
        )
    )
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-mapping-missing",)


def test_routing_matrix_covers_all_actions_and_is_prose_anchored():
    assert {route.action for route in ROUTING_MATRIX} == EXPECTED_ACTIONS
    for route in ROUTING_MATRIX:
        assert route.anchor == "prose"
        assert route.terminal in {"route", "unsupported"}


def test_route_action_rejects_unknown_action():
    with pytest.raises(Exception):
        route_action("summon")


def test_unknown_supplied_reason_code_is_rejected():
    result = validate_contextual_teacher_action(payload(reason_codes=["made.up"]))
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-invalid",)


def test_supplied_governed_reason_codes_are_preserved():
    result = validate_contextual_teacher_action(payload(reason_codes=["context.stale"]))
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert "context.stale" in result.record.to_dict()["reason_codes"]


def test_schema_name_mismatch_is_rejected():
    result = validate_contextual_teacher_action(payload(schema_name="request-interpretation"))
    assert result.status is ValidationStatus.INVALID


def test_contract_version_mismatch_is_rejected():
    result = validate_contextual_teacher_action(payload(contract_version="cta-v0.1.0-draft"))
    assert result.status is ValidationStatus.INVALID


def test_no_1891_lineage_in_module():
    from pathlib import Path

    module = Path("src/instructional_workflow_contracts/contextual_teacher_action.py")
    assert "1891" not in module.read_text()
