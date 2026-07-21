from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from scripts.agent_os_rc6_technical_pilot.runner import (
    EXPECTED_IDS,
    FIXTURE_SHA256,
    FROZEN_SHA,
    FixtureContractError,
    load_frozen_package,
    validate_frozen_package,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/rc6_technical_pilot/cases.json"


def test_frozen_fixture_digest_and_identity_are_exact():
    raw = FIXTURE.read_bytes()
    package = load_frozen_package(FIXTURE)

    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256
    assert package["frozen_sha"] == FROZEN_SHA
    assert package["package_version"] == "RC6-TF-1.0"


def test_frozen_fixture_contains_exactly_ordered_t01_through_t24():
    package = load_frozen_package(FIXTURE)

    assert tuple(case["case_id"] for case in package["cases"]) == EXPECTED_IDS
    assert len({case["case_id"] for case in package["cases"]}) == 24


def test_frozen_fixture_has_no_actual_result_fields():
    text = FIXTURE.read_text(encoding="utf-8")

    assert '"actual_' not in text


def test_duplicate_missing_extra_and_reordered_cases_fail_closed():
    package = load_frozen_package(FIXTURE)

    variants = []
    missing = copy.deepcopy(package)
    missing["cases"].pop()
    variants.append(missing)

    duplicate = copy.deepcopy(package)
    duplicate["cases"][1]["case_id"] = "T01"
    variants.append(duplicate)

    extra = copy.deepcopy(package)
    extra["cases"].append(copy.deepcopy(extra["cases"][-1]))
    extra["cases"][-1]["case_id"] = "T25"
    variants.append(extra)

    reordered = copy.deepcopy(package)
    reordered["cases"][0], reordered["cases"][1] = (
        reordered["cases"][1],
        reordered["cases"][0],
    )
    variants.append(reordered)

    for variant in variants:
        with pytest.raises(FixtureContractError, match="exactly T01-T24"):
            validate_frozen_package(variant)


def test_missing_expected_field_fails_closed():
    package = load_frozen_package(FIXTURE)
    package = copy.deepcopy(package)
    del package["cases"][0]["expected"]["rc5_statuses"]

    with pytest.raises(FixtureContractError, match="expected missing fields"):
        validate_frozen_package(package)


def test_thresholds_and_denominators_are_frozen():
    package = load_frozen_package(FIXTURE)

    assert package["thresholds"] == {
        "false_positive_recommendations_max": 0,
        "false_negatives_clean_cases_max": 0,
        "unexpected_manual_review_clean_cases_max": 0,
        "false_implementation_authorizations_max": 0,
        "false_repository_write_authorizations_max": 0,
        "false_merge_authorizations_max": 0,
        "silent_automatic_selection_max": 0,
        "deterministic_cases_required": 24,
        "contradicted_evidence_used_positively_max": 0,
        "missing_active_path_used_positively_max": 0,
        "active_exemptions_reviewed_percent_min": 100,
    }
    clean_denominator = [
        case["case_id"]
        for case in package["cases"]
        if "false-negative" in case["threshold_classes"]
    ]
    assert clean_denominator == ["T01", "T21", "T22", "T23", "T24"]
