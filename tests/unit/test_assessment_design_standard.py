import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/assessment-design-standard.md"
SCHEMA = ROOT / "03_Templates/assessment-design-record.v1.schema.json"
FIXTURES = ROOT / "tests/fixtures/assessment_design"

APPLIED = {"procedural_skill", "technical_workflow", "critique", "revision", "creative_production", "performance"}
AUTHENTIC_METHODS = {"demonstration", "simulation", "authentic_performance_task", "observation", "product_or_project", "critique", "revision_task", "portfolio_evidence"}


def classify(record):
    purpose = record["assessment_purpose"]
    evidence = record["survey_mastery_classification"]
    target = record["primary_target_classification"]
    method = record["selected_method"]
    if purpose in {"readiness_survey", "interest_confidence_experience_survey"} and evidence != "survey_only":
        return "survey_mastery_conflict"
    if target in APPLIED and method == "selected_response":
        return "method_mismatch"
    if target in {"procedural_skill", "technical_workflow", "performance"} and method not in AUTHENTIC_METHODS:
        return "authentic_evidence_missing"
    return "valid"


def test_standard_is_bounded_and_contains_core_contract():
    text = STANDARD.read_text()
    assert len(text.splitlines()) < 100
    for phrase in ["target-first", "survey_only", "mastery_capable", "needs_teacher_decision", "#838", "report_only: true"]:
        assert phrase in text


def test_schema_requires_fixed_false_authority_fields():
    schema = json.loads(SCHEMA.read_text())
    authority = schema["properties"]["authority"]
    assert authority["properties"]["report_only"]["const"] is True
    for name in authority["required"]:
        if name != "report_only":
            assert authority["properties"][name]["const"] is False


def test_positive_fixtures_are_valid():
    for record in json.loads((FIXTURES / "positive.json").read_text()):
        assert classify(record) == "valid", record["case"]


def test_negative_fixtures_fail_for_declared_reason():
    for record in json.loads((FIXTURES / "negative.json").read_text()):
        assert classify(record) == record["expected"], record["case"]
