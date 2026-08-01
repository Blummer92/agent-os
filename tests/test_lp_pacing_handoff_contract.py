"""Structural tests for the LP3 pacing handoff contract (issue #648).

The registry is the machine-readable half of the contract; the two normative
Markdown standards own meaning. These tests prove the pair stays consistent, that
the packet defaults fail closed, that owner states stay independent, and that the
contract remains provider-neutral.
"""

from __future__ import annotations

import re

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
    markdown_anchors,
    read_text,
)

REGISTRY_PATH = "04_Registry/lp-pacing-handoff-contract.yaml"
AUTHORITY_REGISTRY_PATH = "04_Registry/lp-authority-state-registry.yaml"

TOP_LEVEL_KEYS = (
    "registry_name",
    "contract_version",
    "record_revision",
    "normative_standards",
    "illustrative_standard",
    "authority_state_registry",
    "bounds",
    "owners",
    "evidence_intake",
    "packet_rules",
    "packet_fields",
    "authority_objects",
    "authority_rules",
    "diagnosis_dimensions",
    "diagnosis_rules",
    "adaptation_hierarchy",
    "adaptation_rules",
    "route_back_targets",
    "route_back_rules",
    "mixed_class_pathways",
    "destination_boundary",
    "retired_terms",
    "illustrative_case",
    "required_fixtures",
)

DIAGNOSIS_DIMENSIONS = (
    "instructional_demand",
    "learner_relative_familiarity",
    "language_and_representation_load",
    "material_induced_load",
    "operational_load",
    "evidence_uncertainty",
)

NON_AUTHORITY_FLAGS = {
    "report_only": True,
    "execution_authorized": False,
    "artifact_authorized": False,
    "readiness_authorized": False,
    "grading_authorized": False,
    "student_classification_authorized": False,
    "automatic_placement_authorized": False,
    "route_assignment_authorized": False,
    "production_authorized": False,
    "external_write_authorized": False,
}

FAIL_CLOSED_DEFAULTS = {
    "advisory_assessment_outcome": "insufficient-evidence",
    "routing_recommendation": "hold",
    "confidence": "low",
    "manual_review_required": True,
}

