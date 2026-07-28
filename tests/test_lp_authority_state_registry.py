from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from yaml.nodes import MappingNode

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_PATH = ROOT / "01_Shared_Standards" / "instructional-design" / "lp-authority-state-registry.md"
REGISTRY_PATH = ROOT / "04_Registry" / "lp-authority-state-registry.yaml"

TOP_LEVEL_KEYS = (
    "registry_name",
    "contract_version",
    "record_revision",
    "normative_standard",
    "bounds",
    "namespaces",
    "gate_states",
    "compatibility_states",
    "legacy_aliases",
    "non_authority_evidence",
)
GATE_STATES = ("NOT_EVALUATED", "BLOCKED", "CLEARED", "REVOKED")
COMPATIBILITY_STATES = (
    "compatible",
    "migration-required",
    "unsupported",
    "conflicting",
    "manual-review-required",
)
BOUND_MAXIMA = {
    "reason_codes": 16,
    "source_references": 20,
    "unresolved_uncertainties": 12,
    "explanations": 12,
}
FORBIDDEN_GOVERNED_KEYS = {"status", "ready", "approved", "authorized"}
EXACT_TYPES = {dict, list, str, int, bool, type(None)}


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: UniqueKeyLoader, node: MappingNode, deep: bool = False) -> dict:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _load_text(text: str) -> dict:
    if re.search(r"(^|\s)(?:&|\*)[A-Za-z0-9_-]+", text):
        raise ValueError("YAML anchors and aliases are forbidden")
    if re.search(r"(^|\s)<<\s*:", text, flags=re.MULTILINE):
        raise ValueError("YAML merge keys are forbidden")
    if re.search(r"(^|\s)![A-Za-z]", text):
        raise ValueError("custom YAML tags are forbidden")
    loaded = yaml.load(text, Loader=UniqueKeyLoader)
    if type(loaded) is not dict:
        raise ValueError("registry must be an exact mapping")
    _validate_exact_types(loaded)
    return loaded


def _validate_exact_types(value: Any, *, depth: int = 0) -> None:
    if depth > 20:
        raise ValueError("unexpected nesting depth")
    if type(value) not in EXACT_TYPES:
        raise ValueError(f"unsupported YAML type: {type(value).__name__}")
    if type(value) is dict:
        for key, nested in value.items():
            if type(key) is not str:
                raise ValueError("mapping keys must be exact strings")
            _validate_exact_types(nested, depth=depth + 1)
    elif type(value) is list:
        for nested in value:
            _validate_exact_types(nested, depth=depth + 1)


def _load_registry() -> dict:
    return _load_text(REGISTRY_PATH.read_text(encoding="utf-8"))


def _anchors(markdown: str) -> tuple[str, ...]:
    headings = re.findall(r"^### ([a-z0-9]+(?:-[a-z0-9]+)*)$", markdown, flags=re.MULTILINE)
    return tuple(headings)


def _records(document: dict) -> list[dict]:
    records: list[dict] = []
    for bound in document["bounds"].values():
        records.append(bound)
    for namespace in document["namespaces"].values():
        records.extend(namespace)
    for key in ("gate_states", "compatibility_states", "legacy_aliases", "non_authority_evidence"):
        records.extend(document[key])
    return records


def _assert_no_forbidden_governed_keys(value: Any, *, inside_legacy_alias: bool = False) -> None:
    if type(value) is dict:
        for key, nested in value.items():
            if key in FORBIDDEN_GOVERNED_KEYS and not inside_legacy_alias:
                raise AssertionError(f"forbidden governed key: {key}")
            _assert_no_forbidden_governed_keys(
                nested,
                inside_legacy_alias=inside_legacy_alias or key == "legacy_aliases",
            )
    elif type(value) is list:
        for nested in value:
            _assert_no_forbidden_governed_keys(nested, inside_legacy_alias=inside_legacy_alias)


def _validate_contract(document: dict) -> None:
    assert tuple(document) == TOP_LEVEL_KEYS
    assert document["registry_name"] == "lp-authority-state-registry"
    assert document["contract_version"] == "1.0"
    assert type(document["record_revision"]) is int and document["record_revision"] == 1
    assert document["normative_standard"] == MARKDOWN_PATH.relative_to(ROOT).as_posix()
    assert MARKDOWN_PATH.exists()

    assert {key: value["maximum"] for key, value in document["bounds"].items()} == BOUND_MAXIMA
    assert tuple(record["value"] for record in document["gate_states"]) == GATE_STATES
    assert "CONDITIONALLY_CLEARED" not in GATE_STATES
    assert tuple(record["value"] for record in document["compatibility_states"]) == COMPATIBILITY_STATES

    records = _records(document)
    normative_ids = [record["normative_id"] for record in records]
    assert len(normative_ids) == len(set(normative_ids))
    markdown_anchors = _anchors(MARKDOWN_PATH.read_text(encoding="utf-8"))
    assert len(markdown_anchors) == len(set(markdown_anchors))
    assert set(normative_ids) == set(markdown_anchors)

    namespace_values = {
        name: tuple(record["value"] for record in records)
        for name, records in document["namespaces"].items()
    }
    assert set(namespace_values) == {
        "advisory_assessment_outcomes",
        "routing_recommendations",
        "deployment_lifecycle_states",
    }
    all_namespace_values = [value for values in namespace_values.values() for value in values]
    assert len(all_namespace_values) == len(set(all_namespace_values))
    assert not set(namespace_values["advisory_assessment_outcomes"]) & set(GATE_STATES)

    for alias in document["legacy_aliases"]:
        assert alias["display_only"] is True
        assert alias["authority_advancing"] is False
        assert alias["migration_review_required"] is True
        assert alias["preserve_original_literal"] is True
    for evidence in document["non_authority_evidence"]:
        assert evidence["authority_advancing"] is False

    _assert_no_forbidden_governed_keys(document)


