"""Focused PyYAML loader-compatibility contract for the reusable-capability
registry (#491).

The exhaustive duplicate-key / alias / merge / malformed-input behavior matrix
lives in ``test_reader.py`` and is executed under every PyYAML version by the
compatibility workflow. This module concentrates the *version-sensitive* surface
into a fast, self-describing contract so each matrix lane proves, at its exact
resolved PyYAML version:

1. the installed PyYAML falls inside the declared ``>=6.0,<7`` range;
2. the loader-implementation API surface #490 relies on still exists;
3. the merged reader's duplicate-key boundary still fails closed, and aliases
   and single merges still work.

It intentionally does not pin, narrow, or broaden the dependency; it reads the
version actually resolved by the running environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from yaml.constructor import SafeConstructor
from yaml.nodes import MappingNode

from reusable_capability_registry import RegistryFormatError, RegistryReader
from reusable_capability_registry.reader import _MERGE_TAG, _UniqueKeySafeLoader

FIXTURES = Path(__file__).parent / "fixtures"


def _version_tuple() -> tuple[int, int, int]:
    parts = [int(piece) for piece in yaml.__version__.split(".")[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)  # type: ignore[return-value]


def test_installed_pyyaml_is_within_declared_supported_range():
    # Guards against a mis-provisioned matrix lane: a lane that silently
    # resolved an out-of-range PyYAML fails here instead of reporting green.
    version = _version_tuple()
    assert (6, 0, 0) <= version < (7, 0, 0), f"unexpected PyYAML {yaml.__version__}"


def test_loader_api_surface_used_by_the_reader_exists():
    # The #490 duplicate-key loader depends on these PyYAML internals; assert
    # they remain present so API drift across the range is caught explicitly.
    assert issubclass(_UniqueKeySafeLoader, yaml.SafeLoader)
    assert _MERGE_TAG == "tag:yaml.org,2002:merge"
    assert hasattr(_UniqueKeySafeLoader, "construct_mapping")
    assert hasattr(_UniqueKeySafeLoader, "construct_object")
    # Merge flattening / precedence is inherited from SafeConstructor.
    assert hasattr(SafeConstructor, "flatten_mapping")
    node = MappingNode(tag="tag:yaml.org,2002:map", value=[])
    assert hasattr(node, "start_mark") or node.start_mark is None


def _reader_for(tmp_path: Path, text: str) -> RegistryReader:
    path = tmp_path / "registry.yml"
    path.write_text(text, encoding="utf-8")
    return RegistryReader(path)


_VALID = """registry_version: 0.1.0
capabilities:
  - capability_id: alpha-reader
    name: Alpha Reader
    summary: Reads alpha records.
    status: active
    canonical_paths: [src/alpha.py]
    public_interfaces: [alpha:Read]
    owner_agent: Integration Manager
    known_consumers: []
    tests: [tests/test_alpha.py]
    keywords: [alpha]
    reuse_guidance: Reuse for alpha reads only.
    side_effects: [Performs no writes.]
"""

_MERGE_BASE = """registry_version: 0.1.0
capabilities:
  - &base
    capability_id: base-reader
    name: Base Reader
    summary: Base summary.
    status: active
    canonical_paths: [src/base.py]
    public_interfaces: [base:Read]
    owner_agent: Integration Manager
    known_consumers: []
    tests: [tests/test_base.py]
    keywords: [base]
    reuse_guidance: Base guidance.
    side_effects: [Performs no writes.]
"""


def test_equal_and_different_duplicate_explicit_keys_are_rejected(tmp_path):
    equal = _VALID.replace(
        "    summary: Reads alpha records.\n",
        "    summary: Reads alpha records.\n    summary: Reads alpha records.\n",
        1,
    )
    different = _VALID.replace(
        "    summary: Reads alpha records.\n",
        "    summary: Reads alpha records.\n    summary: Different.\n",
        1,
    )
    for text in (equal, different):
        with pytest.raises(RegistryFormatError, match="duplicate YAML mapping key 'summary'"):
            _reader_for(tmp_path, text)


def test_quoted_and_unquoted_equivalent_keys_are_duplicates(tmp_path):
    text = _VALID.replace(
        "    summary: Reads alpha records.\n",
        '    summary: Reads alpha records.\n    "summary": Different.\n',
        1,
    )
    with pytest.raises(RegistryFormatError, match="duplicate YAML mapping key 'summary'"):
        _reader_for(tmp_path, text)


def test_case_distinct_key_flows_to_unknown_field_validation(tmp_path):
    text = _VALID.replace(
        "    summary: Reads alpha records.\n",
        "    summary: Reads alpha records.\n    Summary: Different case.\n",
        1,
    )
    with pytest.raises(RegistryFormatError, match="unsupported fields.*Summary"):
        _reader_for(tmp_path, text)


def test_first_duplicate_is_deterministic_with_bounded_line_context(tmp_path):
    text = _VALID.replace(
        "    summary: Reads alpha records.\n",
        "    summary: Reads alpha records.\n    summary: Duplicate.\n",
        1,
    )
    with pytest.raises(RegistryFormatError) as exc_info:
        _reader_for(tmp_path, text)
    message = str(exc_info.value)
    assert "duplicate YAML mapping key 'summary'" in message
    assert "at line" in message
    assert "mapping starts at line" in message


def test_alias_without_duplicate_key_is_valid(tmp_path):
    text = _VALID.replace(
        "    summary: Reads alpha records.\n",
        "    summary: &shared Reads alpha records.\n",
        1,
    ).replace(
        "    reuse_guidance: Reuse for alpha reads only.\n",
        "    reuse_guidance: *shared\n",
        1,
    )
    record = _reader_for(tmp_path, text).by_id("alpha-reader")
    assert record.summary == record.reuse_guidance == "Reads alpha records."


def test_single_merge_mapping_is_valid(tmp_path):
    text = _MERGE_BASE + """  - <<: *base
    capability_id: merged-reader
    name: Merged Reader
    canonical_paths: [src/merged.py]
    public_interfaces: [merged:Read]
    tests: [tests/test_merged.py]
    keywords: [merged]
"""
    record = _reader_for(tmp_path, text).by_id("merged-reader")
    assert record.summary == "Base summary."


def test_repeated_explicit_merge_keys_are_rejected(tmp_path):
    text = _MERGE_BASE + """  - <<: *base
    <<: *base
    capability_id: merged-reader
"""
    with pytest.raises(RegistryFormatError, match="duplicate YAML mapping key '<<'"):
        _reader_for(tmp_path, text)


def test_malformed_and_unsupported_inputs_fail_closed(tmp_path):
    with pytest.raises(RegistryFormatError):
        _reader_for(tmp_path, "registry_version: 0.1.0\ncapabilities: [oops\n")
    with pytest.raises(RegistryFormatError):
        _reader_for(tmp_path, _VALID.replace("keywords: [alpha]", "keywords: [alpha, alpha]", 1))


def test_canonical_and_bounded_fixture_registries_load_deterministically():
    canonical = RegistryReader()
    assert canonical.record_count > 0
    first = RegistryReader(FIXTURES / "registry_100.yml").records
    second = RegistryReader(FIXTURES / "registry_100.yml").records
    assert len(first) == 100
    assert first == second
