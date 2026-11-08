import json
from pathlib import Path

from src.instructional_workflow_contracts.assessment_experiment_evidence import (
    adapt_assessment_experiment_evidence,
)
from src.instructional_workflow_contracts.common import ValidationStatus

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/assessment_blueprint"
POSITIVE_PATH = "tests/fixtures/assessment_blueprint/cross-unit-portability-positive.json"
NEGATIVE_PATH = "tests/fixtures/assessment_blueprint/cross-unit-portability-negative.json"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_positive_846_fixtures_map_without_assessment_fields_in_shared_record():
    for fixture in load("cross-unit-portability-positive.json"):
        result = adapt_assessment_experiment_evidence(
            fixture,
            fixture_path=POSITIVE_PATH,
            availability="measured",
            value=True,
        )
        assert result.status is ValidationStatus.VALID, fixture["case"]
        payload = result.record.to_dict()
        assert payload["value"] is True
        assert payload["metric_id"] == "assessment-portability-observation"
        assert payload["references"][0]["stable_id"] == fixture["synthetic_target_id"]
        for assessment_field in (
            "domain",
            "claim",
            "selected_method",
            "qa_expectation",
            "workspace_expectation",
            "expected",
        ):
            assert assessment_field not in payload
        assert payload["execution_authorized"] is False
        assert payload["external_write_authorized"] is False
        assert payload["production_authorized"] is False
        assert payload["publication_authorized"] is False


def test_negative_846_fixtures_are_referenceable_without_reimplementing_semantics():
    for fixture in load("cross-unit-portability-negative.json"):
        result = adapt_assessment_experiment_evidence(
            fixture,
            fixture_path=NEGATIVE_PATH,
            availability="measured",
            value=False,
        )
        assert result.status is ValidationStatus.VALID, fixture["case"]
        payload = result.record.to_dict()
        assert payload["value"] is False
        assert payload["observation_id"] == fixture["case"]
        assert payload["references"][0]["verification_evidence"] == fixture["case"]


def test_unavailable_and_lane_unavailable_remain_distinct_without_imputation():
    fixture = load("cross-unit-portability-positive.json")[0]
    unavailable = adapt_assessment_experiment_evidence(
        fixture,
        fixture_path=POSITIVE_PATH,
        availability="unavailable",
        value=None,
    )
    lane_unavailable = adapt_assessment_experiment_evidence(
        fixture,
        fixture_path=POSITIVE_PATH,
        availability="lane-unavailable",
        value=None,
    )
    assert unavailable.status is ValidationStatus.VALID
    assert lane_unavailable.status is ValidationStatus.VALID
    assert unavailable.record.to_dict()["availability"] == "unavailable"
    assert lane_unavailable.record.to_dict()["availability"] == "lane-unavailable"
    assert unavailable.record.to_dict()["value"] is None
    assert lane_unavailable.record.to_dict()["value"] is None


def test_adapter_rejects_non_synthetic_evidence_with_existing_generic_reason():
    fixture = dict(load("cross-unit-portability-positive.json")[0])
    fixture["synthetic_noncanonical"] = False
    result = adapt_assessment_experiment_evidence(
        fixture,
        fixture_path=POSITIVE_PATH,
        availability="measured",
        value=True,
    )
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("source-invalid",)


def test_shared_experiment_contract_remains_unchanged_by_adapter():
    source = (
        ROOT / "src/instructional_workflow_contracts/experiment_evidence.py"
    ).read_text()
    for assessment_specific in (
        "synthetic_noncanonical",
        "selected_method",
        "qa_expectation",
        "workspace_expectation",
        "assessment-portability-observation",
    ):
        assert assessment_specific not in source
