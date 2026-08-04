"""Structural tests for the LP7 Notion working-layer design (issue #652).

LP7 is design-only. These tests prove the Change Request stays unauthorized, that
every proposed property carries a complete authority map, that nothing in the
projection can advance a gate or carry prohibited student data, and that unresolved
decisions block the live change instead of being defaulted away.
"""

from __future__ import annotations

import pytest
import yaml

from tests.lp_contract_support import (
    assert_canonical_serialization_is_stable,
    assert_contract_identity,
    assert_no_forbidden_governed_keys,
    assert_normative_ids_match_anchors,
    assert_standards_exist,
    load_registry,
    load_yaml_text,
    read_text,
)

REGISTRY_PATH = "04_Registry/lp-notion-working-layer-change-request.yaml"

TOP_LEVEL_KEYS = (
    "registry_name",
    "contract_version",
    "record_revision",
    "normative_standard",
    "handoff_contract",
    "reason_code_catalog",
    "authority_state_registry",
    "change_request_state",
    "live_change_authorized",
    "pilot_execution_authorized",
    "shadow_mode_only",
    "inspection",
    "exact_targets",
    "vocabularies",
    "observed_properties",
    "proposed_properties",
    "proposed_views",
    "prohibited_data",
    "pilot_records",
    "operational_plan",
    "non_authority_guarantees",
    "source_of_truth_rules",
    "authority_rules",
    "architecture_rules",
    "projection_rules",
    "evidence_projection_rules",
    "display_rules",
    "retention_rules",
    "migration_rules",
    "pilot_rules",
    "change_request_rules",
    "retired_patterns",
    "unresolved_decisions",
)

PROPERTY_MAP_KEYS = (
    "target",
    "name",
    "semantic_owner",
    "canonical_source",
    "purpose",
    "permitted_writer",
    "authority_class",
    "privacy_class",
    "retention_class",
    "schema_reference",
    "missing_behaviour",
    "stale_behaviour",
    "conflicting_behaviour",
    "not_evaluated_behaviour",
    "prohibited_implication",
    "normative_id",
)

REUSE_DECISIONS = frozenset(
    {"reuse", "do-not-reuse", "mirror-display-only", "historical-display-only"}
)

OPERATIONAL_PHASES = ("preflight", "verification", "rollback", "incident")

# Names retired by LP7's hardening comments; reintroducing one collapses the
# advisory/canonical distinction the whole design rests on.
RETIRED_NAMES = (
    "ready for teacher modeling",
    "lp pacing status",
    "advanced pathway status",
    "evidence score",
    "mastery score",
    "readiness score",
    "scanned work",
    "ocr transcript",
)


def _registry() -> dict:
    return load_registry(REGISTRY_PATH)


def _vocabulary(document: dict, key: str) -> set[str]:
    return {entry["value"] for entry in document["vocabularies"][key]}


