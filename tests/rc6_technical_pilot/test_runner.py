from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import agent_os_rc6_technical_pilot as pilot
from scripts import agent_os_rc6_pilot_support as support

RUNNER_ROOT = Path(__file__).resolve().parents[2]
BASELINE_ROOT = Path(os.environ.get("RC6_BASELINE_ROOT", RUNNER_ROOT)).resolve()
FIXTURE = RUNNER_ROOT / "tests/fixtures/rc6_technical_pilot/frozen_package.json"


def _package():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_is_exact_ordered_frozen_package():
    package = pilot.load_frozen_package(FIXTURE)
    assert package["package_version"] == "RC6-TF-1.1"
    assert package["frozen_sha"] == pilot.FROZEN_SHA
    assert [case["case_id"] for case in package["cases"]] == list(pilot.EXPECTED_IDS)
    assert len(package["cases"]) == 24


def test_fixture_records_exact_clean_and_t14_behavioral_contracts():
    package = _package()
    assert package["synthetic_fixture_contract"] == {
        "S-CLEAN": {
            "invariants": ["run(value) returns value + 1 for integer input."],
            "compatibility": [
                "src.pkg.mod:run remains stable within the RC6 synthetic fixture contract."
            ],
        },
        "behavioral_contract_missing": {
            "invariants": [],
            "compatibility": [],
        },
    }
    assert support.S_CLEAN_CONTRACT == package["synthetic_fixture_contract"]["S-CLEAN"]
    assert support.T14_OVERRIDE == package["synthetic_fixture_contract"]["behavioral_contract_missing"]


def test_t01_and_t14_remain_behaviorally_distinct():
    package = pilot.load_frozen_package(FIXTURE)
    by_id = {case["case_id"]: case for case in package["cases"]}
    assert by_id["T01"]["scenario"] == "clean_verified"
    assert by_id["T14"]["scenario"] == "behavioral_contract_missing"
    assert by_id["T14"]["expected"]["rc5_informational_statuses"] == ["pass"]
    assert by_id["T14"]["expected"]["rc5_evidence_disposition"] == (
        "positive-with-explicit-residual-risk"
    )
    assert by_id["T14"]["expected"]["required_rc5_evidence"] == [
        "remaining_risk=behavioral-contract-not-evaluated"
    ]


def test_runtime_record_contract_matches_package_and_t14_removes_it():
    clean = support._record()
    missing = support._record(**support.T14_OVERRIDE)
    assert clean["invariants"] == support.S_CLEAN_INVARIANTS
    assert clean["compatibility"] == support.S_CLEAN_COMPATIBILITY
    assert missing["invariants"] == []
    assert missing["compatibility"] == []
    assert clean != missing


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


def test_fixture_rejects_synthetic_contract_drift():
    package = copy.deepcopy(_package())
    package["synthetic_fixture_contract"]["S-CLEAN"]["invariants"] = []
    with pytest.raises(pilot.PilotContractError, match="synthetic fixture contract"):
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


def test_frozen_component_identities_and_sha_are_unchanged():
    package = _package()
    assert package["frozen_sha"] == "ca980c38d74b8d3ab30ca67461a9f576281edc75"
    assert package["frozen_identities"] == {
        "registry_blob": "92fa715d25081487c975969663cedbba9f641e02",
        "registry_version": "0.1.0",
        "provenance_algorithm": "registry-canonical-records",
        "provenance_algorithm_version": 1,
        "provenance_digest": "6cccfc9e86387865c97d10eb7f782c589ebbf016cf507d0cb28c99f48e00a7be",
        "discovery_blob": "c0faa18f7cb7aa7dc71b7ad48437c87db595eb0a",
        "validation_blob": "950d6210c057dd8c2512f356b97398eb8249e42a",
        "rc5_blob": "b1610da51b73ae94202a9c304460e680952fa33b",
        "rc4_package_version": "0.2.0",
        "rc4_report_version": "1.0",
    }


