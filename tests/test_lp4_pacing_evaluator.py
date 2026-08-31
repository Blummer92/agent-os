from __future__ import annotations

from copy import deepcopy

from instructional_pacing import DIMENSIONS, NON_AUTHORITY_FIELDS, evaluate_lesson_pacing
from instructional_workflow_contracts import ValidationStatus


def _packet() -> dict:
    diagnosis = {
        name: {"level": "moderate", "evidence_refs": [f"evidence/{index}"], "uncertainty": "low"}
        for index, name in enumerate(DIMENSIONS, start=1)
    }
    diagnosis["operational_load"]["level"] = "high"
    return {
        "contract_version": "1.0",
        "record_id": "lp4/test-case",
        "record_revision": 1,
        "objective_ref": "objective/composition",
        "success_criteria_ref": "criteria/composition",
        "period_minutes": 55,
        "operational_minutes": 7,
        "instructional_functions": [
            {"name": "model", "protected": True, "lower_minutes": 5, "expected_minutes": 7, "upper_minutes": 9},
            {"name": "practice", "protected": True, "lower_minutes": 18, "expected_minutes": 22, "upper_minutes": 28},
            {"name": "feedback-revision", "protected": True, "lower_minutes": 8, "expected_minutes": 10, "upper_minutes": 12},
        ],
        "evidence_sources": [{"kind": "teacher-entered-summary"}],
        "prior_runs": [
            {"run_id": "run/1", "objective_ref": "objective/composition", "work_mode": "camera", "quality": "usable", "active_minutes": 39, "elapsed_minutes": 50, "context_ref": "context/a"},
            {"run_id": "run/2", "objective_ref": "objective/composition", "work_mode": "camera", "quality": "usable", "active_minutes": 43, "elapsed_minutes": 52, "context_ref": "context/b"},
            {"run_id": "run/3", "objective_ref": "objective/other", "work_mode": "camera", "quality": "usable", "active_minutes": 20, "elapsed_minutes": 40, "context_ref": "context/c"},
        ],
        "observation_quality": {"status": "usable"},
        "privacy_disposition": "eligible",
        "demand_profile": diagnosis,
        "implementation_stage": "teacher-advisory",
        "continuation_allowed": True,
        "work_mode": "camera",
    }


def _payload(result):
    assert result.record is not None
    return result.record.to_dict()


def test_valid_evaluation_is_deterministic_and_report_only() -> None:
    first = evaluate_lesson_pacing(_packet())
    second = evaluate_lesson_pacing(deepcopy(_packet()))
    assert first.status is ValidationStatus.VALID
    assert first.record is not None and second.record is not None
    assert first.record.fingerprint == second.record.fingerprint
    payload = _payload(first)
    for key, value in NON_AUTHORITY_FIELDS.items():
        assert payload[key] is value
    assert tuple(payload["difficulty_diagnosis"]) == tuple(sorted(DIMENSIONS))
    assert "operational_load" in payload["primary_time_drivers"]


def test_noncomparable_run_is_excluded_not_silently_used() -> None:
    payload = _payload(evaluate_lesson_pacing(_packet()))
    assert payload["evidence_summary"]["included_count"] == 2
    assert payload["evidence_summary"]["excluded_count"] == 1
    assert payload["evidence_summary"]["excluded"][0]["reason"] == "lp-evidence-objective-match-weak"


def test_unusable_observation_fails_closed_to_hold() -> None:
    packet = _packet()
    packet["observation_quality"] = {"status": "unusable"}
    payload = _payload(evaluate_lesson_pacing(packet))
    assert payload["advisory_assessment_outcome"] == "insufficient-evidence"
    assert payload["routing_recommendation"] == "hold"
    assert payload["manual_review_required"] is True


def test_privacy_blocked_evidence_never_advances() -> None:
    packet = _packet()
    packet["privacy_disposition"] = "blocked"
    payload = _payload(evaluate_lesson_pacing(packet))
    assert payload["routing_recommendation"] == "hold"
    assert payload["external_write_authorized"] is False
    assert payload["student_classification_authorized"] is False


def test_suspended_revision_fails_closed() -> None:
    packet = _packet()
    packet["implementation_stage"] = "suspended"
    payload = _payload(evaluate_lesson_pacing(packet))
    assert payload["advisory_assessment_outcome"] == "insufficient-evidence"
    assert payload["confidence"] == "low"


def test_high_uncertainty_never_promotes_confidence_from_record_count() -> None:
    packet = _packet()
    packet["demand_profile"]["evidence_uncertainty"] = {
        "level": "high",
        "evidence_refs": ["evidence/uncertain"],
        "uncertainty": "high",
    }
    for index in range(4, 12):
        packet["prior_runs"].append(
            {"run_id": f"run/{index}", "objective_ref": "objective/composition", "work_mode": "camera", "quality": "usable", "active_minutes": 40, "elapsed_minutes": 50, "context_ref": f"context/{index}"}
        )
    payload = _payload(evaluate_lesson_pacing(packet))
    assert payload["confidence"] == "low"
    assert payload["routing_recommendation"] == "hold"


def test_active_time_cannot_exceed_elapsed_time() -> None:
    packet = _packet()
    packet["prior_runs"][0]["active_minutes"] = 60
    payload = _payload(evaluate_lesson_pacing(packet))
    assert payload["evidence_summary"]["excluded"][0]["reason"] == "lp-evidence-run-interrupted-or-sparse"


def test_six_dimensions_are_required_and_never_collapsed() -> None:
    packet = _packet()
    del packet["demand_profile"]["language_and_representation_load"]
    result = evaluate_lesson_pacing(packet)
    assert result.status is ValidationStatus.INVALID
    assert result.record is None


def test_unknown_fields_and_authority_injection_fail_closed() -> None:
    packet = _packet()
    packet["production_authorized"] = True
    result = evaluate_lesson_pacing(packet)
    assert result.status is ValidationStatus.INVALID
    assert result.record is None


def test_shadow_mode_cannot_claim_high_confidence() -> None:
    packet = _packet()
    packet["implementation_stage"] = "shadow-mode"
    payload = _payload(evaluate_lesson_pacing(packet))
    assert payload["confidence"] == "low"


def test_evaluator_uses_no_learner_vector_or_similarity_score_fields() -> None:
    payload = _payload(evaluate_lesson_pacing(_packet()))
    serialized = repr(payload).lower()
    for forbidden in ("cosine", "euclidean", "manhattan", "mahalanobis", "embedding", "learner_score", "ability_score"):
        assert forbidden not in serialized
