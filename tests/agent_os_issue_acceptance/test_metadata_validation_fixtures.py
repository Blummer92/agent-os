from pathlib import Path

import yaml


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "metadata_validation_cases.yml"
)

ALLOWED_CLASSIFICATIONS = {
    "canonical",
    "candidate-alias",
    "approved-alias",
    "ambiguous",
    "invalid",
    "legacy-evidence-only",
    "out-of-scope",
}

ALLOWED_OUTCOMES = {"pass", "warn", "fail", "manual-review"}

REQUIRED_CASE_FIELDS = {
    "id",
    "field",
    "input_evidence",
    "classification",
    "expected_outcome",
    "reason",
}

REQUIRED_CASE_IDS = {
    "issue-tier-canonical-tier-0",
    "issue-tier-canonical-tier-1",
    "issue-tier-canonical-tier-2",
    "issue-tier-candidate-alias-high-risk",
    "issue-tier-ambiguous-generic-tier-2",
    "issue-tier-execution-risk-tier-3",
    "readiness-body-label-conflict",
    "lifecycle-legacy-ready-for-planning",
    "lifecycle-legacy-blocked-human-review",
    "documentation-impact-required",
    "source-route-github",
    "external-write-none",
    "owner-registered-integration-manager",
    "owner-registry-form-surface-gap",
    "owner-registered-legacy-alias",
    "owner-unregistered-prose",
    "unknown-governed-enum-value",
    "legacy-risk-live-write",
    "legacy-surface-github-issues",
    "legacy-system-github",
    "legacy-phase-governance",
}


def _load_cases() -> list[dict]:
    payload = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    cases = payload.get("cases")
    assert isinstance(cases, list)
    return cases


def test_metadata_validation_fixture_schema_is_complete():
    cases = _load_cases()

    assert cases
    for case in cases:
        assert REQUIRED_CASE_FIELDS <= set(case)
        assert isinstance(case["id"], str) and case["id"].strip()
        assert isinstance(case["field"], str) and case["field"].strip()
        assert isinstance(case["input_evidence"], str)
        assert case["classification"] in ALLOWED_CLASSIFICATIONS
        assert case["expected_outcome"] in ALLOWED_OUTCOMES
        assert isinstance(case["reason"], str) and case["reason"].strip()


def test_metadata_validation_fixture_ids_are_unique():
    cases = _load_cases()
    ids = [case["id"] for case in cases]

    assert len(ids) == len(set(ids))


def test_metadata_validation_fixture_corpus_covers_md1_findings():
    cases = _load_cases()
    ids = {case["id"] for case in cases}

    assert REQUIRED_CASE_IDS <= ids


def test_md1_drift_cases_keep_safe_expected_outcomes():
    cases = {case["id"]: case for case in _load_cases()}

    assert cases["issue-tier-candidate-alias-high-risk"] == {
        "id": "issue-tier-candidate-alias-high-risk",
        "field": "issue_tier",
        "input_evidence": "tier:2-high-risk-or-governed-change",
        "classification": "candidate-alias",
        "expected_outcome": "manual-review",
        "reason": "Candidate alias found by MD1; not approved as canonical.",
    }
    assert cases["issue-tier-ambiguous-generic-tier-2"][
        "expected_outcome"
    ] == "manual-review"
    assert cases["readiness-body-label-conflict"][
        "expected_outcome"
    ] == "manual-review"
    assert cases["unknown-governed-enum-value"]["expected_outcome"] == "fail"
