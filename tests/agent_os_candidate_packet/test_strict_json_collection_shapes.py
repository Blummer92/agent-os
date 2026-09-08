import pytest

from scripts.agent_os_candidate_packet.cli import _evidence_status_from_dict
from scripts.agent_os_candidate_packet.stage_models import DependencyEvidence, ValidationEvidence


@pytest.mark.parametrize("cls", [DependencyEvidence, ValidationEvidence])
def test_cli_evidence_rejects_scalar_reason_codes_instead_of_character_splitting(cls):
    with pytest.raises((TypeError, ValueError)):
        _evidence_status_from_dict(
            {"status": "resolved-clear", "reason_codes": "blocked", "details": []},
            cls,
        )


@pytest.mark.parametrize("cls", [DependencyEvidence, ValidationEvidence])
def test_cli_evidence_rejects_scalar_details_instead_of_character_splitting(cls):
    with pytest.raises((TypeError, ValueError)):
        _evidence_status_from_dict(
            {"status": "resolved-clear", "reason_codes": [], "details": "detail"},
            cls,
        )


@pytest.mark.parametrize("cls", [DependencyEvidence, ValidationEvidence])
def test_cli_evidence_preserves_list_collections(cls):
    evidence = _evidence_status_from_dict(
        {"status": "resolved-clear", "reason_codes": ["blocked"], "details": ["detail"]},
        cls,
    )
    assert evidence.reason_codes == ("blocked",)
    assert evidence.details == ("detail",)


@pytest.mark.parametrize("cls", [DependencyEvidence, ValidationEvidence])
def test_cli_evidence_defaults_missing_collections_to_empty(cls):
    evidence = _evidence_status_from_dict({"status": "resolved-clear"}, cls)
    assert evidence.reason_codes == ()
    assert evidence.details == ()
