from pathlib import Path

from scripts.agent_os_issue_acceptance.parse_issue import parse_issue_metadata

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_machine_checkable_issue_metadata_block():
    metadata = parse_issue_metadata((FIXTURES / "issue_valid.md").read_text())

    assert metadata.present is True
    assert metadata.owner_agent == "qa-test-agent"
    assert metadata.source_of_truth == "GitHub"
    assert metadata.external_writes == "none"
    assert metadata.required_files == ["scripts/agent_os_issue_acceptance/"]
    assert metadata.forbidden_paths == ["00_Governance/"]
    assert metadata.required_tests == ["tests/agent_os_issue_acceptance/"]
    assert metadata.required_docs == ["scripts/agent_os_issue_acceptance/README.md"]
    assert metadata.banned_patterns == ["import requests"]


def test_missing_metadata_returns_empty_metadata():
    metadata = parse_issue_metadata((FIXTURES / "issue_missing_metadata.md").read_text())

    assert metadata.present is False
    assert metadata.required_files == []
