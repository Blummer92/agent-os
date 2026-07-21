from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts.agent_os_rc6_technical_pilot.runner import (
    FROZEN_SHA,
    PilotExecutionError,
    apply_thresholds,
    calculate_metrics,
    canonical_json_bytes,
    compare_expected,
    load_frozen_package,
    render_markdown_summary,
    validate_exact_sha,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/rc6_technical_pilot/manifest.json"
SOURCE_DIR = ROOT / "scripts/agent_os_rc6_technical_pilot"


def test_exact_sha_guard_fails_closed_for_input_or_checkout_mismatch():
    validate_exact_sha(FROZEN_SHA, FROZEN_SHA)

    with pytest.raises(PilotExecutionError, match="supplied SHA"):
        validate_exact_sha("0" * 40, FROZEN_SHA)
    with pytest.raises(PilotExecutionError, match="tested checkout"):
        validate_exact_sha(FROZEN_SHA, "0" * 40)


def test_canonical_json_is_byte_identical_for_mapping_order_changes():
    first = {"b": [2, 1], "a": {"z": False, "x": "value"}}
    second = {"a": {"x": "value", "z": False}, "b": [2, 1]}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_expected_comparison_reports_field_level_drift():
    package = load_frozen_package(FIXTURE)
    expected = package["cases"][0]["expected"]
    actual = copy.deepcopy(expected)
    actual["merge_authorized"] = True

    assert compare_expected(expected, actual) == [
        "merge_authorized: expected=False; actual=True"
    ]


def _passing_case_payloads():
    package = load_frozen_package(FIXTURE)
    payloads = []
    for case in package["cases"]:
        actual = copy.deepcopy(case["expected"])
        actual["deterministic"] = True
        payloads.append({"case_id": case["case_id"], "actual": actual})
    return package, payloads


def test_threshold_classification_and_denominators_are_exact():
    package, payloads = _passing_case_payloads()

    metrics = calculate_metrics(package, payloads)
    thresholds = apply_thresholds(package["thresholds"], metrics)

    assert metrics["false_positive_recommendations"] == 0
    assert metrics["false_negative_denominator"] == 5
    assert metrics["unexpected_manual_review_denominator"] == 5
    assert metrics["deterministic_cases"] == 24
    assert metrics["active_exemptions_reviewed_percent"] == 100
    assert all(item["result"] == "pass" for item in thresholds.values())


def test_zero_tolerance_authorization_violation_fails_threshold():
    package, payloads = _passing_case_payloads()
    payloads[0]["actual"]["implementation_authorized"] = True

    metrics = calculate_metrics(package, payloads)
    thresholds = apply_thresholds(package["thresholds"], metrics)

    assert metrics["false_implementation_authorizations"] == 1
    assert thresholds["false_implementation_authorizations"]["result"] == "fail"


def test_markdown_summary_states_evidence_only_authorization_boundary():
    package, payloads = _passing_case_payloads()
    metrics = calculate_metrics(package, payloads)
    thresholds = apply_thresholds(package["thresholds"], metrics)
    cases = [
        {
            "case_id": case["case_id"],
            "category": case["category"],
            "case_result": "pass",
            "differences": [],
        }
        for case in package["cases"]
    ]
    text = render_markdown_summary(
        {
            "overall_result": "pass",
            "runner_sha": "1" * 40,
            "tested_sha": FROZEN_SHA,
            "case_passed": 24,
            "case_total": 24,
            "fixture_sha256": "2" * 64,
            "threshold_results": thresholds,
            "cases": cases,
        }
    )

    assert "technical evidence only" in text
    assert "no implementation, repository-write, merge, or automatic-selection authorization" in text
    assert "T01" in text and "T24" in text


def test_runner_source_has_no_github_or_external_mutation_path():
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(SOURCE_DIR.glob("*.py"))
    )
    forbidden = [
        "requests.",
        "urllib.request",
        "gh issue edit",
        "gh issue close",
        "gh pr merge",
        "git push",
        "git commit",
        "update_issue",
        "add_issue_labels",
        "notion",
        "googleapiclient",
    ]
    for token in forbidden:
        assert token not in source
