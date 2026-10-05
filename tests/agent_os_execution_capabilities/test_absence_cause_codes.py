"""B4 regression tests: bounded capability-absence cause codes.

The AI navigation layer does not manufacture operational state: an absent
capability is classified only through the bounded absence-cause family.
Vocabulary misses become the bounded fallback code, never a bare ValueError
and never an optimistic default. The free-text `reason` field is annotation
only, never the cause carrier.
"""

import pytest

from scripts.agent_os_execution_capabilities.models import (
    CapabilityEvidence,
    CapabilityStatus,
    EvidenceStrength,
)
from scripts.agent_os_execution_capabilities.reason_codes import (
    ABSENCE_CAUSE_CODES,
    ABSENCE_CAUSE_FALLBACK,
    is_absence_cause_code,
    is_approved_reason_code,
    normalize_absence_cause,
    normalize_reason_codes,
)

EXPECTED_CAUSES = {
    "capability-absence.unavailable",
    "capability-absence.undiscovered",
    "capability-absence.permission-missing",
    "capability-absence.connector-limitation",
    "capability-absence.native-host-limitation",
    "capability-absence.external-provider-failure",
    "capability-absence.retired",
    "capability-absence.never-existed",
}


def _evidence(**overrides):
    values = {
        "capability_id": "test-capability",
        "status": CapabilityStatus.UNAVAILABLE,
        "evidence_strength": EvidenceStrength.OBSERVED,
        "operation_scope": "test",
    }
    values.update(overrides)
    return CapabilityEvidence(**values)


def test_b4_absence_cause_family_is_complete():
    assert ABSENCE_CAUSE_CODES == EXPECTED_CAUSES


def test_b4_every_cause_code_is_approved():
    for code in EXPECTED_CAUSES:
        assert is_absence_cause_code(code)
        assert is_approved_reason_code(code)
    assert normalize_reason_codes(tuple(EXPECTED_CAUSES)) == tuple(
        sorted(EXPECTED_CAUSES)
    )


def test_b4_fallback_is_a_bounded_family_member():
    assert ABSENCE_CAUSE_FALLBACK == "capability-absence.undiscovered"
    assert is_absence_cause_code(ABSENCE_CAUSE_FALLBACK)


@pytest.mark.parametrize("code", sorted(EXPECTED_CAUSES))
def test_b4_normalize_passes_family_through(code):
    assert normalize_absence_cause(code) == code


@pytest.mark.parametrize(
    "value",
    [
        "capability-absence.spaceship",
        "adapter.incompatible",
        "available",
        "",
        None,
        42,
        b"capability-absence.unavailable",
        ("capability-absence.unavailable",),
    ],
)
def test_b4_vocabulary_miss_yields_bounded_fallback(value):
    """Unknown cause -> bounded fallback code, never bare ValueError."""
    assert normalize_absence_cause(value) == ABSENCE_CAUSE_FALLBACK


@pytest.mark.parametrize("code", sorted(EXPECTED_CAUSES))
def test_b4_absence_cause_for_each_cause_code(code):
    evidence = _evidence(reason_code=code)
    assert evidence.absence_cause() == code


def test_b4_absence_cause_ignores_free_text_reason():
    """The prose escape hatch never classifies the cause."""
    evidence = _evidence(
        reason_code="adapter.incompatible",
        reason="the connector could not reach the provider",
    )
    assert evidence.absence_cause() == ABSENCE_CAUSE_FALLBACK
    assert evidence.absence_cause() != evidence.reason


def test_b4_default_reason_code_falls_back_without_raising():
    evidence = _evidence()
    assert evidence.reason_code == "adapter.incompatible"
    assert evidence.absence_cause() == ABSENCE_CAUSE_FALLBACK


@pytest.mark.parametrize(
    "status",
    [
        CapabilityStatus.AVAILABLE,
        CapabilityStatus.INDETERMINATE,
        CapabilityStatus.NOT_REQUIRED,
    ],
)
def test_b4_absence_cause_is_none_when_not_unavailable(status):
    """Availability is never defaulted and absence is never inferred."""
    evidence = _evidence(
        status=status, reason_code="capability-absence.unavailable"
    )
    assert evidence.absence_cause() is None
