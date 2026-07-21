"""Fixed-vector tests for the #471 registry-provenance contract (#482).

Golden digests are hard-coded literals, independently reproduced from the
committed fixtures; no expected value is produced by the implementation under
test. Equivalence vectors assert two snapshots share the single golden digest;
difference vectors assert they diverge from it; fail-closed vectors assert no
provenance value is produced.
"""

from __future__ import annotations

import copy
import unicodedata
from dataclasses import fields
from pathlib import Path

import pytest
import yaml

from reusable_capability_registry import (
    CapabilityRecord,
    Confidence,
    RegistryReader,
    discover_capabilities,
)
from reusable_capability_registry.models import (
    PROVENANCE_ALGORITHM,
    PROVENANCE_ALGORITHM_VERSION,
    RegistryProvenance,
    UnsupportedProvenanceError,
)
from reusable_capability_registry.provenance import (
    build_registry_provenance,
    compute_registry_provenance,
    provenance_for_registry,
)
from reusable_capability_registry.reader import (
    RegistryFormatError,
    UnsupportedRegistryVersion,
)
from reusable_capability_registry.serialization import (
    discovery_result_to_payload,
    serialize_discovery_results,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = FIXTURES / "provenance" / "base.yml"

# Independently reproduced golden digests (see the reference derivation in the
# PR description). The base fixture is the primary controlled vector; the live
# canonical registry vector doubles as a tripwire for any semantic registry edit.
GOLDEN_BASE_DIGEST = "7d183194102b8b40410e5fafab07eb5885e36f2e565de79b42290e1d23c344c6"
GOLDEN_LIVE_DIGEST = "6cccfc9e86387865c97d10eb7f782c589ebbf016cf507d0cb28c99f48e00a7be"

_HEX64 = "a" * 64


def _base_data() -> dict:
    return copy.deepcopy(yaml.safe_load(BASE.read_text(encoding="utf-8")))


def _write(tmp_path: Path, data: dict, *, name: str = "registry.yml", **dump_kwargs) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True, **dump_kwargs), encoding="utf-8")
    return path


def _digest_of_data(tmp_path: Path, data: dict, *, name: str = "registry.yml", **dump_kwargs) -> str:
    return provenance_for_registry(_write(tmp_path, data, name=name, **dump_kwargs)).digest


def _record(index: int, data: dict) -> dict:
    """Return the record dict for a given capability_id order-independent lookup."""
    return data["capabilities"][index]


def _find(data: dict, capability_id: str) -> dict:
    for record in data["capabilities"]:
        if record["capability_id"] == capability_id:
            return record
    raise AssertionError(capability_id)


# --- 1. canonical registry produces one fixed expected digest ---------------


def test_base_fixture_matches_hardcoded_golden_digest():
    provenance = provenance_for_registry(BASE)
    assert provenance.digest == GOLDEN_BASE_DIGEST
    assert provenance.algorithm == PROVENANCE_ALGORITHM == "registry-canonical-records"
    assert provenance.algorithm_version == PROVENANCE_ALGORITHM_VERSION == 1
    assert provenance.registry_version == "0.1.0"


def test_live_canonical_registry_matches_hardcoded_golden_digest():
    # Tripwire: this literal changes only when the canonical registry's parsed
    # content changes, which is exactly what provenance is meant to detect.
    assert provenance_for_registry().digest == GOLDEN_LIVE_DIGEST


def test_digest_is_64_lowercase_hex():
    digest = provenance_for_registry(BASE).digest
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(character in "0123456789abcdef" for character in digest)


# --- 2. repeated calculation is identical -----------------------------------


def test_repeated_calculation_is_identical():
    first = provenance_for_registry(BASE)
    second = provenance_for_registry(BASE)
    assert first == second
    assert first.digest == second.digest == GOLDEN_BASE_DIGEST
    reader = RegistryReader(BASE)
    assert compute_registry_provenance(reader) == first
    assert build_registry_provenance(reader.records, "0.1.0").digest == GOLDEN_BASE_DIGEST


# --- 3-8. formatting / ordering / missing-vs-empty preserve identity --------


def test_formatting_only_changes_preserve_provenance(tmp_path):
    data = _base_data()
    # Round-tripping through safe_dump re-quotes, re-indents, and re-orders
    # mapping keys while preserving parsed values.
    assert _digest_of_data(tmp_path, data, default_flow_style=False) == GOLDEN_BASE_DIGEST
    assert _digest_of_data(tmp_path, data, default_flow_style=True, name="flow.yml") == GOLDEN_BASE_DIGEST
    assert _digest_of_data(tmp_path, data, indent=8, width=200, name="wide.yml") == GOLDEN_BASE_DIGEST


