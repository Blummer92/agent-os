from __future__ import annotations

from copy import deepcopy

from instructional_pacing import DIMENSIONS, NON_AUTHORITY_FIELDS, evaluate_lesson_pacing
from instructional_workflow_contracts import ValidationStatus


def _packet() -> dict:
    diagnosis = {
        name: {"level": "moderate", "evidence_refs": [f"evidence/{index}"], "uncertainty": "low"}
        for index, name in enumerate(DIMENSIONS, start=1)
    }
    return {
        "contract_version": "1.0",
        "record_id": "lp16/test-case",
        "record_revision": 1,
        "objective_ref": "objective/composition",
        "success_criteria_ref": "criteria/composition",
        "period_minutes": 50,
        "operational_minutes": 5,
        "instructional_functions": [
            {"name": "model", "protected": True, "lower_minutes": 8, "expected_minutes": 10, "upper_minutes": 12},
            {"name": "practice", "protected": True, "lower_minutes": 20, "expected_minutes": 24, "upper_minutes": 28},
            {"name": "feedback-revision", "protected": True, "lower_minutes": 10, "expected_minutes": 12, "upper_minutes": 14},
            {"name": "showcase", "protected": False, "lower_minutes": 2, "expected_minutes": 4, "upper_minutes": 5},
        ],
        "evidence_sources": [{"kind": "teacher-entered-summary"}],
        "prior_runs": [],
        "observation_quality": {"status": "usable"},
        "privacy_disposition": "eligible",
        "demand_profile": diagnosis,
        "implementation_stage": "teacher-advisory",
        "continuation_allowed": True,
        "work_mode": "camera",
    }


def _payload(packet: dict) -> dict:
    result = evaluate_lesson_pacing(packet)
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    return result.record.to_dict()


def _candidate_packet() -> dict:
    packet = _packet()
    packet["adaptations"] = {
        "operational_friction": [{"id": "setup-friction", "minutes_saved": 3}],
        "extraneous_material": [{"id": "extra-demo", "minutes_saved": 2}],
        "transitions": [{"id": "duplicate-transition", "minutes_saved": 1}],
        "repetitions": [
            {"id": "practice-repeat", "function_name": "practice", "minutes_saved": 2, "preserves_function": True}
        ],
        "evidence_formats": [
            {
                "id": "exit-format",
                "function_name": "feedback-revision",
                "minutes_saved": 2,
                "from_format": "uploaded-reflection",
                "to_format": "verbal-check",
                "preserves_objective": True,
                "preserves_success_criteria": True,
                "preserves_accessibility": True,
            }
        ],
        "optional_polish": [{"id": "showcase-defer", "function_name": "showcase", "minutes_saved": 4}],
    }
    return packet


def test_fitting_lesson_does_not_invent_adaptation() -> None:
    packet = _packet()
    packet["period_minutes"] = 70
    payload = _payload(packet)
    assert payload["advisory_assessment_outcome"] == "fits"
    assert payload["compressed_instances"] == []
    assert payload["changed_formats"] == []
    assert payload["deferred_functions"] == []
    assert payload["split_plan"] is None


def test_adaptation_hierarchy_selects_earlier_steps_first() -> None:
    payload = _payload(_candidate_packet())
    assert [item["id"] for item in payload["compressed_instances"]] == ["setup-friction", "extra-demo"]
    assert payload["changed_formats"] == []
    assert payload["deferred_functions"] == []
    assert payload["adapted_range"]["expected"] == 45.0


def test_repetition_reduction_preserves_instructional_function() -> None:
    packet = _candidate_packet()
    packet["adaptations"]["operational_friction"] = []
    packet["adaptations"]["extraneous_material"] = []
    packet["adaptations"]["transitions"] = []
    payload = _payload(packet)
    assert payload["compressed_instances"][0]["kind"] == "repetitions"
    assert payload["compressed_instances"][0]["function_name"] == "practice"
    assert "practice" in payload["preserved_functions"]


def test_attempt_to_remove_function_fails_closed() -> None:
    packet = _candidate_packet()
    packet["adaptations"]["repetitions"][0]["preserves_function"] = False
    result = evaluate_lesson_pacing(packet)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("lp-pacing-required-function-removed",)


def test_format_change_requires_objective_success_and_accessibility_preservation() -> None:
    packet = _candidate_packet()
    packet["adaptations"]["evidence_formats"][0]["preserves_accessibility"] = False
    result = evaluate_lesson_pacing(packet)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-invalid",)


def test_protected_function_cannot_be_deferred_as_optional_polish() -> None:
    packet = _candidate_packet()
    packet["adaptations"]["optional_polish"] = [
        {"id": "bad-defer", "function_name": "feedback-revision", "minutes_saved": 4}
    ]
    result = evaluate_lesson_pacing(packet)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("lp-pacing-required-function-removed",)


def test_remaining_infeasibility_produces_explicit_split_plan() -> None:
    packet = _packet()
    packet["period_minutes"] = 40
    payload = _payload(packet)
    assert payload["advisory_assessment_outcome"] == "split-required"
    assert payload["split_plan"] is not None
    assert payload["split_plan"]["split_after"] == "practice"
    assert payload["split_plan"]["teacher_review_required"] is True


def test_no_continuation_holds_instead_of_silent_truncation() -> None:
    packet = _packet()
    packet["period_minutes"] = 40
    packet["continuation_allowed"] = False
    payload = _payload(packet)
    assert payload["advisory_assessment_outcome"] == "not-feasible"
    assert payload["routing_recommendation"] == "hold"
    assert payload["split_plan"] is None
    assert "lp-pacing-instruction-time-insufficient" in payload["unresolved_uncertainties"]


def test_high_uncertainty_never_generates_adaptation() -> None:
    packet = _candidate_packet()
    packet["demand_profile"]["evidence_uncertainty"]["level"] = "high"
    payload = _payload(packet)
    assert payload["advisory_assessment_outcome"] == "insufficient-evidence"
    assert payload["compressed_instances"] == []
    assert payload["changed_formats"] == []
    assert payload["deferred_functions"] == []


def test_teacher_decision_is_preserved_separately() -> None:
    packet = _candidate_packet()
    packet["teacher_decision"] = "continue-as-planned"
    payload = _payload(packet)
    assert payload["teacher_decision"] == "continue-as-planned"
    assert payload["routing_recommendation"] != "continue-as-planned"


def test_unknown_adaptation_section_fails_closed() -> None:
    packet = _candidate_packet()
    packet["adaptations"]["delete-modeling"] = []
    result = evaluate_lesson_pacing(packet)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-unknown-field",)


def test_duplicate_candidate_ids_fail_closed() -> None:
    packet = _candidate_packet()
    packet["adaptations"]["extraneous_material"][0]["id"] = "setup-friction"
    result = evaluate_lesson_pacing(packet)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-duplicate",)


def test_adaptation_is_deterministic_and_non_authorizing() -> None:
    first = _payload(_candidate_packet())
    second = _payload(deepcopy(_candidate_packet()))
    assert first == second
    for key, value in NON_AUTHORITY_FIELDS.items():
        assert first[key] is value
