"""Tests for the ANI1 assessment -> next-instruction contract (#1891).

All evidence is synthetic.  No real student data, no network, no I/O.
"""

import pytest

from instructional_workflow_contracts.assessment_next_instruction import (
    CONTRACT_ID,
    analyze_assessment_next_instruction,
)
from instructional_workflow_contracts.common import ValidationStatus


def _targets():
    return [
        {"target_ref": "frac-add", "label": "Add fractions with unlike denominators"},
        {"target_ref": "frac-equiv", "label": "Recognize equivalent fractions"},
    ]


def _base_evidence(**overrides):
    evidence = {
        "contract_version": CONTRACT_ID,
        "analysis_id": "ani-2026-10-01-synth-001",
        "record_revision": 1,
        "evidence_source": "teacher-class-summary",
        "review_state": "reviewed",
        "privacy_disposition": "eligible",
        "blueprint_identity": {
            "blueprint_id": "bp-fractions-unit-3",
            "blueprint_version": "1.2.0",
        },
        "targets": _targets(),
        "observations": [
            {
                "observation_id": "obs-1",
                "bound_target_ref": "frac-add",
                "scope": "class",
                "evidence_kind": "direct",
                "strength": "strong",
                "observed": "Most work shows correct common-denominator procedure but wrong final sums",
            },
            {
                "observation_id": "obs-2",
                "bound_target_ref": "frac-equiv",
                "scope": "class",
                "evidence_kind": "direct",
                "strength": "moderate",
                "observed": "Equivalent-fraction items answered correctly at a steady rate",
            },
        ],
        "hypotheses": [
            {
                "hypothesis_id": "hyp-1",
                "kind": "misconception",
                "bound_target_ref": "frac-add",
                "supporting_observation_ids": ["obs-1"],
                "evidence_strength": "moderate",
                "limitations": "Procedure errors were inferred from written work, not confirmed in interviews",
            }
        ],
        "options": [
            {
                "option_id": "opt-1",
                "kind": "reteach-bounded",
                "bound_target_refs": ["frac-add"],
                "supporting_hypothesis_ids": ["hyp-1"],
                "consequential": False,
                "description": "Revisit common-denominator procedure with worked examples",
            },
            {
                "option_id": "opt-2",
                "kind": "sequence-change",
                "bound_target_refs": ["frac-add", "frac-equiv"],
                "supporting_hypothesis_ids": ["hyp-1"],
                "consequential": True,
                "description": "Move fraction addition later in the unit sequence",
            },
        ],
    }
    evidence.update(overrides)
    return evidence


def _payload(result):
    assert result.status is ValidationStatus.VALID, result.details
    return result.record.to_dict()


def test_valid_teacher_summary_keeps_evidence_inference_and_options_separate():
    result = analyze_assessment_next_instruction(_base_evidence())
    payload = _payload(result)
    assert payload["contract_version"] == CONTRACT_ID
    assert payload["analysis_id"] == "ani-2026-10-01-synth-001"
    assert len(payload["observed_evidence"]) == 2
    assert len(payload["inference_hypotheses"]) == 1
    assert len(payload["instructional_options"]) == 2
    # Hypotheses stay labeled as hypotheses with explicit limitations.
    hypothesis = payload["inference_hypotheses"][0]
    assert hypothesis["kind"] == "misconception"
    assert hypothesis["limitations"]
    # Non-consequential option needs no teacher decision; consequential does.
    by_id = {o["option_id"]: o for o in payload["instructional_options"]}
    assert by_id["opt-1"]["teacher_decision_required"] is False
    assert by_id["opt-2"]["teacher_decision_required"] is True
    assert payload["teacher_decision_required"] is True
    assert payload["classification"] == "sufficient-evidence"
    assert payload["routing"] == "proceed-to-owner-review"
    # Deterministic owner routing from option kinds.
    assert payload["recommended_next_owner"] == "teacher-modeling-coach"
    # All authority is permanently false on the record and the result.
    for key, value in payload["authority"].items():
        assert value is False, key
    authority = result.authority
    assert authority.execution_authorized is False
    assert authority.external_write_authorized is False
    assert authority.production_authorized is False
    assert authority.publication_authorized is False


def test_deterministic_fingerprint_across_runs():
    first = analyze_assessment_next_instruction(_base_evidence())
    second = analyze_assessment_next_instruction(_base_evidence())
    assert first.status is ValidationStatus.VALID
    assert second.status is ValidationStatus.VALID
    assert first.record.fingerprint == second.record.fingerprint
    assert first.record.to_dict() == second.record.to_dict()


def test_normalized_evidence_intake_source_is_admitted():
    payload = _payload(
        analyze_assessment_next_instruction(
            _base_evidence(evidence_source="normalized-evidence-intake")
        )
    )
    assert payload["evidence_source"] == "normalized-evidence-intake"


def test_not_reviewed_evidence_is_rejected():
    result = analyze_assessment_next_instruction(
        _base_evidence(review_state="not-reviewed")
    )
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("source-invalid",)


def test_privacy_ineligible_routes_to_explicit_hold():
    result = analyze_assessment_next_instruction(
        _base_evidence(privacy_disposition="restricted")
    )
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.reason_codes == ("manual-review-privacy-ineligible",)
    payload = result.record.to_dict()
    assert payload["classification"] == "insufficient-evidence"
    assert payload["routing"] == "hold"
    assert payload["manual_review_required"] is True
    assert payload["instructional_options"] == []
    assert payload["recommended_next_owner"] == "manual-review"


