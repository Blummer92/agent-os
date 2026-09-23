"""Regression coverage for #1708."""

import pytest

from scripts.agent_os_candidate_packet.stage_models import DependencyEvidence, EvidenceStatus, ValidationEvidence


@pytest.mark.parametrize("model", [DependencyEvidence, ValidationEvidence])
@pytest.mark.parametrize("field", ["reason_codes", "details"])
def test_scalar_string_evidence_is_rejected(model, field):
    with pytest.raises(TypeError):
        model(status=EvidenceStatus.UNAVAILABLE, **{field: "blocked"})


@pytest.mark.parametrize("model", [DependencyEvidence, ValidationEvidence])
def test_tuple_of_strings_is_preserved(model):
    evidence = model(status=EvidenceStatus.UNAVAILABLE, reason_codes=("blocked",), details=("detail",))
    assert evidence.reason_codes == ("blocked",)
    assert evidence.details == ("detail",)
