from pathlib import Path

import yaml

from scripts.agent_os_issue_acceptance.metadata_validation import (
    validate_metadata_evidence,
)
from scripts.agent_os_issue_acceptance.models import Status


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "metadata_validation_cases.yml"
)


def _load_cases() -> list[dict]:
    payload = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    cases = payload.get("cases")
    assert isinstance(cases, list)
    return cases


def _case(case_id: str) -> dict:
    matches = [case for case in _load_cases() if case["id"] == case_id]
    assert len(matches) == 1
    return matches[0]


def test_metadata_validation_matches_fixture_expected_outcomes():
    for case in _load_cases():
        result = validate_metadata_evidence(str(case["field"]), str(case["input_evidence"]))

        assert result.classification == case["classification"]
        assert result.outcome.value == case["expected_outcome"]


def test_metadata_validation_check_output_is_report_only_evidence():
    case = _case("issue-tier-candidate-alias-high-risk")
    result = validate_metadata_evidence(str(case["field"]), str(case["input_evidence"]))
    check = result.to_check()

    assert check.name == "metadata:issue_tier"
    assert check.status == Status.MANUAL_REVIEW
    assert "field=issue_tier" in check.evidence
    assert "classification=candidate-alias" in check.evidence


def test_candidate_alias_does_not_become_canonical():
    case = _case("issue-tier-candidate-alias-high-risk")
    result = validate_metadata_evidence(str(case["field"]), str(case["input_evidence"]))

    assert result.classification == "candidate-alias"
    assert result.outcome == Status.MANUAL_REVIEW


def test_generic_tier_language_does_not_silently_normalize():
    for value in ("Tier 0", "Tier 1", "Tier 2", "Tier 3: production modifier"):
        result = validate_metadata_evidence("issue_tier", value)

        assert result.outcome == Status.MANUAL_REVIEW
        assert result.classification in {"ambiguous", "legacy-evidence-only"}


def test_body_label_readiness_conflict_requires_manual_review():
    case = _case("readiness-body-label-conflict")
    result = validate_metadata_evidence(str(case["field"]), str(case["input_evidence"]))

    assert result.classification == "ambiguous"
    assert result.outcome == Status.MANUAL_REVIEW


def test_legacy_metadata_remains_evidence_only():
    for case_id in (
        "legacy-risk-live-write",
        "legacy-surface-github-issues",
        "legacy-system-github",
        "legacy-phase-governance",
    ):
        case = _case(case_id)
        result = validate_metadata_evidence(str(case["field"]), str(case["input_evidence"]))

        assert result.classification == "legacy-evidence-only"
        assert result.outcome == Status.MANUAL_REVIEW


def test_unknown_governed_enum_value_fails():
    case = _case("unknown-governed-enum-value")
    result = validate_metadata_evidence(str(case["field"]), str(case["input_evidence"]))

    assert result.classification == "invalid"
    assert result.outcome == Status.FAIL


def test_owner_registry_surface_gap_warns_without_invalidating_owner():
    case = _case("owner-registry-form-surface-gap")
    result = validate_metadata_evidence(str(case["field"]), str(case["input_evidence"]))

    assert result.classification == "canonical"
    assert result.outcome == Status.WARN


def test_unregistered_owner_prose_requires_manual_review():
    case = _case("owner-unregistered-prose")
    result = validate_metadata_evidence(str(case["field"]), str(case["input_evidence"]))

    assert result.classification == "ambiguous"
    assert result.outcome == Status.MANUAL_REVIEW
