from pathlib import Path

import pytest
import yaml

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
    assert reader.registry_path == default_registry_path()
    assert reader.record_count > 0


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


def test_exact_non_keyword_indexes_reject_normalized_variants():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    assert reader.by_id("alpha-reader") is not None
    assert reader.by_id("ALPHA_READER") is None
    assert reader.lookup("owner", "Integration Manager")
    assert reader.lookup("owner", "integration_manager") == ()
    assert reader.lookup("status", "active")
    assert reader.lookup("status", " ACTIVE ") == ()
    assert reader.lookup("canonical_path", "src/alpha.py")
    assert reader.lookup("canonical_path", "SRC/ALPHA.PY") == ()
    assert reader.lookup("public_interface", "alpha:Read")
    assert reader.lookup("public_interface", "alpha:read") == ()


def test_keyword_index_remains_normalized():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    assert [record.capability_id for record in reader.lookup("keyword", "ALPHA")] == ["alpha-reader", "beta-evaluator"]


@pytest.mark.parametrize("invalid_id", ["foo_bar", "Foo-Bar", "foo bar", "-foo", "foo-", "foo--bar"])
def test_invalid_capability_id_fails_conservatively(tmp_path, invalid_id):
    data = yaml.safe_load((FIXTURES / "valid_registry.yml").read_text())
    data["capabilities"][0]["capability_id"] = invalid_id
    path = tmp_path / "invalid-id.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    with pytest.raises(RegistryFormatError, match="lowercase kebab-case"):
        RegistryReader(path)


def test_record_does_not_retain_source_dictionary(tmp_path):
    data = yaml.safe_load((FIXTURES / "valid_registry.yml").read_text())
    path = tmp_path / "copy.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    record = RegistryReader(path).by_id("alpha-reader")
    data["capabilities"][0]["keywords"].append("mutated")
    data["capabilities"][0]["canonical_paths"][0] = "changed.py"
    assert record.keywords == ("Alpha", "shared")
    assert record.canonical_paths == ("src/alpha.py",)


def test_100_record_indexes_are_stable():
    reader = RegistryReader(FIXTURES / "registry_100.yml")
    counts = reader.index_entry_counts
    records = reader.records
    for _ in range(25):
        assert reader.by_id("capability-050").capability_id == "capability-050"
        assert reader.lookup("keyword", "FIXTURE")
    assert reader.parse_count == 1
    assert reader.index_build_count == 1
    assert reader.record_count == 100
    assert reader.records is records
    assert reader.index_entry_counts == counts


def _valid_registry_data():
    return yaml.safe_load((FIXTURES / "valid_registry.yml").read_text(encoding="utf-8"))


def _write_registry(tmp_path, data, name="registry.yml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def test_unknown_top_level_scalar_key_is_rejected(tmp_path):
    data = _valid_registry_data()
    data["metadata"] = "extra"
    with pytest.raises(RegistryFormatError, match="unsupported top-level registry keys.*metadata"):
        RegistryReader(_write_registry(tmp_path, data))


def test_unknown_top_level_mapping_key_is_rejected(tmp_path):
    data = _valid_registry_data()
    data["settings"] = {"strict": True}
    with pytest.raises(RegistryFormatError, match="unsupported top-level registry keys.*settings"):
        RegistryReader(_write_registry(tmp_path, data))


def test_unknown_top_level_list_key_is_rejected(tmp_path):
    data = _valid_registry_data()
    data["notes"] = ["a", "b"]
    with pytest.raises(RegistryFormatError, match="unsupported top-level registry keys.*notes"):
        RegistryReader(_write_registry(tmp_path, data))


def test_mistyped_capabilities_key_fails_closed_not_zero_records(tmp_path):
    data = _valid_registry_data()
    data["capabilties"] = data.pop("capabilities")  # typo drops the real key
    with pytest.raises(RegistryFormatError, match="unsupported top-level registry keys.*capabilties"):
        RegistryReader(_write_registry(tmp_path, data))


def test_error_names_all_unknown_top_level_keys(tmp_path):
    data = _valid_registry_data()
    data["alpha_extra"] = 1
    data["zeta_extra"] = 2
    with pytest.raises(RegistryFormatError, match="alpha_extra, zeta_extra"):
        RegistryReader(_write_registry(tmp_path, data))


def test_formatting_only_top_level_key_reorder_remains_valid(tmp_path):
    data = _valid_registry_data()
    reordered = {"capabilities": data["capabilities"], "registry_version": data["registry_version"]}
    reader = RegistryReader(_write_registry(tmp_path, reordered))
    assert reader.record_count == 2


def test_canonical_registry_still_loads_under_top_level_key_rejection():
    # The fail-closed top-level-key rule must not reject the current canonical registry.
    reader = RegistryReader()
    assert reader.record_count > 0


def test_record_level_unknown_field_rejection_is_preserved(tmp_path):
    data = _valid_registry_data()
    data["capabilities"][0]["confidence"] = "verified"
    with pytest.raises(RegistryFormatError, match="unsupported fields"):
        RegistryReader(_write_registry(tmp_path, data))
