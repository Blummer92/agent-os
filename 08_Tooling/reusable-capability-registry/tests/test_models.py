from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from reusable_capability_registry import CapabilityRecord, Confidence, DiscoveryResult, RegistryReader, discover_capabilities

FIXTURES = Path(__file__).parent / "fixtures"


def make_record() -> CapabilityRecord:
    return CapabilityRecord(
        capability_id="alpha",
        name="Alpha",
        summary="Alpha summary",
        status="active",
        canonical_paths=("alpha.py",),
        public_interfaces=("alpha:run",),
        owner_agent="Integration Manager",
        supporting_agents=(),
        known_consumers=(),
        known_consumer_exemption=None,
        tests=(),
        keywords=("alpha",),
        reuse_guidance="Reuse alpha.",
        side_effects=(),
    )


def test_models_are_frozen_slotted_and_nested_sequences_are_immutable():
    record = make_record()
    result = DiscoveryResult(record, Confidence.VERIFIED, ("exact-capability-id-match",), (), ())
    assert not hasattr(record, "__dict__")
    assert isinstance(record.keywords, tuple)
    with pytest.raises(FrozenInstanceError):
        setattr(record, "status", "deprecated")
    with pytest.raises(AttributeError):
        result.evidence_basis.append("x")


def test_canonical_and_derived_fields_are_separated():
    record = RegistryReader(FIXTURES / "valid_registry.yml").by_id("alpha-reader")
    assert {"confidence", "evidence_basis", "warnings", "manual_review_reasons"}.isdisjoint(
        {field.name for field in fields(type(record))}
    )
    result = discover_capabilities(
        RegistryReader(FIXTURES / "valid_registry.yml"), capability_id="alpha-reader"
    )[0]
    assert {"confidence", "evidence_basis", "warnings", "manual_review_reasons"} <= {
        field.name for field in fields(type(result))
    }
