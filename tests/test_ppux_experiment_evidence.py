from pathlib import Path

from src.instructional_workflow_contracts.common import ValidationStatus
from src.instructional_workflow_contracts.ppux_experiment_evidence import (
    adapt_ppux_experiment_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_LOCATION = (
    "08_Tooling/instructional-materials-coach/picture-perfect-coach/"
    "src/fidelityEvaluation.ts"
)


def ppux_result(**overrides):
    value = {
        "status": "evaluated",
        "provider": "gemini",
        "model": "flash",
        "prompt_strategy": "constraint-first",
        "instructional_state": "pass",
        "interface_fidelity": "warn",
        "artifact_state_fidelity": "warn",
        "negative_constraints": "fail",
        "execution_completion": "pass",
        "reasons": ["invented red annotation", "UI reconstruction"],
        "generated_output_is_source_evidence": False,
    }
    value.update(overrides)
    return value


def adapt(record, metric_id, *, availability="measured"):
    return adapt_ppux_experiment_evidence(
        record,
        run_id="tinkercad-step-1-gemini-flash",
        observation_id=f"step-1-{metric_id}",
        metric_id=metric_id,
        source_location=SOURCE_LOCATION,
        availability=availability,
    )


def test_single_frame_dimension_maps_without_ppux_fields_in_shared_record():
    result = adapt(ppux_result(), "interface-fidelity")
    assert result.status is ValidationStatus.VALID
    payload = result.record.to_dict()
    assert payload["metric_id"] == "interface-fidelity"
    assert payload["value"] == "warn"
    for ppux_field in (
        "provider",
        "model",
        "prompt_strategy",
        "instructional_state",
        "interface_fidelity",
        "negative_constraints",
        "generated_output_is_source_evidence",
    ):
        assert ppux_field not in payload
    assert payload["execution_authorized"] is False
    assert payload["external_write_authorized"] is False
    assert payload["production_authorized"] is False
    assert payload["publication_authorized"] is False


def test_dimensions_remain_separate_and_negative_failure_does_not_collapse_score():
    record = ppux_result()
    instructional = adapt(record, "instructional-state-fidelity")
    interface = adapt(record, "interface-fidelity")
    negative = adapt(record, "negative-constraint-compliance")
    assert instructional.record.to_dict()["value"] == "pass"
    assert interface.record.to_dict()["value"] == "warn"
    assert negative.record.to_dict()["value"] == "fail"
    assert len({item.record.record_id for item in (instructional, interface, negative)}) == 3


def test_provider_model_are_bounded_reference_provenance_only():
    result = adapt(ppux_result(), "instructional-state-fidelity")
    reference = result.record.to_dict()["references"][0]
    assert reference["stable_id"] == "issue-1542"
    assert "gemini" in reference["verification_evidence"]
    assert "flash" in reference["verification_evidence"]
    assert "provider" not in result.record.to_dict()
    assert "model" not in result.record.to_dict()


def test_identical_ppux_evidence_has_deterministic_fingerprint():
    first = adapt(ppux_result(), "artifact-state-fidelity")
    second = adapt(ppux_result(reasons=["UI reconstruction", "invented red annotation"]), "artifact-state-fidelity")
    assert first.status is ValidationStatus.VALID
    assert second.status is ValidationStatus.VALID
    assert first.record.fingerprint == second.record.fingerprint
    assert first.record.to_dict() == second.record.to_dict()


def test_unavailable_and_lane_unavailable_remain_distinct_without_imputation():
    record = ppux_result()
    unavailable = adapt(record, "interface-fidelity", availability="unavailable")
    lane_unavailable = adapt(record, "interface-fidelity", availability="lane-unavailable")
    assert unavailable.status is ValidationStatus.VALID
    assert lane_unavailable.status is ValidationStatus.VALID
    assert unavailable.record.to_dict()["value"] is None
    assert lane_unavailable.record.to_dict()["value"] is None
    assert unavailable.record.to_dict()["availability"] == "unavailable"
    assert lane_unavailable.record.to_dict()["availability"] == "lane-unavailable"


def test_manual_review_is_preserved_as_categorical_evidence():
    result = adapt(
        ppux_result(status="manual-review-required", interface_fidelity="manual-review"),
        "interface-fidelity",
    )
    assert result.status is ValidationStatus.VALID
    assert result.record.to_dict()["value"] == "manual-review"
    assert "manual-review-required" in result.record.to_dict()["references"][0]["verification_evidence"]


def test_generated_output_cannot_be_promoted_to_source_evidence():
    result = adapt(
        ppux_result(generated_output_is_source_evidence=True),
        "interface-fidelity",
    )
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("source-invalid",)


def test_malformed_or_unsupported_ppux_evidence_fails_closed():
    malformed = ppux_result(interface_fidelity="excellent")
    result = adapt(malformed, "interface-fidelity")
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-invalid",)

    unsupported = adapt(ppux_result(), "composite-image-quality")
    assert unsupported.status is ValidationStatus.INVALID
    assert unsupported.reason_codes == ("handoff-invalid",)


def test_shared_experiment_contract_remains_free_of_ppux_specific_fields():
    source = (ROOT / "src/instructional_workflow_contracts/experiment_evidence.py").read_text()
    for ppux_specific in (
        "instructional_state",
        "interface_fidelity",
        "artifact_state_fidelity",
        "negative_constraints",
        "execution_completion",
        "ppux-fidelity-evaluation",
        "prompt_strategy",
    ):
        assert ppux_specific not in source
