from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from scripts import agent_os_rc6_technical_pilot as pilot

RUNNER_ROOT = Path(__file__).resolve().parents[2]
BASELINE_ROOT = Path(os.environ.get("RC6_BASELINE_ROOT", RUNNER_ROOT)).resolve()
FIXTURE = RUNNER_ROOT / "tests/fixtures/rc6_technical_pilot/frozen_package.json"


def _package():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_is_exact_ordered_frozen_package():
    package = pilot.load_frozen_package(FIXTURE)
    assert package["package_version"] == "RC6-TF-1.0"
    assert package["frozen_sha"] == pilot.FROZEN_SHA
    assert [case["case_id"] for case in package["cases"]] == list(pilot.EXPECTED_IDS)
    assert len(package["cases"]) == 24


def test_fixture_contains_no_actual_result_fields():
    package = _package()

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert not key.startswith("actual_")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(package)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "reordered"])
def test_fixture_rejects_case_identity_drift(mutation):
    package = copy.deepcopy(_package())
    if mutation == "missing":
        package["cases"].pop()
    elif mutation == "extra":
        package["cases"].append(copy.deepcopy(package["cases"][-1]))
        package["cases"][-1]["case_id"] = "T25"
    elif mutation == "duplicate":
        package["cases"][-1]["case_id"] = "T23"
    else:
        package["cases"][0], package["cases"][1] = package["cases"][1], package["cases"][0]
    with pytest.raises(pilot.PilotContractError, match="case IDs"):
        pilot.validate_frozen_package(package)


def test_fixture_rejects_actual_field_injection():
    package = copy.deepcopy(_package())
    package["cases"][0]["actual_rc5_render"] = "prepopulated"
    with pytest.raises(pilot.PilotContractError, match="actual-result field"):
        pilot.validate_frozen_package(package)


def test_threshold_denominators_are_frozen():
    package = pilot.load_frozen_package(FIXTURE)
    thresholds = package["thresholds"]
    assert thresholds["false_negative"]["denominator"] == ["T01", "T21", "T22", "T23", "T24"]
    assert thresholds["unexpected_manual_review"]["denominator"] == ["T01", "T21", "T22", "T23", "T24"]
    assert thresholds["silent_automatic_selection"]["denominator"] == ["T05"]
    assert thresholds["contradicted_evidence_positive"]["denominator"] == ["T12"]
    assert thresholds["missing_active_path_positive"]["denominator"] == ["T15"]
    assert thresholds["active_exemptions_reviewed"]["denominator"] == ["T13"]


def test_runner_executes_all_cases_twice_and_passes_frozen_contract():
    result = pilot.run_pilot(FIXTURE, BASELINE_ROOT, pilot.FROZEN_SHA, verify_head=False)
    assert result.exit_code == 0
    assert result.payload["summary"] == {
        "result": "pass",
        "total_cases": 24,
        "passed_cases": 24,
        "failed_cases": 0,
        "deterministic_cases": 24,
        "thresholds_passed": True,
    }
    assert all(case["actual"]["repeat_output_digest_1"] == case["actual"]["repeat_output_digest_2"] for case in result.payload["cases"])
    assert json.loads(result.json_text) == result.payload
    assert "This report is evidence only" in result.markdown_text


def test_wrong_sha_fails_closed_before_execution():
    package = pilot.load_frozen_package(FIXTURE)
    api = pilot._load_interfaces(BASELINE_ROOT)
    with pytest.raises(pilot.PilotContractError, match="tested SHA"):
        pilot.verify_frozen_baseline(BASELINE_ROOT, package, "0" * 40, api, verify_head=False)


def test_cli_contract_error_exit_code(monkeypatch, tmp_path):
    code = pilot.main(
        [
            "--fixture",
            str(FIXTURE),
            "--repository-root",
            str(BASELINE_ROOT),
            "--tested-sha",
            "0" * 40,
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert code == 2
    assert not list(tmp_path.iterdir())
