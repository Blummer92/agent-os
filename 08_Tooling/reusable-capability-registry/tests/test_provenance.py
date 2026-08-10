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
GOLDEN_LIVE_DIGEST = "41280f4b1c4b1b2b507024e75cd52847b33cdbdbd13e17ba3ca69f3eeb436a50"

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