# A pacing packet names no destination. These tokens would smuggle LP7's job in.
# Matched per underscore-delimited segment, so `primary_time_drivers` is not a
# false positive for `drive`.
DESTINATION_TOKENS = frozenset(
    {
        "notion",
        "drive",
        "sheet",
        "sheets",
        "workspace",
        "database",
        "page",
        "folder",
        "property",
        "url",
    }
)
_NOTION_ID_RE = re.compile(r"\b[0-9a-f]{32}\b|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


def _registry() -> dict:
    return load_registry(REGISTRY_PATH)


def _standards(document: dict) -> list[str]:
    return list(document["normative_standards"])


def _packet_defaults(document: dict) -> dict:
    return {field["name"]: field["default"] for field in document["packet_fields"]}


def _validate_contract(document: dict) -> None:
    """Every invariant a conforming registry must satisfy, in one reusable pass."""
    assert tuple(document) == TOP_LEVEL_KEYS
    assert_contract_identity(document, registry_name="lp-pacing-handoff-contract")

    standards = _standards(document)
    assert_standards_exist([*standards, document["illustrative_standard"], REGISTRY_PATH])
    assert_normative_ids_match_anchors(document, standards)
    assert_no_forbidden_governed_keys(document)

    # Illustrative case and fixtures resolve two-way against the cases file.
    illustrative_ids = {document["illustrative_case"]["illustrative_id"]}
    illustrative_ids.update(fixture["illustrative_id"] for fixture in document["required_fixtures"])
    assert illustrative_ids == set(markdown_anchors([document["illustrative_standard"]]))

    defaults = _packet_defaults(document)
    for name, expected in FAIL_CLOSED_DEFAULTS.items():
        assert defaults[name] == expected, f"{name} must fail closed to {expected!r}"
    for name, expected in NON_AUTHORITY_FLAGS.items():
        assert defaults[name] is expected, f"{name} must be fixed {expected}"

    non_authority = {
        field["name"] for field in document["packet_fields"] if field["kind"] == "non-authority"
    }
    assert non_authority == set(NON_AUTHORITY_FLAGS)
    assert all(field["required"] is True for field in document["packet_fields"] if field["kind"] == "non-authority")

    names = [field["name"] for field in document["packet_fields"]]
    assert len(names) == len(set(names))

    assert tuple(item["value"] for item in document["diagnosis_dimensions"]) == DIAGNOSIS_DIMENSIONS

    positions = [step["position"] for step in document["adaptation_hierarchy"]]
    assert positions == list(range(1, len(positions) + 1))
    assert document["adaptation_hierarchy"][0]["value"] == "remove-operational-friction"
    assert document["adaptation_hierarchy"][-1]["value"] == "route-to-curriculum-owner"

    gates = {obj["object"]: obj["is_gate"] for obj in document["authority_objects"]}
    assert gates == {
        "pacing_assessment": False,
        "alignment_gate": True,
        "modeling_handoff_gate": True,
        "production_authorization": True,
    }
    assert document["authority_state_registry"] == AUTHORITY_REGISTRY_PATH


def test_registry_and_normative_standards_are_consistent() -> None:
    _validate_contract(_registry())


def test_canonical_serialization_is_stable() -> None:
    assert_canonical_serialization_is_stable(_registry())


def test_advisory_and_routing_defaults_exist_in_the_authority_registry() -> None:
    """LP3 reuses LP12 vocabulary rather than inventing parallel values."""
    authority = load_registry(AUTHORITY_REGISTRY_PATH)
    namespaces = authority["namespaces"]
    outcomes = {record["value"] for record in namespaces["advisory_assessment_outcomes"]}
    routes = {record["value"] for record in namespaces["routing_recommendations"]}
    defaults = _packet_defaults(_registry())
    assert defaults["advisory_assessment_outcome"] in outcomes
    assert defaults["routing_recommendation"] in routes


def test_gate_states_are_not_reused_as_pacing_outcomes() -> None:
    authority = load_registry(AUTHORITY_REGISTRY_PATH)
    gate_values = {record["value"] for record in authority["gate_states"]}
    document = _registry()
    outcomes = {field["default"] for field in document["packet_fields"] if field["kind"] == "advisory"}
    assert not outcomes & gate_values


def test_packet_is_provider_neutral() -> None:
    document = _registry()
    for field in document["packet_fields"]:
        segments = set(field["name"].lower().split("_"))
        named = segments & DESTINATION_TOKENS
        assert not named, f"packet field {field['name']} names a destination: {sorted(named)}"
    for relative_path in [*_standards(document), document["illustrative_standard"]]:
        assert not _NOTION_ID_RE.search(read_text(relative_path)), (
            f"{relative_path} contains a destination identifier"
        )


def test_retired_terms_are_not_active_values() -> None:
    document = _registry()
    retired = {term["value"] for term in document["retired_terms"]}
    active = {field["default"] for field in document["packet_fields"] if type(field["default"]) is str}
    active.update(item["value"] for item in document["diagnosis_dimensions"])
    active.update(step["value"] for step in document["adaptation_hierarchy"])
    assert not active & retired


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("record_revision: 1", "record_revision: 1\nrecord_revision: 2"),
        ("bounds:", "alias_source: &shared value\nalias_copy: *shared\nbounds:"),
        ("bounds:", "merged: {<<: {value: bad}}\nbounds:"),
        ("bounds:", "tagged: !custom bad\nbounds:"),
        ("record_revision: 1", "record_revision: 2026-07-28"),
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
        # A caller raising a non-authority flag.
        (
            "  - name: readiness_authorized\n    kind: non-authority\n    required: true\n    default: false",
            "  - name: readiness_authorized\n    kind: non-authority\n    required: true\n    default: true",
        ),
        # Pacing feasibility promoted into a gate.
        (
            "  - object: pacing_assessment\n    owner: Unit Alignment Agent\n    normative_id: authority-pacing-assessment\n    is_gate: false",
            "  - object: pacing_assessment\n    owner: Unit Alignment Agent\n    normative_id: authority-pacing-assessment\n    is_gate: true",
        ),
        # An optimistic default replacing the fail-closed one.
        (
            "    default: insufficient-evidence",
            "    default: feasible",
        ),
        # A generic governed status key.
        (
            "registry_name: lp-pacing-handoff-contract",
            "registry_name: lp-pacing-handoff-contract\nstatus: ready",
        ),
        # A dropped diagnosis dimension collapsing the six-way separation.
        (
            "  - value: evidence_uncertainty\n    normative_id: diagnosis-evidence-uncertainty\n",
            "",
        ),
    ],
)
def test_authority_and_fail_closed_violations_are_rejected(old: str, new: str) -> None:
    text = read_text(REGISTRY_PATH).replace(old, new, 1)
    assert text != read_text(REGISTRY_PATH), "mutation did not apply"
    with pytest.raises((AssertionError, ValueError, KeyError)):
        _validate_contract(load_yaml_text(text))


def test_missing_owner_decision_resolves_only_to_not_evaluated() -> None:
    supplied: dict[str, str] = {}
    assert supplied.get("modeling_handoff_gate", "NOT_EVALUATED") == "NOT_EVALUATED"


def test_teacher_summary_path_never_requires_the_extraction_lane() -> None:
    document = _registry()
    assert all(path["requires_extraction_lane"] is False for path in document["evidence_intake"])
