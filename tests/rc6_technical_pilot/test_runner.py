from __future__ import annotations

import copy
import hashlib
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


def test_preflight_validates_frozen_boundary_without_executing_cases(monkeypatch):
    cases = [{"case_id": case_id} for case_id in pilot.EXPECTED_IDS]
    package = {"package_version": "RC6-TF-1.0", "cases": cases}
    calls = []
    api = object()

    monkeypatch.setattr(pilot, "load_package", lambda fixture: package)
    monkeypatch.setattr(pilot, "load_api", lambda root: api)
    monkeypatch.setattr(
        pilot,
        "verify_baseline",
        lambda root, value, sha, loaded_api, verify_head: calls.append(
            (root, value, sha, loaded_api, verify_head)
        ),
    )
    monkeypatch.setattr(
        pilot,
        "_once",
        lambda *args: pytest.fail("preflight must not execute a pilot case"),
    )

    result = pilot.run_preflight(FIXTURE, BASELINE_ROOT, pilot.FROZEN_SHA, verify_head=False)

    assert calls == [(BASELINE_ROOT, package, pilot.FROZEN_SHA, api, False)]
    assert result.exit_code == 0
    assert result.payload["mode"] == "preflight"
    assert result.payload["summary"] == {
        "result": "pass",
        "validated_cases": 24,
        "cases_executed": 0,
    }
    assert result.payload["authorization"]["pilot_execution"] == "not-authorized"
    assert "No T01-T24 case was executed" in result.markdown_text
    assert json.loads(result.json_text) == result.payload


def test_runner_orchestrates_two_passes_without_executing_frozen_pilot(monkeypatch):
    cases = [{"case_id": f"T{number:02d}", "title": "fixture"} for number in range(1, 25)]
    package = {"package_version": "RC6-TF-1.0", "cases": cases, "thresholds": {}}
    calls = []

    def fake_once(case, root, api):
        calls.append(case["case_id"])
        return {
            "case_id": case["case_id"],
            "positive_guidance": False,
            "implementation_authorization": "not-authorized",
            "repository_write_authorization": "not-authorized",
            "merge_authorization": "not-authorized",
            "automatic_selection": False,
            "rc3_results": [],
            "rc4_severity": "pass",
            "rc5_informational_statuses": [],
            "base_readiness_before": "ready",
            "base_readiness_after": "ready",
            "rendered_report": "stable report",
        }, "stable report"

    monkeypatch.setattr(pilot, "load_package", lambda fixture: package)
    monkeypatch.setattr(pilot, "load_api", lambda root: object())
    monkeypatch.setattr(pilot, "verify_baseline", lambda *args: None)
    monkeypatch.setattr(pilot, "_once", fake_once)
    monkeypatch.setattr(pilot, "_compare", lambda case, actual: [])
    monkeypatch.setattr(
        pilot,
        "_thresholds",
        lambda package, actuals: {
            "deterministic_repeated_output": {
                "numerator": 24,
                "denominator": 24,
                "required": 24,
                "passed": True,
            }
        },
    )

    result = pilot.run_pilot(FIXTURE, BASELINE_ROOT, pilot.FROZEN_SHA, verify_head=False)

    assert calls == [case_id for case_id in pilot.EXPECTED_IDS for _ in range(2)]
    assert result.exit_code == 0
    assert result.payload["mode"] == "pilot"
    assert result.payload["summary"]["passed_cases"] == 24
    assert result.payload["summary"]["deterministic_cases"] == 24
    assert all(
        case["actual"]["repeat_output_digest_1"] == case["actual"]["repeat_output_digest_2"]
        for case in result.payload["cases"]
    )
    assert json.loads(result.json_text) == result.payload
    assert "This report is evidence only" in result.markdown_text


@pytest.mark.parametrize("target", ["run_preflight", "run_pilot"])
def test_wrong_sha_fails_closed_before_loading_interfaces(monkeypatch, target):
    monkeypatch.setattr(
        pilot,
        "load_api",
        lambda root: pytest.fail("interfaces must not load for a mismatched SHA"),
    )
    with pytest.raises(pilot.PilotContractError, match="tested SHA"):
        getattr(pilot, target)(FIXTURE, BASELINE_ROOT, "0" * 40, verify_head=False)


def test_cli_contract_error_writes_failed_closed_evidence(monkeypatch, tmp_path):
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
    assert {path.name for path in tmp_path.iterdir()} == {
        "rc6-technical-pilot.json",
        "rc6-technical-pilot.md",
        "SHA256SUMS",
    }
    payload = json.loads((tmp_path / "rc6-technical-pilot.json").read_text(encoding="utf-8"))
    assert payload["summary"]["result"] == "failed-closed"
    assert payload["error"]["type"] == "PilotContractError"
    assert payload["authorization"]["repository_writes"] == "not-authorized"
    markdown = (tmp_path / "rc6-technical-pilot.md").read_text(encoding="utf-8")
    assert "FAILED CLOSED" in markdown
    manifest = (tmp_path / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert manifest == [
        f"{hashlib.sha256((tmp_path / 'rc6-technical-pilot.json').read_bytes()).hexdigest()}  rc6-technical-pilot.json",
        f"{hashlib.sha256((tmp_path / 'rc6-technical-pilot.md').read_bytes()).hexdigest()}  rc6-technical-pilot.md",
    ]
