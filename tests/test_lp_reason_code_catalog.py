"""Structural tests for the LP15 reason-code catalog (issue #711).

The catalog holds LP domain semantics only. Generic parsing, bounds, version,
serialization, and authority mechanics belong to LP9, LP12, and CW5A, so these
tests prove the catalog delegates rather than duplicates, that every code has one
owner and one stable cause, and that no code can be read as a result
classification, an authority state, or a permission.
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
    read_text,
)

REGISTRY_PATH = "04_Registry/lp-reason-code-catalog.yaml"
AUTHORITY_REGISTRY_PATH = "04_Registry/lp-authority-state-registry.yaml"
HANDOFF_REGISTRY_PATH = "04_Registry/lp-pacing-handoff-contract.yaml"

TOP_LEVEL_KEYS = (
    "registry_name",
    "contract_version",
    "record_revision",
    "normative_standard",
    "authority_state_registry",
    "handoff_contract",
    "bounds",
    "semantic_owners",
    "result_families",
    "prohibited_implication_vocabulary",
    "required_evidence_vocabulary",
    "normative_references",
    "families",
    "naming_rules",
    "record_rules",
    "ownership_rules",
    "result_rules",
    "diagnosis_rules",
    "exclusions",
    "deprecation_rules",
    "codes",
)

CODE_RECORD_KEYS = (
    "code",
    "family",
    "semantic_owner",
    "normative_reference",
    "summary",
    "trigger",
    "required_evidence",
    "allowed_result_families",
    "manual_review_required",
    "privacy_sensitive",
    "prohibited_implications",
    "deprecated",
    "replacement_code",
)

_CODE_RE = re.compile(r"^lp-[a-z0-9]+(?:-[a-z0-9]+)+$")

# Every LP reason must foreclose these implications, without exception.
BASELINE_PROHIBITED = frozenset(
    {"gate-advancement", "readiness", "grading", "placement", "production", "external-write"}
)

# Generic mechanics belong to LP9/LP12/CW5A. An active LP code naming one of
# these is a duplication of another owner's contract.
GENERIC_TOKENS = frozenset(
    {
        "invalid",
        "malformed",
        "bad",
        "data",
        "unknown",
        "unsupported",
        "serialization",
        "import",
        "json",
        "depth",
        "oversized",
        "syntax",
    }
)

# Language that would turn a task-and-evidence description into a learner label.
LEARNER_LABEL_TOKENS = ("gifted", "incapable", "slow learner", "low ability", "high ability")


def _registry() -> dict:
    return load_registry(REGISTRY_PATH)


def _vocabulary(document: dict, key: str) -> set[str]:
    return {entry["value"] for entry in document[key]}


def _validate_contract(document: dict) -> None:
    """Every invariant a conforming catalog must satisfy, in one reusable pass."""
    assert tuple(document) == TOP_LEVEL_KEYS
    assert_contract_identity(document, registry_name="lp-reason-code-catalog")
    assert_standards_exist(
        [
            document["normative_standard"],
            document["authority_state_registry"],
            document["handoff_contract"],
        ]
    )
    assert_normative_ids_match_anchors(document, [document["normative_standard"]])
    assert_no_forbidden_governed_keys(document)

    owners = {owner["id"] for owner in document["semantic_owners"]}
    references = {reference["id"] for reference in document["normative_references"]}
    result_families = _vocabulary(document, "result_families")
    prohibited_vocabulary = _vocabulary(document, "prohibited_implication_vocabulary")
    evidence_vocabulary = _vocabulary(document, "required_evidence_vocabulary")
    assert BASELINE_PROHIBITED <= prohibited_vocabulary

    families = {family["id"]: family for family in document["families"]}
    assert len(families) == len(document["families"])
    for family in families.values():
        assert family["semantic_owner"] in owners
        assert family["normative_reference"] in references
        assert set(family["allowed_result_families"]) <= result_families
        assert family["authorized_producers"], "a family must declare its producers"
        assert family["authorized_consumers"], "a family must declare its consumers"

    max_evidence = document["bounds"]["required_evidence_per_code"]["maximum"]
    max_prohibited = document["bounds"]["prohibited_implications_per_code"]["maximum"]

    codes = document["codes"]
    identifiers = [record["code"] for record in codes]
    assert len(identifiers) == len(set(identifiers)), "duplicate reason code"
    summaries = [record["summary"] for record in codes]
    assert len(summaries) == len(set(summaries)), "synonym codes share one meaning"

    active_families: set[str] = set()
    for record in codes:
        code = record["code"]
        assert tuple(record) == CODE_RECORD_KEYS, f"{code} record shape drifted"
        assert _CODE_RE.match(code), f"{code} is outside the lp-* namespace"

        family = families[record["family"]]
        assert record["semantic_owner"] == family["semantic_owner"], f"{code} owner conflict"
        assert record["normative_reference"] == family["normative_reference"]
        assert record["allowed_result_families"] == family["allowed_result_families"]

        assert record["summary"] and record["trigger"], f"{code} has no stated cause"
        assert 1 <= len(record["required_evidence"]) <= max_evidence
        assert set(record["required_evidence"]) <= evidence_vocabulary
        assert 1 <= len(record["prohibited_implications"]) <= max_prohibited
        assert set(record["prohibited_implications"]) <= prohibited_vocabulary
        assert BASELINE_PROHIBITED <= set(record["prohibited_implications"]), (
            f"{code} does not foreclose the baseline implications"
        )
        assert type(record["manual_review_required"]) is bool
        assert type(record["privacy_sensitive"]) is bool

        if record["deprecated"]:
            replacement = record["replacement_code"]
            assert replacement is None or replacement in set(identifiers)
        else:
            assert record["replacement_code"] is None, f"{code} is active but names a replacement"
            segments = set(code.split("-"))
            named = segments & GENERIC_TOKENS
            assert not named, f"{code} duplicates generic mechanics: {sorted(named)}"
            active_families.add(record["family"])

    assert active_families == set(families), "every family needs at least one active code"

    for record in codes:
        if families[record["family"]]["id"] == "privacy-and-disclosure":
            assert record["privacy_sensitive"] is True


def test_catalog_and_normative_standard_are_consistent() -> None:
    _validate_contract(_registry())


def test_canonical_serialization_is_stable() -> None:
    assert_canonical_serialization_is_stable(_registry())


def test_reason_codes_never_collide_with_authority_or_result_values() -> None:
    """A reason explains a result; it is never a classification or a gate state."""
    document = _registry()
    authority = load_registry(AUTHORITY_REGISTRY_PATH)
    reserved = {record["value"] for record in authority["gate_states"]}
    for namespace in authority["namespaces"].values():
        reserved.update(record["value"] for record in namespace)
    reserved.update(_vocabulary(document, "result_families"))
    assert not {record["code"] for record in document["codes"]} & reserved


def test_result_bound_matches_the_authority_registry() -> None:
    document = _registry()
    authority = load_registry(AUTHORITY_REGISTRY_PATH)
    assert (
        document["bounds"]["reason_codes_per_result"]["maximum"]
        == authority["bounds"]["reason_codes"]["maximum"]
    )


def test_demand_diagnosis_references_the_handoff_contract_dimensions() -> None:
    """LP15 names causes for the same six dimensions LP3 separates."""
    handoff = load_registry(HANDOFF_REGISTRY_PATH)
    dimensions = {item["value"].replace("_", "-") for item in handoff["diagnosis_dimensions"]}
    demand_codes = [
        record["code"] for record in _registry()["codes"] if record["family"] == "demand-diagnosis"
    ]
    assert len(demand_codes) == len(dimensions)


def test_no_code_labels_a_learner() -> None:
    document = _registry()
    for record in document["codes"]:
        text = f"{record['code']} {record['summary']} {record['trigger']}".lower()
        for token in LEARNER_LABEL_TOKENS:
            assert token not in text, f"{record['code']} labels a learner"


def test_deprecated_generic_code_is_retained_only_as_history() -> None:
    """The retired generic code proves the exclusion rule bites."""
    codes = {record["code"]: record for record in _registry()["codes"]}
    retired = codes["lp-evidence-bad-data"]
    assert retired["deprecated"] is True
    assert retired["replacement_code"] is None
    assert set(retired["code"].split("-")) & GENERIC_TOKENS

    superseded = codes["lp-pacing-not-enough-time"]
    assert superseded["deprecated"] is True
    assert codes[superseded["replacement_code"]]["deprecated"] is False


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("record_revision: 1", "record_revision: 1\nrecord_revision: 2"),
        ("bounds:", "alias_source: &shared value\nalias_copy: *shared\nbounds:"),
        ("bounds:", "merged: {<<: {value: bad}}\nbounds:"),
        ("bounds:", "tagged: !custom bad\nbounds:"),
        ("record_revision: 1", "record_revision: 1.5"),
        ("registry_name: lp-reason-code-catalog", "registry_name: lp-reason-code-catalog\nstatus: ready"),
    ],
)
def test_hostile_yaml_documents_fail_closed(old: str, new: str) -> None:
    text = read_text(REGISTRY_PATH).replace(old, new, 1)
    with pytest.raises((AssertionError, ValueError, yaml.YAMLError)):
        _validate_contract(load_yaml_text(text))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # A code that quietly drops a baseline prohibition.
        ("  - production\n  - readiness\n", "  - production\n"),
        # A second owner claiming an existing code.
        ("  semantic_owner: unit-alignment-agent\n", "  semantic_owner: qa-test-agent\n"),
        # A generic mechanics code reintroduced as active.
        (
            "- code: lp-pacing-time-budget-missing\n",
            "- code: lp-handoff-invalid-json\n",
        ),
    ],
)
def test_ownership_and_delegation_violations_are_rejected(old: str, new: str) -> None:
    base = read_text(REGISTRY_PATH)
    text = base.replace(old, new, 1)
    assert text != base, "mutation did not apply"
    with pytest.raises((AssertionError, ValueError, KeyError)):
        _validate_contract(load_yaml_text(text))