def test_empty_observations_fail_closed_to_hold_without_options():
    result = analyze_assessment_next_instruction(
        _base_evidence(observations=[], hypotheses=[], options=[])
    )
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.reason_codes == ("manual-review-insufficient-evidence",)
    payload = result.record.to_dict()
    assert payload["instructional_options"] == []


def test_all_insufficient_observations_fail_closed_to_hold():
    evidence = _base_evidence(
        observations=[
            {
                "observation_id": "obs-1",
                "bound_target_ref": "frac-add",
                "scope": "class",
                "evidence_kind": "partial",
                "strength": "insufficient",
                "observed": "Too few items were completed to say anything",
            }
        ],
        hypotheses=[],
        options=[],
    )
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.record.to_dict()["classification"] == "insufficient-evidence"


def test_options_are_rejected_when_evidence_is_insufficient():
    evidence = _base_evidence(
        observations=[],
        hypotheses=[],
        options=[
            {
                "option_id": "opt-1",
                "kind": "reteach-bounded",
                "bound_target_refs": ["frac-add"],
                "supporting_hypothesis_ids": [],
                "consequential": False,
                "description": "Should never be admitted",
            }
        ],
    )
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-invalid",)


def test_non_class_scoped_observation_is_rejected():
    evidence = _base_evidence()
    evidence["observations"][0]["scope"] = "learner"
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("source-invalid",)


def test_uncertain_evidence_cannot_carry_stronger_strength():
    evidence = _base_evidence()
    evidence["observations"][0]["evidence_kind"] = "uncertain"
    evidence["observations"][0]["strength"] = "moderate"
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("quality-invalid",)


def test_hypothesis_cannot_exceed_supporting_observation_strength():
    evidence = _base_evidence()
    evidence["observations"][0]["strength"] = "weak"
    evidence["hypotheses"][0]["evidence_strength"] = "moderate"
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("quality-invalid",)


def test_hypothesis_must_state_limitations():
    evidence = _base_evidence()
    evidence["hypotheses"][0]["limitations"] = "   "
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("quality-invalid",)


def test_hypothesis_binding_to_unknown_target_is_rejected():
    evidence = _base_evidence()
    evidence["hypotheses"][0]["bound_target_ref"] = "not-a-target"
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("source-invalid",)


def test_option_on_insufficient_strength_hypothesis_is_rejected():
    evidence = _base_evidence(
        observations=[
            {
                "observation_id": "obs-1",
                "bound_target_ref": "frac-add",
                "scope": "class",
                "evidence_kind": "partial",
                "strength": "insufficient",
                "observed": "Sparse evidence only",
            }
        ],
        hypotheses=[
            {
                "hypothesis_id": "hyp-1",
                "kind": "prerequisite-gap",
                "bound_target_ref": "frac-add",
                "supporting_observation_ids": ["obs-1"],
                "evidence_strength": "insufficient",
                "limitations": "Evidence is too sparse to act on",
            }
        ],
    )
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("quality-invalid",)


def test_option_binding_to_unknown_target_is_rejected():
    evidence = _base_evidence()
    evidence["options"][0]["bound_target_refs"] = ["frac-add", "not-a-target"]
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("source-invalid",)


def test_option_referencing_unknown_hypothesis_is_rejected():
    evidence = _base_evidence()
    evidence["options"][0]["supporting_hypothesis_ids"] = ["hyp-999"]
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("source-invalid",)


def test_weak_evidence_flags_manual_review_on_valid_record():
    evidence = _base_evidence()
    evidence["observations"][1]["strength"] = "weak"
    payload = _payload(analyze_assessment_next_instruction(evidence))
    assert payload["manual_review_required"] is True
    assert "manual-review-weak-evidence-present" in payload["unresolved_uncertainties"]


def test_manual_review_option_routes_to_manual_review():
    evidence = _base_evidence(
        options=[
            {
                "option_id": "opt-1",
                "kind": "manual-review",
                "bound_target_refs": ["frac-add"],
                "supporting_hypothesis_ids": ["hyp-1"],
                "consequential": True,
                "description": "Teacher reviews the class work directly",
            }
        ]
    )
    payload = _payload(analyze_assessment_next_instruction(evidence))
    assert payload["recommended_next_owner"] == "manual-review"


def test_wrong_contract_version_is_rejected():
    result = analyze_assessment_next_instruction(
        _base_evidence(contract_version="assessment-next-instruction-v0")
    )
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-version-unsupported",)


def test_unknown_field_is_rejected():
    evidence = _base_evidence()
    evidence["extra_field"] = "not-admitted"
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-unknown-field",)


def test_non_object_intake_is_rejected():
    result = analyze_assessment_next_instruction(["not", "an", "object"])
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-wrong-type",)


def test_oversized_intake_is_rejected():
    evidence = _base_evidence()
    evidence["observations"][0]["observed"] = "x" * (70 * 1024)
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-oversized",)


def test_duplicate_observation_ids_are_rejected():
    evidence = _base_evidence()
    evidence["observations"].append(dict(evidence["observations"][0]))
    result = analyze_assessment_next_instruction(evidence)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("identity-invalid",)


def test_empty_targets_are_rejected():
    result = analyze_assessment_next_instruction(_base_evidence(targets=[]))
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-invalid",)
