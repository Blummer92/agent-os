from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

from instructional_workflow_contracts import ValidationStatus, validate_experiment_evidence

MODULE = Path("src/instructional_workflow_contracts/experiment_evidence.py")


def reference(stable_id: str = "source-1") -> dict[str, str]:
    return {
        "system": "github",
        "stable_id": stable_id,
        "exact_location": f"issue:{stable_id}",
        "verification_evidence": "supplied-bounded-reference",
    }


def payload(**overrides):
    value = {
        "contract_version": "experiment-evidence-v1",
        "record_revision": 1,
        "experiment_id": "exh-demo",
        "run_id": "run-1",
        "observation_id": "observation-1",
        "adapter_id": "assessment-adapter",
        "adapter_version": "v1",
        "metric_id": "retrieval-calls",
        "availability": "measured",
        "value": 0,
        "baseline_reference": None,
        "references": [reference()],
    }
    value.update(overrides)
    return value


def validated(value):
    result = validate_experiment_evidence(value)
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    return result


def test_measured_zero_is_preserved_and_distinct_from_unavailable():
    measured = validated(payload())
    assert measured.record.to_dict()["value"] == 0
    unavailable = validated(payload(availability="unavailable", value=None))
    assert unavailable.record.to_dict()["value"] is None
    assert measured.record.fingerprint != unavailable.record.fingerprint


@pytest.mark.parametrize("availability", ["unavailable", "lane-unavailable"])
def test_unavailable_states_reject_fabricated_measurement(availability):
    result = validate_experiment_evidence(payload(availability=availability, value=1))
    assert result.status is ValidationStatus.INVALID
    assert "handoff-invalid" in result.reason_codes


def test_lane_unavailable_is_valid_capability_evidence_not_zero_or_failure():
    result = validated(payload(availability="lane-unavailable", value=None))
    data = result.record.to_dict()
    assert data["availability"] == "lane-unavailable"
    assert data["value"] is None
    assert result.status is ValidationStatus.VALID


def test_measured_observation_requires_a_value():
    result = validate_experiment_evidence(payload(value=None))
    assert result.status is ValidationStatus.INVALID


def test_identity_fields_are_bounded_and_part_of_fingerprint():
    first = validated(payload())
    second = validated(payload(run_id="run-2"))
    assert first.record.fingerprint != second.record.fingerprint
    invalid = validate_experiment_evidence(payload(observation_id="bad id"))
    assert invalid.status is ValidationStatus.INVALID
    assert "identity-invalid" in invalid.reason_codes


def test_references_are_canonical_order_insensitive_and_unique():
    first = validated(payload(references=[reference("b"), reference("a")]))
    second = validated(payload(references=[reference("a"), reference("b")]))
    assert first.record.fingerprint == second.record.fingerprint
    duplicate = validate_experiment_evidence(payload(references=[reference(), reference()]))
    assert duplicate.status is ValidationStatus.INVALID
    assert "handoff-duplicate" in duplicate.reason_codes


def test_baseline_reference_is_generic_and_optional():
    result = validated(payload(baseline_reference=reference("baseline-1")))
    assert result.record.to_dict()["baseline_reference"]["stable_id"] == "baseline-1"


def test_authority_is_fixed_false_and_not_caller_overridable():
    result = validated(payload())
    data = result.record.to_dict()
    assert data["execution_authorized"] is False
    assert data["external_write_authorized"] is False
    assert data["production_authorized"] is False
    assert data["publication_authorized"] is False
    assert result.authority.execution_authorized is False
    hostile = payload()
    hostile["execution_authorized"] = True
    invalid = validate_experiment_evidence(hostile)
    assert invalid.status is ValidationStatus.INVALID
    assert "handoff-unknown-field" in invalid.reason_codes


@pytest.mark.parametrize("field", ["score", "aggregate", "p_value", "effect_size", "lifecycle"])
def test_score_aggregate_statistics_and_lifecycle_fields_are_not_accepted(field):
    hostile = payload()
    hostile[field] = 1
    result = validate_experiment_evidence(hostile)
    assert result.status is ValidationStatus.INVALID
    assert "handoff-unknown-field" in result.reason_codes


def test_value_may_be_bounded_json_without_cross_domain_interpretation():
    result = validated(payload(value={"count": 3, "observed": True}))
    assert result.record.to_dict()["value"] == {"count": 3, "observed": True}


def test_deterministic_and_input_immutable():
    value = payload(value={"b": 2, "a": 1})
    original = copy.deepcopy(value)
    first = validated(value)
    second = validated(copy.deepcopy(value))
    assert first.record.fingerprint == second.record.fingerprint
    assert value == original


def test_bounds_and_unknown_availability_fail_closed():
    oversized = validate_experiment_evidence(
        payload(references=[reference(f"source-{index}") for index in range(65)])
    )
    assert oversized.status is ValidationStatus.INVALID
    assert "handoff-oversized" in oversized.reason_codes
    unsupported = validate_experiment_evidence(payload(availability="estimated"))
    assert unsupported.status is ValidationStatus.INVALID


def test_module_has_no_forbidden_io_provider_or_student_evidence_imports():
    tree = ast.parse(MODULE.read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    forbidden = (
        "requests",
        "httpx",
        "urllib",
        "subprocess",
        "os",
        "google",
        "notion",
        "workflow_scheduler",
        "navigation_registry",
        "student_evidence_core",
    )
    assert not any(name.startswith(forbidden) for name in imports)