def _validate_contract(document: dict) -> None:
    """Every invariant a conforming Change Request must satisfy."""
    assert tuple(document) == TOP_LEVEL_KEYS
    assert_contract_identity(document, registry_name="lp-notion-working-layer-change-request")
    assert_standards_exist(
        [
            document["normative_standard"],
            document["handoff_contract"],
            document["reason_code_catalog"],
            document["authority_state_registry"],
        ]
    )
    assert_normative_ids_match_anchors(document, [document["normative_standard"]])
    assert_no_forbidden_governed_keys(document)

    # LP7 designs; it never authorizes.
    assert document["change_request_state"] == "proposed-not-authorized"
    assert document["live_change_authorized"] is False
    assert document["pilot_execution_authorized"] is False
    assert document["shadow_mode_only"] is True
    assert type(document["live_change_authorized"]) is bool
    assert type(document["pilot_execution_authorized"]) is bool
    assert type(document["shadow_mode_only"]) is bool
    assert document["inspection"]["mode"] == "read-only"
    assert document["inspection"]["scope"] == "schema-and-view-configuration-only"
    assert document["inspection"]["records_read"] is False
    assert document["inspection"]["student_data_read"] is False

    target_ids = {target["id"] for target in document["exact_targets"]}
    assert len(target_ids) == len(document["exact_targets"])
    for target in document["exact_targets"]:
        if target["exists"]:
            assert target["notion_id"], f"{target['id']} exists but names no identifier"
        else:
            # A database that does not exist yet cannot claim an identifier.
            assert target["notion_id"] is None
            assert target["data_source_url"] is None

    authority_classes = _vocabulary(document, "authority_classes")
    privacy_classes = _vocabulary(document, "privacy_classes")
    retention_classes = _vocabulary(document, "retention_classes")
    writers = _vocabulary(document, "permitted_writers")

    for record in document["observed_properties"]:
        assert record["target"] in target_ids
        assert record["reuse_decision"] in REUSE_DECISIONS
        assert record["finding"], f"{record['property']} records no finding"

    proposed = document["proposed_properties"]
    assert proposed, "the Change Request proposes nothing"
    for record in proposed:
        name = record["name"]
        assert tuple(record) == PROPERTY_MAP_KEYS, f"{name} has an incomplete authority map"
        assert record["target"] in target_ids
        assert record["authority_class"] in authority_classes
        assert record["privacy_class"] in privacy_classes
        assert record["retention_class"] in retention_classes
        assert record["permitted_writer"] in writers
        assert record["schema_reference"], f"{name} names no schema reference"
        assert record["missing_behaviour"], f"{name} does not define missing behaviour"
        assert record["stale_behaviour"], f"{name} does not define stale behaviour"
        assert record["conflicting_behaviour"], (
            f"{name} does not define conflicting behaviour"
        )
        assert record["not_evaluated_behaviour"], (
            f"{name} does not define NOT_EVALUATED behaviour"
        )
        assert record["prohibited_implication"], f"{name} names no prohibited implication"

    for view in document["proposed_views"]:
        assert view["target"] in target_ids

    diagnosis_names = {
        record["name"]
        for record in proposed
        if record["target"] == "lesson-pacing-and-pathways"
    }
    required_diagnosis_names = {
        "Instructional Demand — Advisory",
        "Learner Relative Familiarity — Advisory",
        "Language and Representation Load — Advisory",
        "Material-Induced Load — Advisory",
        "Operational Load — Advisory",
        "Evidence Uncertainty — Advisory",
    }
    assert required_diagnosis_names <= diagnosis_names
    assert "Difficulty Diagnosis — Six Dimensions" not in diagnosis_names

    pilot_keys = (
        "id",
        "minimum_fields",
        "provisional_timing_range_required",
        "route_briefs_required",
        "synthetic_evidence_summary",
        "diagnostic_dimensions",
        "manual_review_questions",
        "post_lesson_aggregate_evidence",
        "usefulness_criteria",
        "rollback_deletion_expectations",
    )
    expected_dimensions = {
        "instructional_demand",
        "learner_relative_familiarity",
        "language_and_representation_load",
        "material_induced_load",
        "operational_load",
        "evidence_uncertainty",
    }

    assert len(document["pilot_records"]) == 3
    for record in document["pilot_records"]:
        assert tuple(record) == pilot_keys
        assert record["provisional_timing_range_required"] is True
        assert record["minimum_fields"] >= 1
        assert set(record["diagnostic_dimensions"]) == expected_dimensions
        assert record["manual_review_questions"]
        assert record["post_lesson_aggregate_evidence"]
        assert record["usefulness_criteria"]
        assert record["rollback_deletion_expectations"]

    for phase in OPERATIONAL_PHASES:
        assert document["operational_plan"][phase], f"{phase} plan is empty"

    assert document["unresolved_decisions"], "an empty decision list hides open questions"
    for decision in document["unresolved_decisions"]:
        assert decision["owner"], f"{decision['id']} names no human owner"
        assert decision["blocks_live_change"] is True


def test_change_request_and_standard_are_consistent() -> None:
    _validate_contract(_registry())


def test_canonical_serialization_is_stable() -> None:
    assert_canonical_serialization_is_stable(_registry())


def test_no_retired_name_is_reintroduced() -> None:
    document = _registry()
    proposed = [record["name"] for record in document["proposed_properties"]]
    proposed += [view["name"] for view in document["proposed_views"]]
    for name in proposed:
        lowered = name.lower()
        for retired in RETIRED_NAMES:
            assert retired not in lowered, f"{name} reintroduces a retired pattern"


def test_prohibited_data_covers_every_named_artifact_class() -> None:
    """The prohibition list is the design's hard floor; it must stay complete."""
    prohibited = {entry["value"] for entry in _registry()["prohibited_data"]}
    required = {
        "raw-scans-or-page-images",
        "cropped-answer-regions",
        "handwriting-samples",
        "full-recognized-responses-or-transcripts",
        "answer-level-or-learner-level-histories",
        "student-names-or-identifiers",
        "diagnoses-or-protected-characteristics",
        "row-per-student-records",
        "permanent-ability-labels",
        "model-internals-or-embeddings",
        "opaque-similarity-percentage",
        "continuous-telemetry",
    }
    assert required <= prohibited


def test_restricted_evidence_is_governed_by_lp10_retention() -> None:
    for record in _registry()["proposed_properties"]:
        if record["privacy_class"] == "lp10-restricted":
            assert record["retention_class"] == "lp10-governed", (
                f"{record['name']} holds restricted evidence without LP10 retention"
            )


