from dataclasses import FrozenInstanceError

import pytest

from reusable_capability_registry import CapabilityRecord, Confidence, DiscoveryResult


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
        record.status = "deprecated"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        result.evidence_basis.append("x")  # type: ignore[attr-defined]
