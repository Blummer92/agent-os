import pytest

from scripts.agent_os_candidate_packet.cli import _evidence_from_json
from scripts.agent_os_candidate_packet.stage_models import DependencyEvidence


def test_cli_evidence_rejects_scalar_reason_codes_instead_of_character_splitting():
    with pytest.raises((TypeError, ValueError)):
        _evidence_from_json(
            DependencyEvidence,
            {"status": "resolved-clear", "reason_codes": "blocked", "details": []},
        )


def test_cli_evidence_rejects_scalar_details_instead_of_character_splitting():
    with pytest.raises((TypeError, ValueError)):
        _evidence_from_json(
            DependencyEvidence,
            {"status": "resolved-clear", "reason_codes": [], "details": "detail"},
        )