def test_registry_and_markdown_are_consistent() -> None:
    _validate_contract(_load_registry())


def test_canonical_serialization_is_stable() -> None:
    document = _load_registry()
    first = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    second = yaml.safe_dump(_load_text(first), sort_keys=False, allow_unicode=True)
    assert first == second
    assert tuple(_load_text(first)) == TOP_LEVEL_KEYS


def test_gate_and_compatibility_enums_are_exact() -> None:
    document = _load_registry()
    assert tuple(record["value"] for record in document["gate_states"]) == GATE_STATES
    assert tuple(record["value"] for record in document["compatibility_states"]) == COMPATIBILITY_STATES


@pytest.mark.parametrize(
    "replacement",
    [
        'contract_version: "2.0"',
        'contract_version: "1.0"\nfuture_contract_version: "2.0"',
        'contract_version: "retired"',
    ],
)
def test_unknown_future_mixed_and_retired_versions_fail_closed(replacement: str) -> None:
    text = REGISTRY_PATH.read_text(encoding="utf-8").replace('contract_version: "1.0"', replacement, 1)
    with pytest.raises((AssertionError, ValueError)):
        _validate_contract(_load_text(text))


def test_conditionally_cleared_is_rejected() -> None:
    text = REGISTRY_PATH.read_text(encoding="utf-8").replace(
        "  - value: REVOKED\n    normative_id: gate-revoked",
        "  - value: REVOKED\n    normative_id: gate-revoked\n"
        "  - value: CONDITIONALLY_CLEARED\n    normative_id: gate-conditionally-cleared",
    )
    with pytest.raises(AssertionError):
        _validate_contract(_load_text(text))


def test_generic_governed_status_key_is_rejected() -> None:
    text = REGISTRY_PATH.read_text(encoding="utf-8").replace(
        "registry_name: lp-authority-state-registry",
        "registry_name: lp-authority-state-registry\nstatus: ready",
        1,
    )
    with pytest.raises(AssertionError):
        _validate_contract(_load_text(text))


def test_duplicate_keys_aliases_merge_keys_tags_timestamps_and_floats_fail_closed() -> None:
    base = REGISTRY_PATH.read_text(encoding="utf-8")
    hostile_documents = (
        base.replace("record_revision: 1", "record_revision: 1\nrecord_revision: 2", 1),
        base.replace("bounds:", "alias_source: &shared value\nalias_copy: *shared\nbounds:", 1),
        base.replace("bounds:", "merged: {<<: {value: bad}}\nbounds:", 1),
        base.replace("bounds:", "tagged: !custom bad\nbounds:", 1),
        base.replace("record_revision: 1", "record_revision: 2026-07-27", 1),
        base.replace("record_revision: 1", "record_revision: 1.5", 1),
    )
    for text in hostile_documents:
        with pytest.raises((AssertionError, ValueError, yaml.YAMLError)):
            _validate_contract(_load_text(text))


def test_bounds_are_exact_and_boundary_plus_one_is_rejected() -> None:
    document = _load_registry()
    for key, maximum in BOUND_MAXIMA.items():
        assert len([f"value-{index}" for index in range(maximum)]) == maximum
        assert len([f"value-{index}" for index in range(maximum + 1)]) > document["bounds"][key]["maximum"]


def test_pacing_feasible_can_coexist_with_alignment_blocked() -> None:
    supplied_record = {
        "pacing_assessment": "feasible",
        "alignment_gate": "BLOCKED",
    }
    document = _load_registry()
    assert supplied_record["pacing_assessment"] in {
        record["value"] for record in document["namespaces"]["advisory_assessment_outcomes"]
    }
    assert supplied_record["alignment_gate"] in {
        record["value"] for record in document["gate_states"]
    }


def test_missing_gate_resolves_only_to_not_evaluated() -> None:
    supplied_record: dict[str, str] = {}
    resolved_gate = supplied_record.get("alignment_gate", "NOT_EVALUATED")
    assert resolved_gate == "NOT_EVALUATED"
    assert resolved_gate != "CLEARED"


def test_existing_owner_and_readiness_files_are_not_modified_by_this_change() -> None:
    expected_changed_paths = {
        MARKDOWN_PATH.relative_to(ROOT).as_posix(),
        REGISTRY_PATH.relative_to(ROOT).as_posix(),
        Path(__file__).resolve().relative_to(ROOT).as_posix(),
    }
    assert "04_Registry/responsibility-matrix.md" not in expected_changed_paths
    assert all("readiness" not in path for path in expected_changed_paths)
