import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/assessment-dashboard-workspace-standard.md"
SCHEMA = ROOT / "03_Templates/assessment-dashboard-workspace.v1.schema.json"
FIXTURES = ROOT / "tests/fixtures/assessment_blueprint"


def classify(record):
    checks = [
        not record.get("forced_linear"),
        not record.get("overview_dump"),
        record.get("preserves_unrelated"),
        record.get("survey_mastery_distinct"),
        record.get("time_visible"),
        record.get("target_gaps_visible"),
        record.get("status_authority_safe"),
        record.get("warning_has_repair"),
        record.get("usable_content_first"),
        record.get("guidance_local"),
        record.get("authority_valid"),
        not record.get("aggregate_masks_failure"),
    ]
    return "valid" if all(checks) else "invalid"


def test_standard_consumes_existing_contracts_without_reimplementing_them():
    text = STANDARD.read_text()
    for phrase in ["#837", "#838", "#1192", "#839", "#841", "Teacher Decision Studio", "Artifact-First Response", "does not create a second lifecycle", "#842"]:
        assert phrase in text
    assert "#840 is retired" in text
    assert "standalone Assessment Agent" in text


def test_schema_has_finite_planning_statuses_and_fixed_authority():
    schema = json.loads(SCHEMA.read_text())
    assert schema["$defs"]["status"]["enum"] == ["not_started", "draft", "needs_teacher_decision", "needs_revision", "blocked", "approved_section_draft", "revalidation_required"]
    authority = schema["$defs"]["authority"]["properties"]
    assert authority["report_only"]["const"] is True
    for key in ["execution_authorized","classroom_use_authorized","grading_authorized","readiness_authorized","production_authorized","publication_authorized","external_write_authorized","source_of_truth_write_authorized"]:
        assert authority[key]["const"] is False
    assert schema["additionalProperties"] is False


def test_schema_keeps_survey_and_mastery_semantically_distinct():
    schema = json.loads(SCHEMA.read_text())
    values = schema["$defs"]["section"]["properties"]["evidence_classification"]["enum"]
    assert "survey_only" in values and "mastery" in values
    assert values.index("survey_only") != values.index("mastery")


def test_warning_contract_requires_repair_route_and_affected_section():
    schema = json.loads(SCHEMA.read_text())
    required = schema["$defs"]["warning"]["required"]
    assert "affected_section_id" in required
    assert "repair_action" in required
    assert "revalidation_ref" in required


def test_positive_fixtures_are_valid():
    for record in json.loads((FIXTURES / "dashboard-workspace-positive.json").read_text()):
        assert classify(record) == record["expected"], record["case"]


def test_negative_fixtures_fail_closed():
    for record in json.loads((FIXTURES / "dashboard-workspace-negative.json").read_text()):
        assert classify(record) == record["expected"], record["case"]


def test_fixtures_are_synthetic_noncanonical_and_downstream_unit_zero_stays_with_842():
    text = STANDARD.read_text()
    assert "synthetic and noncanonical" in text
    assert "not approved Unit 0 targets" in text
    assert "#842 is the downstream owner" in text