def test_display_only_mirrors_are_never_written_by_the_pacing_lane() -> None:
    """A mirrored gate is read-only here; its owner writes it in its own record."""
    document = _registry()
    mirrored = [
        record for record in document["observed_properties"]
        if record["reuse_decision"] == "mirror-display-only"
    ]
    assert mirrored, "no gate mirror recorded"
    proposed_names = {record["name"] for record in document["proposed_properties"]}
    for record in mirrored:
        assert record["property"] not in proposed_names


def test_diagnosis_dimensions_are_six_separate_properties() -> None:
    names = {
        record["name"]
        for record in _registry()["proposed_properties"]
        if record["target"] == "lesson-pacing-and-pathways"
    }

    required = {
        "Instructional Demand — Advisory",
        "Learner Relative Familiarity — Advisory",
        "Language and Representation Load — Advisory",
        "Material-Induced Load — Advisory",
        "Operational Load — Advisory",
        "Evidence Uncertainty — Advisory",
    }

    assert required <= names
    assert "Difficulty Diagnosis — Six Dimensions" not in names


def test_pilot_covers_three_lesson_patterns() -> None:
    records = _registry()["pilot_records"]
    assert len(records) == 3

    required_keys = (
        "id",
        "minimum_fields",
        "provisional_timing_range_required",
        "route_briefs_required",
        "synthetic_evidence_summary",
        "diagnostic_dimensions",
        "manual_review_questions",
        "post_lesson_aggregate_evidence",
        "usefulness_criteria",
        "rollback_deletion_expectations",
    )

    expected_dimensions = {
        "instructional_demand",
        "learner_relative_familiarity",
        "language_and_representation_load",
        "material_induced_load",
        "operational_load",
        "evidence_uncertainty",
    }

    for record in records:
        assert tuple(record) == required_keys
        assert record["provisional_timing_range_required"] is True
        assert record["minimum_fields"] >= 1
        assert set(record["diagnostic_dimensions"]) == expected_dimensions
        assert record["manual_review_questions"]
        assert record["post_lesson_aggregate_evidence"]
        assert record["usefulness_criteria"]
        assert record["rollback_deletion_expectations"]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("record_revision: 1", "record_revision: 1\nrecord_revision: 2"),
        ("inspection:", "alias_source: &shared value\nalias_copy: *shared\ninspection:"),
        ("inspection:", "merged: {<<: {value: bad}}\ninspection:"),
        ("inspection:", "tagged: !custom bad\ninspection:"),
        ("record_revision: 1", "record_revision: 1.5"),
    ],
)
def test_hostile_yaml_documents_fail_closed(old: str, new: str) -> None:
    text = read_text(REGISTRY_PATH).replace(old, new, 1)
    with pytest.raises((AssertionError, ValueError, yaml.YAMLError)):
        _validate_contract(load_yaml_text(text))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # The Change Request quietly authorizing itself.
        ("live_change_authorized: false", "live_change_authorized: true"),
        ("pilot_execution_authorized: false", "pilot_execution_authorized: true"),
        ("shadow_mode_only: true", "shadow_mode_only: false"),
        ("change_request_state: proposed-not-authorized", "change_request_state: authorized"),
        # An unresolved decision downgraded so it no longer blocks.
        ("    blocks_live_change: true", "    blocks_live_change: false"),
        # A proposed property losing part of its authority map.
        (
            "    schema_reference: lp7-property-pacing-feasibility-advisory\n"
            "    missing_behaviour: display NOT_EVALUATED\n"
            "    stale_behaviour: display stale and require manual review\n"
            "    conflicting_behaviour: display conflicting and require manual review\n"
            "    not_evaluated_behaviour: display NOT_EVALUATED\n",
            "",
        ),
        # Read-only inspection widened to records.
        ("  records_read: false", "  records_read: true"),
        # Six distinct diagnosis properties collapsed back into one aggregate.
        (
            "    name: Instructional Demand — Advisory",
            "    name: Difficulty Diagnosis — Six Dimensions",
        ),
        # A pilot record loses an explicit per-record requirement.
        (
            "    manual_review_questions:\n"
            "      - which estimate remains uncertain\n"
            "      - which owner decision remains unresolved\n",
            "",
        ),
        (
            "  scope: schema-and-view-configuration-only",
            "  scope: records-and-content",
        ),
    ],
)
def test_authorization_and_completeness_violations_are_rejected(old: str, new: str) -> None:
    base = read_text(REGISTRY_PATH)
    text = base.replace(old, new, 1)
    assert text != base, "mutation did not apply"
    with pytest.raises((AssertionError, ValueError, KeyError)):
        _validate_contract(load_yaml_text(text))