def test_mapping_key_order_changes_preserve_provenance(tmp_path):
    data = _base_data()
    reordered = {"capabilities": data["capabilities"], "registry_version": data["registry_version"]}
    # safe_dump(sort_keys=True) canonicalizes key order regardless of input order.
    assert _digest_of_data(tmp_path, reordered) == GOLDEN_BASE_DIGEST


def test_capability_order_changes_preserve_provenance(tmp_path):
    data = _base_data()
    data["capabilities"] = list(reversed(data["capabilities"]))
    assert _digest_of_data(tmp_path, data) == GOLDEN_BASE_DIGEST


def test_set_like_list_order_changes_preserve_provenance(tmp_path):
    data = _base_data()
    for record in data["capabilities"]:
        for key, value in record.items():
            if isinstance(value, list):
                record[key] = list(reversed(value))
    assert _digest_of_data(tmp_path, data) == GOLDEN_BASE_DIGEST


def test_missing_versus_empty_optional_lists_match(tmp_path):
    data = _base_data()
    beta = _find(data, "beta-gadget")
    for optional_list in (
        "supporting_agents", "inputs", "outputs", "extension_points",
        "invariants", "failure_modes", "compatibility", "documentation_handoff",
    ):
        assert optional_list not in beta
        beta[optional_list] = []
    assert _digest_of_data(tmp_path, data) == GOLDEN_BASE_DIGEST


def test_missing_versus_null_optional_text_match(tmp_path):
    data = _base_data()
    gamma = _find(data, "gamma-tool")
    assert "known_consumer_exemption" not in gamma
    assert "deprecated_by" not in gamma
    gamma["known_consumer_exemption"] = None
    gamma["deprecated_by"] = None
    assert _digest_of_data(tmp_path, data) == GOLDEN_BASE_DIGEST


# --- 9-13. semantic changes alter identity ----------------------------------


def test_semantic_scalar_change_alters_provenance(tmp_path):
    data = _base_data()
    _find(data, "alpha-widget")["summary"] = "A different summary."
    assert _digest_of_data(tmp_path, data) != GOLDEN_BASE_DIGEST


def test_semantic_collection_value_change_alters_provenance(tmp_path):
    data = _base_data()
    _find(data, "gamma-tool")["keywords"] = ["gamma", "different"]
    assert _digest_of_data(tmp_path, data) != GOLDEN_BASE_DIGEST


def test_case_only_change_alters_provenance(tmp_path):
    data = _base_data()
    _find(data, "gamma-tool")["keywords"] = ["Gamma", "tool"]
    assert _digest_of_data(tmp_path, data) != GOLDEN_BASE_DIGEST


def test_path_spelling_change_alters_provenance(tmp_path):
    data = _base_data()
    gamma = _find(data, "gamma-tool")
    trailing = copy.deepcopy(data)
    _find(trailing, "gamma-tool")["canonical_paths"] = ["src/gamma/two.py", "src/gamma/one.py/"]
    dot_segment = copy.deepcopy(data)
    _find(dot_segment, "gamma-tool")["canonical_paths"] = ["src/gamma/two.py", "./src/gamma/one.py"]
    separator = copy.deepcopy(data)
    _find(separator, "gamma-tool")["canonical_paths"] = ["src/gamma/two.py", "src\\gamma\\one.py"]
    assert gamma["canonical_paths"]  # sanity: base path exists
    assert _digest_of_data(tmp_path, trailing, name="a.yml") != GOLDEN_BASE_DIGEST
    assert _digest_of_data(tmp_path, dot_segment, name="b.yml") != GOLDEN_BASE_DIGEST
    assert _digest_of_data(tmp_path, separator, name="c.yml") != GOLDEN_BASE_DIGEST


def test_composed_versus_decomposed_unicode_alters_provenance(tmp_path):
    data = _base_data()
    summary = "Café résumé"  # composed (NFC)
    nfc = copy.deepcopy(data)
    _find(nfc, "gamma-tool")["summary"] = unicodedata.normalize("NFC", summary)
    nfd = copy.deepcopy(data)
    _find(nfd, "gamma-tool")["summary"] = unicodedata.normalize("NFD", summary)
    assert unicodedata.normalize("NFC", summary) != unicodedata.normalize("NFD", summary)
    composed_digest = _digest_of_data(tmp_path, nfc, name="nfc.yml")
    decomposed_digest = _digest_of_data(tmp_path, nfd, name="nfd.yml")
    assert composed_digest != decomposed_digest


def test_added_or_removed_capability_alters_provenance(tmp_path):
    data = _base_data()
    removed = copy.deepcopy(data)
    removed["capabilities"] = [r for r in removed["capabilities"] if r["capability_id"] != "beta-gadget"]
    assert _digest_of_data(tmp_path, removed, name="removed.yml") != GOLDEN_BASE_DIGEST


