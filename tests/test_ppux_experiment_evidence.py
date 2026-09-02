from pathlib import Path

from src.instructional_workflow_contracts.common import ValidationStatus
from src.instructional_workflow_contracts.ppux_experiment_evidence import (
    adapt_ppux_experiment_evidence,
)

ROOT = Path(__file__).resolve().parents[1]


def single_frame(**overrides):
    value = {
        "status": "evaluated",
        "provider": "provider-a",
        "model": "model-a",
        "prompt_strategy": None,
        "instructional_state": "pass",
        "interface_fidelity": "warn",
        "artifact_state_fidelity": "pass",
        "negative_constraints": "fail",
        "execution_completion": "pass",
        "reasons": ["ui-drift"],
        "generated_output_is_source_evidence": False,
    }
    value.update(overrides)
    return value


def sequence(**overrides):
    value = {"status": "fail", "reasons": ["sequence-ui-drift"], "singleFrameFindings": []}
    value.update(overrides)
    return value


def adapt(record, *, kind="single-frame", metric="interface-fidelity", availability="measured"):
    return adapt_ppux_experiment_evidence(
        record,
        evidence_kind=kind,
        metric_id=metric,
        run_id="tutorial-3-provider-a",
        observation_id=f"tutorial-3-{metric}",
        evidence_location="08_Tooling/instructional-materials-coach/picture-perfect-coach/src/fidelityEvaluation.ts",
        availability=availability,
    )


def test_single_frame_dimensions_remain_separate_observations():
    interface = adapt(single_frame(), metric="interface-fidelity")
    instructional = adapt(single_frame(), metric="instructional-state-fidelity")
    negative = adapt(single_frame(), metric="negative-constraint-compliance")
    assert interface.status is ValidationStatus.VALID
    assert instructional.status is ValidationStatus.VALID
    assert negative.status is ValidationStatus.VALID
    assert interface.record.to_dict()["value"] == "warn"
    assert instructional.record.to_dict()["value"] == "pass"
    assert negative.record.to_dict()["value"] == "fail"


def test_provider_and_model_are_provenance_not_shared_schema_fields():
    result = adapt(single_frame())
    payload = result.record.to_dict()
    assert "provider" not in payload
    assert "model" not in payload
    assert payload["references"][0]["verification_evidence"] == "provider=provider-a;model=model-a"


def test_identical_evidence_is_deterministic():
    first = adapt(single_frame())
    second = adapt(single_frame())
    assert first.record.fingerprint == second.record.fingerprint
    assert first.record.to_dict() == second.record.to_dict()


def test_unavailable_and_lane_unavailable_are_not_imputed():
    unavailable = adapt(single_frame(status="manual-review-required"), availability="unavailable")
    lane = adapt(single_frame(status="manual-review-required"), availability="lane-unavailable")
    assert unavailable.status is ValidationStatus.VALID
    assert lane.status is ValidationStatus.VALID
    assert unavailable.record.to_dict()["value"] is None
    assert lane.record.to_dict()["value"] is None
    assert unavailable.record.to_dict()["availability"] == "unavailable"
    assert lane.record.to_dict()["availability"] == "lane-unavailable"


def test_manual_review_is_not_invented_into_a_measurement():
    result = adapt(single_frame(status="manual-review-required"))
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-manual-review",)


def test_sequence_evidence_stays_distinct_from_single_frame_evidence():
    result = adapt(
        sequence(),
        kind="sequence",
        metric="cross-frame-sequence-fidelity",
    )
    assert result.status is ValidationStatus.VALID
    payload = result.record.to_dict()
    assert payload["metric_id"] == "cross-frame-sequence-fidelity"
    assert payload["value"] == "fail"


def test_malformed_or_unsupported_ppux_evidence_fails_closed():
    assert adapt([], metric="interface-fidelity").status is ValidationStatus.INVALID
    unsupported = adapt(single_frame(), metric="composite-quality-score")
    assert unsupported.status is ValidationStatus.INVALID


def test_shared_experiment_contract_remains_free_of_ppux_fields():
    source = (ROOT / "src/instructional_workflow_contracts/experiment_evidence.py").read_text()
    for ppux_specific in (
        "instructional_state",
        "interface_fidelity",
        "negative_constraints",
        "cross-frame-sequence-fidelity",
        "provider",
        "model",
    ):
        assert ppux_specific not in source


def test_adapter_outputs_remain_non_authorizing():
    result = adapt(single_frame())
    payload = result.record.to_dict()
    assert payload["execution_authorized"] is False
    assert payload["external_write_authorized"] is False
    assert payload["production_authorized"] is False
    assert payload["publication_authorized"] is False