def test_preflight_validates_frozen_boundary_without_executing_cases(monkeypatch):
    cases = [{"case_id": case_id} for case_id in pilot.EXPECTED_IDS]
    package = {"package_version": "RC6-TF-1.1", "cases": cases}
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
    package = {"package_version": "RC6-TF-1.1", "cases": cases, "thresholds": {}}
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


def _fake_summary(status: str):
    class DiscoveryResult:
        pass

    class ValidationReport:
        pass

    class Provenance:
        is_supported = True

        def __hash__(self):
            return 1

        def __eq__(self, other):
            return isinstance(other, Provenance)

    provenance = Provenance()
    result = DiscoveryResult()
    result.capability = SimpleNamespace(capability_id="widget")
    result.confidence = SimpleNamespace(value="verified")
    result.evidence_basis = ("exact-capability-id-match",)
    result.warnings = ()
    result.manual_review_reasons = ()
    result.provenance = provenance
    report = ValidationReport()
    report.provenance = provenance
    report.findings = ()
    candidate = SimpleNamespace(
        name="reuse candidate widget",
        status=SimpleNamespace(value=status),
        evidence=[pilot.AUTH_EVIDENCE],
    )
    unmatched = SimpleNamespace(
        name="reuse unmatched validation findings",
        status=SimpleNamespace(value="manual-review"),
        evidence=["validation_finding=unrelated"],
    )
    attached = SimpleNamespace(
        outcome=SimpleNamespace(value="ready"),
        report=SimpleNamespace(informational_checks=(candidate, unmatched)),
    )
    base = SimpleNamespace(outcome=SimpleNamespace(value="ready"))
    api = SimpleNamespace(DiscoveryResult=DiscoveryResult, ValidationReport=ValidationReport)
    case = {"case_id": "T21", "scenario": "current_clean"}
    return pilot._summarize(case, base, [result], report, attached, "rendered", api)


@pytest.mark.parametrize(
    ("status", "expected_disposition"),
    [("pass", "positive-informational"), ("warn", "qualified-positive")],
)
def test_candidate_status_is_not_conflated_with_unmatched_diagnostics(status, expected_disposition):
    summary = _fake_summary(status)

    assert summary["rc5_informational_statuses"] == [status]
    assert summary["rc5_evidence_disposition"] == expected_disposition
    assert summary["positive_guidance"] is True
    assert summary["rc5_candidate_checks"] == [{
        "name": "reuse candidate widget",
        "status": status,
        "evidence": [pilot.AUTH_EVIDENCE],
    }]
    assert summary["rc5_diagnostic_checks"] == [{
        "name": "reuse unmatched validation findings",
        "status": "manual-review",
        "evidence": ["validation_finding=unrelated"],
    }]


def test_compare_treats_warning_and_review_collections_as_unordered():
    expected = {
        "rc3_results": [],
        "rc3_warnings": ["a", "b"],
        "rc3_manual_review_reasons": ["c", "d"],
        "rc4_severity": "pass",
        "rc4_finding_codes": ["x", "y"],
        "provenance_interpretation": "matched",
        "rc5_informational_statuses": ["pass"],
        "rc5_evidence_disposition": "positive-informational",
        "base_readiness_before": "ready",
        "base_readiness_after": "ready",
        "implementation_authorization": "not-authorized",
        "repository_write_authorization": "not-authorized",
        "merge_authorization": "not-authorized",
        "automatic_selection": False,
    }
    actual = dict(expected)
    actual.update({
        "rc3_warnings": ["b", "a"],
        "rc3_manual_review_reasons": ["d", "c"],
        "rc4_finding_codes": ["y", "x"],
        "rc5_check_names": ["reuse candidate widget"],
        "rc5_evidence": [pilot.AUTH_EVIDENCE],
    })

    assert pilot._compare({"expected": expected}, actual) == []


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
    subprocess.run(
        ["sha256sum", "-c", "SHA256SUMS"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
