import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/unit0-assessment-reference-validation-standard.md"
FIXTURES = ROOT / "tests/fixtures/assessment_blueprint"


def classify(record):
    checks = [
        record.get("synthetic_noncanonical"),
        record.get("design_valid"),
        record.get("blueprint_valid"),
        record.get("lifecycle_current"),
        record.get("sequence_valid"),
        record.get("qa_valid"),
        record.get("workspace_valid"),
        record.get("survey_mastery_separate"),
        record.get("authentic_evidence"),
        record.get("observable_evidence"),
        record.get("claim_aligned"),
        record.get("ai_policy_match"),
        record.get("vocabulary_eligible"),
        record.get("scoring_guidance"),
        record.get("instructional_usefulness"),
        record.get("preserves_unrelated"),
        record.get("warning_has_repair"),
        record.get("usable_content_first"),
        record.get("authority_valid"),
    ]
    return "valid" if all(checks) else "invalid"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_standard_composes_canonical_stack_without_reimplementation():
    text = STANDARD.read_text()
    for phrase in ["#837", "#838", "#1192", "#839", "#841", "#843", "Teacher Decision Studio", "Artifact-First Response", "does not redefine", "#846"]:
        assert phrase in text
    assert "#840 remains retired" in text
    assert "standalone Assessment Agent" in text


def test_positive_unit0_integration_fixtures_are_valid_and_synthetic():
    records = load("unit0-integration-positive.json")
    required_cases = {
        "readiness-survey-separated",
        "file-organization-performance",
        "equipment-inspection-observation",
        "constructive-critique",
        "assignment-specific-ai-judgment",
        "vocabulary-after-practice",
        "local-edit-preserves-unrelated",
    }
    assert required_cases <= {record["case"] for record in records}
    for record in records:
        assert record["synthetic_noncanonical"] is True
        assert classify(record) == record["expected"] == "valid", record["case"]


def test_negative_unit0_integration_fixtures_fail_closed():
    records = load("unit0-integration-negative.json")
    required_cases = {
        "canonical-claim-from-synthetic",
        "confidence-as-mastery",
        "procedure-selected-response-only",
        "target-method-mismatch",
        "untaught-vocabulary",
        "invalid-sequencing-demand",
        "missing-observation-guidance",
        "score-only-output",
        "ai-policy-mismatch",
        "stale-presented-current",
        "local-edit-global-reset",
        "warning-without-repair",
        "audit-before-usable-content",
        "authority-elevation",
    }
    assert required_cases <= {record["case"] for record in records}
    for record in records:
        assert classify(record) == record["expected"] == "invalid", record["case"]


def test_integration_preserves_upstream_ownership_boundaries():
    text = STANDARD.read_text()
    assert "#1192 owns stale state" in text
    assert "#839 owns sequencing" in text
    assert "#841 QA remains report-only" in text
    assert "#843 owns dashboard-first presentation" in text
    assert "failure routes back to the owning contract" in text.lower()


def test_fixed_authority_and_noncanonical_boundaries_are_explicit():
    text = STANDARD.read_text()
    for phrase in [
        "synthetic, noncanonical",
        "not approved learning targets",
        "classroom use",
        "grading",
        "readiness",
        "production",
        "publication",
        "external writes",
        "source-of-truth",
    ]:
        assert phrase in text


def test_existing_unit0_qa_cases_are_reused_not_reinvented():
    qa_cases = {record["case"] for record in load("qa-positive.json")}
    integration_cases = {record["case"] for record in load("unit0-integration-positive.json")}
    assert {
        "readiness-survey-separated",
        "file-organization-performance",
        "equipment-inspection-observation",
        "assignment-specific-ai-judgment",
        "vocabulary-after-practice",
    } <= qa_cases & integration_cases


def test_workspace_preservation_case_matches_existing_dashboard_regression():
    workspace_cases = {record["case"] for record in load("dashboard-workspace-positive.json")}
    integration_cases = {record["case"] for record in load("unit0-integration-positive.json")}
    assert "local-edit-preserves-unrelated" in workspace_cases & integration_cases
