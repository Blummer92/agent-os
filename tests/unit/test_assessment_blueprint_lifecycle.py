import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/assessment-blueprint-lifecycle-standard.md"
SCHEMA = ROOT / "03_Templates/assessment-blueprint-lifecycle.v1.schema.json"
FIXTURES = ROOT / "tests/fixtures/assessment_blueprint"

CONSUMERS = ("dashboard", "portability", "qa", "sequencing")
IMPACT_ORDER = (
    "no_revalidation",
    "local_validation",
    "blueprint_validation",
    "qa_rerun",
    "teacher_review",
    "downstream_invalidation",
)

PREFIX_IMPACT = (
    ("metadata.", "no_revalidation"),
    ("presentation.", "local_validation"),
    ("blueprint.provenance.", "blueprint_validation"),
    ("blueprint.task_format.", "blueprint_validation"),
    ("blueprint.complexity.", "blueprint_validation"),
    ("blueprint.blockers", "blueprint_validation"),
    ("blueprint.unresolved_uncertainties", "blueprint_validation"),
    ("blueprint.assessment_design_record.observable_evidence", "qa_rerun"),
    ("blueprint.assessment_design_record.selected_method", "qa_rerun"),
    ("blueprint.accessibility.", "qa_rerun"),
    ("blueprint.ai_conditions.", "qa_rerun"),
    ("blueprint.authority.", "qa_rerun"),
    ("blueprint.assessment_design_record.assessment_purpose", "teacher_review"),
    ("blueprint.assessment_design_record.intended_instructional_decision", "teacher_review"),
    ("blueprint.student_time.", "teacher_review"),
    ("blueprint.scoring.", "teacher_review"),
    ("blueprint.assessment_design_record.authenticity_requirement", "teacher_review"),
    ("blueprint.assessment_design_record.approved_target_ref", "blueprint_validation"),
    ("blueprint.assessment_design_record.claim_statement", "blueprint_validation"),
)


def _impact_for_path(path):
    if path.startswith("handoff."):
        parts = path.split(".", 2)
        if len(parts) == 3 and parts[1] in CONSUMERS:
            return "downstream_invalidation"
        return None
    matches = [impact for prefix, impact in PREFIX_IMPACT if path.startswith(prefix)]
    return max(matches, key=IMPACT_ORDER.index) if matches else None


def project(record):
    if record.get("authority_override") or record.get("semantic_override"):
        return {"disposition": "needs-decision", "invalidated_consumers": [], "stale": True}

    impacts = [_impact_for_path(path) for path in record["changed_paths"]]
    if any(impact is None for impact in impacts) or record["dependency_impact"] == "ambiguous":
        return {"disposition": "needs-decision", "invalidated_consumers": [], "stale": True}

    if record["shared_semantic_root_changed"]:
        primary = "downstream_invalidation"
        invalidated = list(CONSUMERS)
    else:
        primary = max(impacts, key=IMPACT_ORDER.index) if impacts else "no_revalidation"
        invalidated = sorted({path.split(".", 2)[1] for path in record["changed_paths"] if path.startswith("handoff.")})

    stale_reasons = []
    if record["current_blueprint_version"] != record["last_validated_blueprint_version"]:
        stale_reasons.append("blueprint-version-changed")
    if record["current_source_version"] != record["last_validated_source_version"]:
        stale_reasons.append("authoritative-source-version-changed")
    if record["current_design_record_id"] != record["last_validated_design_record_id"]:
        stale_reasons.append("upstream-design-record-changed")
    if invalidated:
        stale_reasons.append("handed-off-field-changed")
    if record["shared_semantic_root_changed"]:
        stale_reasons.append("shared-semantic-root-changed")

    stale = bool(stale_reasons)
    preserved = sorted(set(record["object_ids"]) - set(record["changed_object_ids"]))
    return {
        "change_impact": primary,
        "stale": stale,
        "stale_reasons": stale_reasons,
        "disposition": "stale" if stale else "current",
        "invalidated_consumers": invalidated,
        "preserved_objects": preserved,
    }


def test_standard_is_bounded_and_keeps_837_838_ownership():
    text = STANDARD.read_text()
    assert len(text.splitlines()) < 100
    for phrase in ["#837", "#838", "needs-decision", "bounded invalidation", "does not itself authorize"]:
        assert phrase in text


def test_schema_composes_core_instead_of_redefining_authority():
    schema = json.loads(SCHEMA.read_text())
    assert schema["properties"]["blueprint"]["$ref"] == "assessment-blueprint-core.v1.schema.json"
    assert "authority" not in schema["properties"]
    assert schema["properties"]["change_impact_class"]["enum"] == list(IMPACT_ORDER)
    assert schema["additionalProperties"] is False


def test_positive_fixtures_cover_all_classes_and_bounded_invalidation():
    records = json.loads((FIXTURES / "lifecycle-positive.json").read_text())
    seen = set()
    for record in records:
        result = project(record)
        seen.add(result["change_impact"])
        assert result["change_impact"] == record["expected_change_impact"], record["case"]
        assert result["stale"] is record["expected_stale"], record["case"]
        assert result["disposition"] == record["expected_disposition"], record["case"]
        assert result["invalidated_consumers"] == record["expected_invalidated_consumers"], record["case"]
        assert result["preserved_objects"] == record["expected_preserved_objects"], record["case"]
    assert seen == set(IMPACT_ORDER)


def test_negative_fixtures_fail_closed_or_expose_false_claims():
    records = json.loads((FIXTURES / "lifecycle-negative.json").read_text())
    for record in records:
        result = project(record)
        if "claimed_disposition" in record:
            assert result["disposition"] != record["claimed_disposition"], record["case"]
        if "claimed_stale" in record:
            assert result["stale"] is not record["claimed_stale"], record["case"]
        if "claimed_invalidated_consumers" in record:
            assert result["invalidated_consumers"] != record["claimed_invalidated_consumers"], record["case"]


def test_stale_reason_codes_are_deterministic():
    record = {
        "current_blueprint_version": "2",
        "last_validated_blueprint_version": "1",
        "current_source_version": "s2",
        "last_validated_source_version": "s1",
        "current_design_record_id": "d2",
        "last_validated_design_record_id": "d1",
        "changed_paths": ["handoff.qa.validation_status"],
        "dependency_impact": "resolved",
        "shared_semantic_root_changed": False,
        "object_ids": ["qa"],
        "changed_object_ids": ["qa"],
    }
    assert project(record)["stale_reasons"] == [
        "blueprint-version-changed",
        "authoritative-source-version-changed",
        "upstream-design-record-changed",
        "handed-off-field-changed",
    ]
