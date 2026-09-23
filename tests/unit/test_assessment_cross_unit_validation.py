import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/assessment-cross-unit-validation-standard.md"
FIXTURES = ROOT / "tests/fixtures/assessment_blueprint"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def classify(record):
    policy = record.get("policy_condition", {})
    checks = [
        record.get("synthetic_noncanonical") is True,
        not record.get("canonical_target_claimed"),
        not record.get("domain_label_used_as_selector"),
        not record.get("foreign_domain_rule_injected"),
        record.get("target_claim_evidence_method_aligned"),
        record.get("survey_mastery_separate"),
        record.get("policy_condition_respected"),
        not policy.get("ai_policy_applied") or policy.get("ai_condition_supplied"),
        record.get("lifecycle_preserves_unrelated"),
        record.get("sequence_semantics_valid"),
        record.get("qa_non_authorizing"),
        record.get("workspace_semantics_consistent"),
        record.get("authority_valid"),
    ]
    return "portable" if all(checks) else "invalid"


def by_domain(records, domain):
    return next(record for record in records if record["domain"] == domain)


def test_standard_consumes_existing_assessment_stack_without_reimplementation():
    text = STANDARD.read_text()
    for phrase in [
        "#837", "#838", "#1192", "#839", "#841", "#842", "#843",
        "Teacher Decision Studio", "Artifact-First Response", "does not redefine",
    ]:
        assert phrase in text
    assert "#840 and #844 remain retired/not planned" in text
    assert "content domains, not agents" in text.lower()
    assert "standalone Assessment Agent" in text


def test_fixture_projection_is_bounded_and_explicitly_synthetic():
    required = {
        "synthetic_noncanonical", "domain", "synthetic_target_id",
        "target_classification", "claim", "observable_evidence",
        "selected_method", "method_rationale", "task_pattern",
        "scoring_observation_need", "assessment_classification",
        "policy_condition", "accessibility_context_note",
        "lifecycle_expectation", "sequencing_expectation",
        "qa_expectation", "workspace_expectation", "regression_tags",
    }
    for record in load("cross-unit-portability-positive.json") + load("cross-unit-portability-negative.json"):
        assert required <= set(record), record["case"]
        assert record["synthetic_target_id"].startswith("synthetic-")
        assert record["synthetic_noncanonical"] is True


def test_all_six_required_domains_are_portable_from_supplied_context():
    records = load("cross-unit-portability-positive.json")
    assert {record["domain"] for record in records} == {
        "Photography", "Typography", "Graphic Design",
        "Branding", "Video Production", "AI Media",
    }
    for record in records:
        assert classify(record) == record["expected"] == "portable", record["case"]
        assert record["domain_label_used_as_selector"] is False
        assert record["foreign_domain_rule_injected"] is False


def test_method_and_evidence_are_target_driven_not_domain_defaults():
    records = load("cross-unit-portability-positive.json")
    photo = by_domain(records, "Photography")
    video = by_domain(records, "Video Production")
    typography = by_domain(records, "Typography")
    branding = by_domain(records, "Branding")

    assert photo["claim"] != video["claim"]
    assert photo["selected_method"] != video["selected_method"]
    assert photo["observable_evidence"] != video["observable_evidence"]
    assert "hierarchy" in typography["claim"].lower()
    assert "readab" in typography["claim"].lower()
    assert "camera" in " ".join(typography["regression_tags"]).lower()
    assert "audience" in branding["claim"].lower()
    assert "identity" in branding["claim"].lower()
    assert "equipment" in " ".join(branding["regression_tags"]).lower()


def test_ai_policy_is_assignment_specific_and_not_a_domain_wide_default():
    records = load("cross-unit-portability-positive.json")
    applied = [record for record in records if record["policy_condition"]["ai_policy_applied"]]
    assert [record["domain"] for record in applied] == ["AI Media"]
    assert all(record["policy_condition"]["ai_condition_supplied"] for record in applied)
    for record in records:
        policy = record["policy_condition"]
        assert not policy["ai_policy_applied"] or policy["ai_condition_supplied"]


def test_lifecycle_qa_and_workspace_semantics_remain_portable_and_non_authorizing():
    records = load("cross-unit-portability-positive.json")
    assert all(record["lifecycle_expectation"]["preserve_unrelated"] for record in records)
    assert all(record["qa_expectation"] == "valid" for record in records)
    assert all(record["workspace_expectation"]["status_semantics"] == "canonical" for record in records)
    assert all(record["workspace_expectation"]["warning_has_repair"] for record in records)
    assert all(record["workspace_expectation"]["progressive_disclosure"] for record in records)
    assert all(record["qa_non_authorizing"] and record["authority_valid"] for record in records)
    assert any(
        "no-unit-specific-repair" in record["regression_tags"]
        and not record["unit_specific_repair_required"]
        for record in records
    )


def test_negative_cross_unit_regressions_fail_closed():
    records = load("cross-unit-portability-negative.json")
    required_cases = {
        "typography-file-naming-without-target",
        "branding-equipment-inspection-without-target",
        "video-copies-photography-criteria",
        "camera-assumption-noncamera-domain",
        "ai-policy-without-supplied-condition",
        "unit0-survey-promoted-to-mastery",
        "domain-label-determines-method",
        "dashboard-status-varies-by-domain",
        "synthetic-target-presented-canonical",
        "local-failure-global-invalidation",
        "qa-portability-elevates-authority",
    }
    assert required_cases <= {record["case"] for record in records}
    for record in records:
        assert classify(record) == record["expected"] == "invalid", record["case"]


def test_standard_routes_defects_to_existing_owners_and_preserves_fixed_authority():
    text = STANDARD.read_text()
    for owner in [
        "assessment design -> #837",
        "blueprint structure -> #838",
        "lifecycle/change impact/preservation -> #1192",
        "sequencing/student experience -> #839",
        "QA -> #841",
        "Unit 0 integration-baseline assumptions -> #842",
        "dashboard/workspace -> #843",
    ]:
        assert owner in text
    for phrase in [
        "classroom_use_authorized", "grading_authorized",
        "readiness_authorized", "production_authorized",
        "publication_authorized", "external_write_authorized",
        "source_of_truth_write_authorized",
    ]:
        assert phrase in text