# --- 14-20. fail-closed at the reader: no provenance is produced -------------


def test_duplicate_set_like_values_fail_before_provenance(tmp_path):
    data = _base_data()
    _find(data, "gamma-tool")["keywords"] = ["gamma", "gamma"]
    with pytest.raises(RegistryFormatError):
        provenance_for_registry(_write(tmp_path, data))


def test_unknown_top_level_key_fails_before_provenance(tmp_path):
    data = _base_data()
    data["surprise"] = "value"
    with pytest.raises(RegistryFormatError):
        provenance_for_registry(_write(tmp_path, data))


def test_unknown_record_field_fails_before_provenance(tmp_path):
    data = _base_data()
    _find(data, "alpha-widget")["mystery_field"] = "value"
    with pytest.raises(RegistryFormatError):
        provenance_for_registry(_write(tmp_path, data))


def test_duplicate_yaml_mapping_keys_fail_before_provenance(tmp_path):
    path = tmp_path / "dup_key.yml"
    path.write_text(
        "registry_version: 0.1.0\n"
        "registry_version: 0.1.0\n"
        "capabilities: []\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryFormatError):
        provenance_for_registry(path)


def test_duplicate_capability_ids_fail_before_provenance(tmp_path):
    data = _base_data()
    clone = copy.deepcopy(_find(data, "alpha-widget"))
    data["capabilities"].append(clone)
    with pytest.raises(RegistryFormatError):
        provenance_for_registry(_write(tmp_path, data))


def test_unsupported_registry_version_produces_no_provenance(tmp_path):
    data = _base_data()
    data["registry_version"] = "9.9.9"
    with pytest.raises(UnsupportedRegistryVersion):
        provenance_for_registry(_write(tmp_path, data))
    # The pure builder rejects the version too, independent of the reader.
    reader = RegistryReader(BASE)
    with pytest.raises(UnsupportedRegistryVersion):
        build_registry_provenance(reader.records, "9.9.9")


def test_malformed_yaml_produces_no_provenance(tmp_path):
    path = tmp_path / "malformed.yml"
    path.write_text("registry_version: 0.1.0\ncapabilities: [unterminated\n", encoding="utf-8")
    with pytest.raises(RegistryFormatError):
        provenance_for_registry(path)


def test_provenance_builder_defends_against_duplicate_set_like_values():
    # Defense-in-depth: even a hand-built record (bypassing the reader) fails
    # closed rather than silently deduplicating, per the #471 contract.
    record = CapabilityRecord(
        capability_id="dup-widget",
        name="Dup",
        summary="Dup summary",
        status="active",
        canonical_paths=("a.py",),
        public_interfaces=("m:A",),
        owner_agent="Integration Manager",
        supporting_agents=(),
        known_consumers=(),
        known_consumer_exemption=None,
        tests=(),
        keywords=("dup", "dup"),
        reuse_guidance="Reuse.",
        side_effects=(),
    )
    with pytest.raises(RegistryFormatError):
        build_registry_provenance([record], "0.1.0")


def test_provenance_builder_defends_against_duplicate_capability_ids():
    def make(cid: str) -> CapabilityRecord:
        return CapabilityRecord(
            capability_id=cid, name="N", summary="S", status="active",
            canonical_paths=("a.py",), public_interfaces=("m:A",),
            owner_agent="Integration Manager", supporting_agents=(),
            known_consumers=(), known_consumer_exemption=None, tests=(),
            keywords=("k",), reuse_guidance="R", side_effects=(),
        )
    with pytest.raises(RegistryFormatError):
        build_registry_provenance([make("same"), make("same")], "0.1.0")


# --- 21-24. provenance model: fail closed + version-aware equality ----------


def test_unsupported_provenance_algorithm_fails_closed():
    provenance = RegistryProvenance("some-other-algorithm", 1, "0.1.0", _HEX64)
    assert provenance.is_supported is False
    with pytest.raises(UnsupportedProvenanceError):
        provenance.require_supported()


def test_unsupported_provenance_version_fails_closed():
    provenance = RegistryProvenance(PROVENANCE_ALGORITHM, 2, "0.1.0", _HEX64)
    assert provenance.is_supported is False
    with pytest.raises(UnsupportedProvenanceError):
        provenance.require_supported()


@pytest.mark.parametrize(
    "bad_digest",
    [
        "abc",                      # too short
        _HEX64 + "a",               # too long
        "A" * 64,                   # uppercase
        "g" * 64,                   # non-hex letter
        "z" * 63 + " ",             # trailing space
        "",                          # empty
    ],
)
def test_malformed_digest_fails_closed(bad_digest):
    with pytest.raises(ValueError):
        RegistryProvenance(PROVENANCE_ALGORITHM, 1, "0.1.0", bad_digest)


def test_malformed_provenance_scalars_fail_closed():
    with pytest.raises(ValueError):
        RegistryProvenance("", 1, "0.1.0", _HEX64)
    with pytest.raises(ValueError):
        RegistryProvenance(PROVENANCE_ALGORITHM, 1, "", _HEX64)
    with pytest.raises(ValueError):
        RegistryProvenance(PROVENANCE_ALGORITHM, True, "0.1.0", _HEX64)  # bool is not a version


def test_provenance_equality_is_version_aware():
    base = RegistryProvenance(PROVENANCE_ALGORITHM, 1, "0.1.0", _HEX64)
    same = RegistryProvenance(PROVENANCE_ALGORITHM, 1, "0.1.0", _HEX64)
    other_version = RegistryProvenance(PROVENANCE_ALGORITHM, 2, "0.1.0", _HEX64)
    other_algorithm = RegistryProvenance("other-algorithm", 1, "0.1.0", _HEX64)
    other_registry = RegistryProvenance(PROVENANCE_ALGORITHM, 1, "0.2.0", _HEX64)
    other_digest = RegistryProvenance(PROVENANCE_ALGORITHM, 1, "0.1.0", "b" * 64)
    assert base == same
    # Whole-object, version-aware comparison: a bare digest is never equal on its own.
    assert base != other_version
    assert base != other_algorithm
    assert base != other_registry
    assert base != other_digest
    assert base != _HEX64


# --- 25-27. discovery attachment and serialization --------------------------


def test_populated_discovery_serialization_contains_correct_envelope():
    reader = RegistryReader(BASE)
    results = discover_capabilities(reader, status="active", attach_provenance=True)
    assert results
    expected = provenance_for_registry(BASE)
    for result in results:
        assert result.provenance == expected
        payload = discovery_result_to_payload(result)
        assert payload["provenance"] == {
            "algorithm": "registry-canonical-records",
            "algorithm_version": 1,
            "digest": GOLDEN_BASE_DIGEST,
            "registry_version": "0.1.0",
        }
    serialized = serialize_discovery_results(results)
    assert GOLDEN_BASE_DIGEST in serialized
    assert '"provenance"' in serialized


def test_absent_provenance_preserves_legacy_serialization():
    reader = RegistryReader(BASE)
    results = discover_capabilities(reader, status="active")
    assert results
    for result in results:
        assert result.provenance is None
        assert "provenance" not in discovery_result_to_payload(result)
    assert '"provenance"' not in serialize_discovery_results(results)


def test_discovery_ranking_and_selection_unchanged_by_provenance():
    reader = RegistryReader(BASE)
    plain = discover_capabilities(reader, status="active")
    stamped = discover_capabilities(reader, status="active", attach_provenance=True)
    assert [r.capability.capability_id for r in plain] == [r.capability.capability_id for r in stamped]
    for plain_result, stamped_result in zip(plain, stamped, strict=True):
        assert plain_result.confidence == stamped_result.confidence
        assert plain_result.evidence_basis == stamped_result.evidence_basis
        assert plain_result.warnings == stamped_result.warnings
        assert plain_result.manual_review_reasons == stamped_result.manual_review_reasons


# --- 28. digest is independent of external / filesystem metadata ------------


def test_digest_independent_of_path_and_filesystem_metadata(tmp_path):
    copy_a = tmp_path / "one" / "alias-a.yml"
    copy_b = tmp_path / "two" / "alias-b.yml"
    copy_a.parent.mkdir()
    copy_b.parent.mkdir()
    text = BASE.read_text(encoding="utf-8")
    copy_a.write_text(text, encoding="utf-8")
    copy_b.write_text(text, encoding="utf-8")
    import os

    os.utime(copy_b, (0, 0))  # different mtime
    assert provenance_for_registry(copy_a).digest == GOLDEN_BASE_DIGEST
    assert provenance_for_registry(copy_b).digest == GOLDEN_BASE_DIGEST


# --- integrity guard: every governed field participates ---------------------


def test_every_capability_record_field_participates_in_provenance():
    from reusable_capability_registry import provenance as provenance_module

    classified = (
        set(provenance_module._SCALAR_FIELDS)
        | set(provenance_module._OPTIONAL_TEXT_FIELDS)
        | set(provenance_module._SET_LIKE_FIELDS)
    )
    assert classified == {field.name for field in fields(CapabilityRecord)}


def test_confidence_import_is_available():
    # Guards the shared discovery import surface these tests rely on.
    assert Confidence.VERIFIED.value == "verified"
