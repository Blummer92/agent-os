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
        ({"public_interface": "alpha:Read"}, "public-interface-match"),
        ({"keywords": ("Alpha",), "owner": "Integration Manager"}, "exact-keyword-match"),
    ]
    for kwargs, evidence in cases:
        results = discover_capabilities(reader, **kwargs)
        assert results
        assert evidence in results[0].evidence_basis
        assert "behavioral-compatibility-not-evaluated" in results[0].warnings


def test_normalized_keyword_is_probable_and_tied_keyword_is_manual_review():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    probable = discover_capabilities(reader, keywords=("ALPHA",), owner="QA / Test Agent")
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


def test_non_keyword_queries_are_literal_and_truthful():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    assert discover_capabilities(reader, capability_id="ALPHA_READER") == ()
    assert discover_capabilities(reader, owner="integration_manager") == ()
    assert discover_capabilities(reader, status=" ACTIVE ") == ()
    assert discover_capabilities(reader, canonical_path="SRC/ALPHA.PY") == ()
    assert discover_capabilities(reader, public_interface="alpha:read") == ()


def test_keyword_provenance_is_per_result_after_filtering():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    alpha = discover_capabilities(reader, keywords=("Alpha",), owner="Integration Manager")[0]
    beta = discover_capabilities(reader, keywords=("Alpha",), owner="QA / Test Agent")[0]
    assert alpha.confidence is Confidence.VERIFIED
    assert alpha.evidence_basis == ("exact-keyword-match", "owner-field-match")
    assert beta.confidence is Confidence.PROBABLE
    assert beta.evidence_basis == ("normalized-keyword-match", "owner-field-match")


def test_duplicate_matches_collapse_and_preserve_provenance():
    result = discover_capabilities(
        RegistryReader(FIXTURES / "valid_registry.yml"),
        capability_id="alpha-reader",
        keywords=("Alpha",),
        owner="Integration Manager",
        status="active",
        canonical_path="src/alpha.py",
        public_interface="alpha:Read",
    )
    assert len(result) == 1
    assert result[0].capability.capability_id == "alpha-reader"
    assert result[0].evidence_basis == (
        "canonical-path-match",
        "exact-capability-id-match",
        "exact-keyword-match",
        "owner-field-match",
        "public-interface-match",
        "status-field-match",
    )


def test_prior_query_order_does_not_contaminate_results():
    path = FIXTURES / "valid_registry.yml"
    queries = [
        {"capability_id": "alpha-reader"},
        {"keywords": ("Alpha",), "owner": "Integration Manager"},
        {"owner": "QA / Test Agent"},
        {"status": "active", "canonical_path": "src/alpha.py"},
        {"public_interface": "beta:evaluate"},
    ]
    baseline = [discover_capabilities(RegistryReader(path), **query) for query in queries]
    reader = RegistryReader(path)
    forward = [discover_capabilities(reader, **query) for query in queries]
    reverse_results = {index: discover_capabilities(reader, **queries[index]) for index in reversed(range(len(queries)))}
    reverse = [reverse_results[index] for index in range(len(queries))]
    assert forward == baseline == reverse


def test_fresh_and_reused_readers_are_equivalent():
    path = FIXTURES / "valid_registry.yml"
    queries = [
        {"capability_id": "alpha-reader"},
        {"keywords": ("ALPHA",), "owner": "QA / Test Agent"},
        {"owner": "Integration Manager"},
        {"status": "active"},
        {"canonical_path": "src/alpha.py"},
        {"public_interface": "alpha:Read"},
    ]
    reused = RegistryReader(path)
    assert [discover_capabilities(reused, **query) for query in queries] == [
        discover_capabilities(RegistryReader(path), **query) for query in queries
    ]


def test_100_record_reused_and_fresh_results_match():
    path = FIXTURES / "registry_100.yml"
    reused = RegistryReader(path)
    expected = discover_capabilities(reused, capability_id="capability-050")
    for _ in range(20):
        assert discover_capabilities(reused, capability_id="capability-050") == expected
    assert discover_capabilities(RegistryReader(path), capability_id="capability-050") == expected
    assert reused.parse_count == 1
    assert reused.index_build_count == 1
    assert reused.record_count == 100
