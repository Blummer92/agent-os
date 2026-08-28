import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/assessment-sequencing-student-experience-standard.md"
SCHEMA = ROOT / "03_Templates/assessment-sequencing-student-experience.v1.schema.json"
FIXTURES = ROOT / "tests/fixtures/assessment_blueprint"


def classify(record):
    if record.get("authority_valid") is False:
        return "blocked"
    if record.get("lifecycle_disposition") in {"stale", "needs-decision"}:
        return "blocked"
    if record.get("survey_mastery_separate") is False or record.get("dependencies_valid") is False:
        return "blocked"
    if record.get("teacher_owned_time_choice") and record.get("time_feasible") is False:
        return "needs_teacher_decision"
    if record.get("language_complete") is False or record.get("time_feasible") is False or record.get("workload_feasible") is False:
        return "revision_required"
    return "valid"


def test_standard_consumes_upstream_contracts_and_stays_non_authorizing():
    text = STANDARD.read_text()
    for phrase in ["#837", "#838", "#1192", "survey", "cognitive", "workload", "does not create a second lifecycle model", "authorizes no classroom use"]:
        assert phrase in text
    assert "new Assessment Agent" in text


def test_schema_has_fixed_authority_and_finite_statuses():
    schema = json.loads(SCHEMA.read_text())
    assert schema["properties"]["sequence_status"]["enum"] == ["blocked", "needs_teacher_decision", "revision_required", "valid"]
    authority = schema["$defs"]["authority"]["properties"]
    assert authority["report_only"]["const"] is True
    for key in ["execution_authorized","classroom_use_authorized","grading_authorized","readiness_authorized","production_authorized","publication_authorized","external_write_authorized","source_of_truth_write_authorized"]:
        assert authority[key]["const"] is False
    assert schema["additionalProperties"] is False


def test_positive_fixtures_follow_deterministic_outcomes():
    for record in json.loads((FIXTURES / "sequencing-positive.json").read_text()):
        assert classify(record) == record["sequence_status"], record["case"]


def test_negative_fixtures_fail_closed_or_require_revision():
    for record in json.loads((FIXTURES / "sequencing-negative.json").read_text()):
        if "expected_status" in record:
            assert classify(record) == record["expected_status"], record["case"]
            assert classify(record) != record["claimed_status"], record["case"]


def test_local_edit_preserves_unrelated_sections():
    record = json.loads((FIXTURES / "sequencing-positive.json").read_text())[-1]
    assert record["case"] == "bounded-local-reorder"
    assert set(record["preserved_section_ids"]) == {"orientation", "foundation", "reflection"}
    bad = json.loads((FIXTURES / "sequencing-negative.json").read_text())[-1]
    assert bad["local_edit"] is True
    assert bad["preserved_section_ids"] == []
    assert bad["expected_preservation_valid"] is False
