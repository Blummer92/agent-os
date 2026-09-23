import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/assessment-qa-evidence-review-standard.md"
SCHEMA = ROOT / "03_Templates/assessment-qa-evidence-review.v1.schema.json"
FIXTURES = ROOT / "tests/fixtures/assessment_blueprint"


def classify(record):
    if not record.get("upstream_current") or not record.get("identity_match") or not record.get("authority_valid"):
        return "blocked"
    if not record.get("survey_mastery_separate") or not record.get("authentic_evidence_valid"):
        return "blocked"
    if not record.get("taught_content") or record.get("policy_conflict"):
        return "blocked"
    if record.get("manual_review"):
        return "manual_review"
    if record.get("revision_needed") or not record.get("instructional_usefulness"):
        return "revision_required"
    return "valid"


def test_standard_consumes_upstream_contracts_without_reimplementing_them():
    text = STANDARD.read_text()
    for phrase in ["#837", "#838", "#1192", "#839", "second sequencing", "report-only", "standalone Assessment Agent"]:
        assert phrase in text
    assert "#842" in text


def test_schema_has_finite_dispositions_separate_findings_and_fixed_authority():
    schema = json.loads(SCHEMA.read_text())
    assert schema["properties"]["overall_disposition"]["enum"] == ["blocked", "manual_review", "revision_required", "valid"]
    required = schema["properties"]["category_findings"]["required"]
    assert "alignment" in required and "evidence" in required
    finding_states = schema["$defs"]["finding"]["properties"]["state"]["enum"]
    assert finding_states == ["pass", "fail", "manual_review", "not_applicable"]
    authority = schema["$defs"]["authority"]["properties"]
    assert authority["report_only"]["const"] is True
    for key in ["execution_authorized","classroom_use_authorized","grading_authorized","readiness_authorized","production_authorized","publication_authorized","external_write_authorized","source_of_truth_write_authorized"]:
        assert authority[key]["const"] is False
    assert schema["additionalProperties"] is False


def test_positive_and_bounded_nonvalid_fixtures_are_deterministic():
    for record in json.loads((FIXTURES / "qa-positive.json").read_text()):
        assert classify(record) == record["expected"], record["case"]


def test_negative_fixtures_fail_closed_or_route_to_review_or_revision():
    for record in json.loads((FIXTURES / "qa-negative.json").read_text()):
        assert classify(record) == record["expected"], record["case"]
        assert classify(record) != record["claimed"], record["case"]


def test_unit_zero_fixtures_are_explicitly_synthetic_and_noncanonical():
    text = STANDARD.read_text()
    assert "synthetic regression evidence only" in text
    assert "never canonical classroom content" in text
    cases = {r["case"] for r in json.loads((FIXTURES / "qa-positive.json").read_text())}
    assert {"readiness-survey-separated","file-organization-performance","equipment-inspection-observation","evidence-based-critique","assignment-specific-ai-judgment","vocabulary-after-practice"} <= cases
