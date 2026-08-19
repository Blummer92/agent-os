import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/assessment-blueprint-core-standard.md"
SCHEMA = ROOT / "03_Templates/assessment-blueprint-core.v1.schema.json"
FIXTURES = ROOT / "tests/fixtures/assessment_blueprint"

DESIGN_REQUIRED = {
    "assessment_design_contract_version", "design_record_id", "source_context",
    "assessment_purpose", "intended_instructional_decision", "approved_target_ref",
    "target_source_state", "claim_id", "claim_statement", "primary_target_classification",
    "supporting_target_classifications", "observable_evidence", "evidence_sufficiency_rule",
    "evidence_exclusions", "selected_method", "supporting_methods", "method_rationale",
    "method_limitations", "survey_mastery_classification", "scoring_or_observation_requirement",
    "success_evidence_features", "likely_misconceptions", "possible_instructional_responses",
    "accessibility_considerations", "authenticity_requirement", "provenance", "blockers",
    "unresolved_uncertainties", "next_owner", "authority"
}


def classify(record):
    if not record["authority_valid"] or record["provenance_conflict"] == "unresolved":
        return "blocked"
    if record["selected_method"] == "survey" and record["survey_mastery_classification"] != "survey_only":
        return "blocked"
    return record["outcome"]


def test_standard_is_bounded_and_has_split_boundary():
    text = STANDARD.read_text()
    assert len(text.splitlines()) < 100
    for phrase in ["#837", "#1192", "report-only", "does not create an Assessment Agent", "fails closed"]:
        assert phrase in text


def test_schema_preserves_complete_837_input_and_fixed_authority():
    schema = json.loads(SCHEMA.read_text())
    design_required = set(schema["$defs"]["designRecord"]["required"])
    assert DESIGN_REQUIRED <= design_required
    authority = schema["$defs"]["authority"]
    assert authority["properties"]["report_only"]["const"] is True
    for name in authority["required"]:
        if name != "report_only":
            assert authority["properties"][name]["const"] is False


def test_schema_excludes_lifecycle_engine_fields():
    schema = json.loads(SCHEMA.read_text())
    forbidden = {"last_validated_version", "change_impact", "stale_validation", "downstream_invalidation"}
    assert forbidden.isdisjoint(schema["properties"])


def test_positive_fixtures_follow_core_outcomes():
    for record in json.loads((FIXTURES / "positive.json").read_text()):
        assert classify(record) == record["outcome"], record["case"]


def test_negative_fixtures_fail_closed():
    for record in json.loads((FIXTURES / "negative.json").read_text()):
        assert classify(record) == record["expected"], record["case"]
