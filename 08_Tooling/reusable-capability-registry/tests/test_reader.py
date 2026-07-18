from pathlib import Path

import pytest

from reusable_capability_registry import (
    RegistryFileError,
    RegistryFormatError,
    RegistryReader,
    UnsupportedRegistryVersion,
    default_registry_path,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_default_path_is_repository_relative_and_loads_from_non_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert default_registry_path().name == "reusable-capabilities.yml"
    reader = RegistryReader()
    assert reader.record_count == 2


def test_explicit_fixture_loads_once_and_builds_indexes_once():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    assert reader.parse_count == 1
    assert reader.index_build_count == 1
    assert tuple(record.capability_id for record in reader.records) == ("alpha-reader", "beta-evaluator")


def test_registry_bytes_and_records_remain_stable():
    path = FIXTURES / "valid_registry.yml"
    before = path.read_bytes()
    reader = RegistryReader(path)
    snapshot = reader.records
    reader.lookup("keyword", "shared")
    assert path.read_bytes() == before
    assert reader.records == snapshot


def test_missing_malformed_unsupported_and_invalid_top_level_fail_safely(tmp_path):
    with pytest.raises(RegistryFileError):
        RegistryReader(tmp_path / "missing.yml")
    with pytest.raises(RegistryFormatError):
        RegistryReader(FIXTURES / "malformed_registry.yml")
    with pytest.raises(UnsupportedRegistryVersion):
        RegistryReader(FIXTURES / "unsupported_registry.yml")
    invalid = tmp_path / "invalid.yml"
    invalid.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(RegistryFormatError):
        RegistryReader(invalid)


def test_unknown_same_version_field_is_rejected(tmp_path):
    text = (FIXTURES / "valid_registry.yml").read_text(encoding="utf-8")
    path = tmp_path / "unknown.yml"
    path.write_text(text.replace("    name: Alpha Reader", "    name: Alpha Reader\n    confidence: verified", 1), encoding="utf-8")
    with pytest.raises(RegistryFormatError, match="unsupported fields"):
        RegistryReader(path)


def test_optional_supporting_agents_and_conditional_deprecated_by(tmp_path):
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    assert reader.by_id("alpha-reader").supporting_agents == ()

    deprecated = tmp_path / "deprecated.yml"
    deprecated.write_text(
        """registry_version: 0.1.0
capabilities:
  - capability_id: old-reader
    name: Old Reader
    summary: Legacy reader.
    status: deprecated
    canonical_paths: [src/old.py]
    public_interfaces: [old:read]
    owner_agent: Integration Manager
    known_consumers: []
    known_consumer_exemption: Legacy record.
    tests: [tests/test_old.py]
    keywords: [old]
    reuse_guidance: Use new-reader.
    side_effects: [Performs no writes.]
    deprecated_by: new-reader
""",
        encoding="utf-8",
    )
    record = RegistryReader(deprecated).by_id("old-reader")
    assert record.deprecated_by == "new-reader"

    deprecated.write_text(deprecated.read_text().replace("    deprecated_by: new-reader\n", ""), encoding="utf-8")
    with pytest.raises(RegistryFormatError, match="deprecated_by is required"):
        RegistryReader(deprecated)


def test_invalid_status_is_rejected(tmp_path):
    text = (FIXTURES / "valid_registry.yml").read_text(encoding="utf-8")
    path = tmp_path / "status.yml"
    path.write_text(text.replace("    status: active", "    status: unknown", 1), encoding="utf-8")
    with pytest.raises(RegistryFormatError, match="unsupported status"):
        RegistryReader(path)
