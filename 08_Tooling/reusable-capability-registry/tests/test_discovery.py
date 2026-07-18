from pathlib import Path

import pytest

from reusable_capability_registry import Confidence, RegistryFormatError, RegistryReader, discover_capabilities

FIXTURES = Path(__file__).parent / "fixtures"


def test_exact_id_owner_status_path_interface_and_keyword_queries():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    cases = [
        ({"capability_id": "alpha-reader"}, "exact-capability-id-match"),
        ({"owner": "Integration Manager"}, "owner-field-match"),
        ({"status": "active", "capability_id": "alpha-reader"}, "status-field-match"),
        ({"canonical_path": "src/alpha.py"}, "canonical-path-match"),
        ({"public_interface": "alpha:read"}, "public-interface-match"),
        ({"keywords": ("alpha",)}, "exact-keyword-match"),
    ]
    for kwargs, evidence in cases:
        results = discover_capabilities(reader, **kwargs)
        assert results
        assert evidence in results[0].evidence_basis
        assert "behavioral-compatibility-not-evaluated" in results[0].warnings


def test_normalized_keyword_is_probable_and_tied_keyword_is_manual_review():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    probable = discover_capabilities(reader, keywords=("ALPHA",))
    assert probable[0].confidence is Confidence.PROBABLE
    tied = discover_capabilities(reader, keywords=("shared",))
    assert len(tied) == 2
    assert all(result.confidence is Confidence.MANUAL_REVIEW for result in tied)


def test_filters_intersect_deduplicate_and_order_stably():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    first = discover_capabilities(reader, keywords=("shared",), status="active")
    second = discover_capabilities(reader, status="active", keywords=("shared",))
    assert first == second
    assert [item.capability.capability_id for item in first] == ["alpha-reader", "beta-evaluator"]


def test_exemption_and_direct_module_warnings_are_visible():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    result = discover_capabilities(reader, capability_id="beta-evaluator")[0]
    assert "known-consumer-exemption-active" in result.warnings
    assert "direct-module-stability-commitment" in result.warnings


def test_no_match_and_empty_query_behavior():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    assert discover_capabilities(reader, capability_id="missing") == ()
    with pytest.raises(RegistryFormatError):
        discover_capabilities(reader)


def test_repeated_queries_do_not_change_internal_counts():
    reader = RegistryReader(FIXTURES / "registry_100.yml")
    expected = discover_capabilities(reader, capability_id="capability-050")
    for _ in range(20):
        assert discover_capabilities(reader, capability_id="capability-050") == expected
    assert reader.record_count == 100
    assert reader.parse_count == 1
    assert reader.index_build_count == 1
