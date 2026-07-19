from pathlib import Path

from scripts.agent_os_issue_acceptance.models import IssueMetadata
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
    assert metadata.documentation_impact is None
    assert metadata.documentation_expected_change is None
    assert metadata.documentation_exemption_reason is None


def test_parse_documentation_metadata_preserves_values_and_raw_block():
    body = '''
```yaml
agent_os_issue_acceptance:
  documentation_impact: " docs-required "
  required_docs:
    - 01_Shared_Standards/github
    - bad//path
  documentation_expected_change: " Explain the new operator behavior. "
  documentation_exemption_reason: null
```
'''

    metadata = parse_issue_metadata(body)

    assert metadata.documentation_impact == " docs-required "
    assert metadata.required_docs == ["01_Shared_Standards/github", "bad//path"]
    assert metadata.documentation_expected_change == " Explain the new operator behavior. "
    assert metadata.documentation_exemption_reason is None
    assert metadata.raw["documentation_impact"] == metadata.documentation_impact
    assert metadata.raw["documentation_expected_change"] == metadata.documentation_expected_change


def test_each_documentation_impact_value_and_unknown_remain_observable():
    for value in (
        "docs-required",
        "docs-not-required",
        "docs-needs-decision",
        "future-value",
    ):
        metadata = parse_issue_metadata(
            f"```yaml\nagent_os_issue_acceptance:\n  documentation_impact: {value}\n```"
        )
        assert metadata.documentation_impact == value


def test_required_docs_scalar_and_list_normalization_remain_compatible():
    scalar = parse_issue_metadata(
        "```yaml\nagent_os_issue_acceptance:\n  required_docs: docs/one.md\n```"
    )
    multiple = parse_issue_metadata(
        "```yaml\nagent_os_issue_acceptance:\n  required_docs:\n    - docs/one.md\n    - docs/two.md\n```"
    )

    assert scalar.required_docs == ["docs/one.md"]
    assert multiple.required_docs == ["docs/one.md", "docs/two.md"]


def test_missing_documentation_keys_preserve_defaults():
    metadata = parse_issue_metadata(
        "```yaml\nagent_os_issue_acceptance:\n  owner_agent: qa-test-agent\n```"
    )

    assert metadata.documentation_impact is None
    assert metadata.required_docs == []
    assert metadata.documentation_expected_change is None
    assert metadata.documentation_exemption_reason is None


def test_malformed_yaml_retains_existing_fail_closed_behavior():
    metadata = parse_issue_metadata(
        "```yaml\nagent_os_issue_acceptance: [unterminated\n```"
    )

    assert metadata == IssueMetadata.empty()


def test_old_positional_constructor_and_empty_remain_valid():
    metadata = IssueMetadata(
        True,
        "qa-test-agent",
        "GitHub",
        "none",
        ["a"],
        ["b"],
        ["c"],
        ["d"],
        ["e"],
        ["f"],
        {"owner_agent": "qa-test-agent"},
    )

    assert metadata.raw == {"owner_agent": "qa-test-agent"}
    assert metadata.documentation_impact is None
    assert IssueMetadata.empty().present is False


def test_repeated_parsing_is_deterministic():
    body = "```yaml\nagent_os_issue_acceptance:\n  documentation_impact: docs-required\n```"

    assert parse_issue_metadata(body) == parse_issue_metadata(body)


def test_missing_metadata_returns_empty_metadata():
    metadata = parse_issue_metadata((FIXTURES / "issue_missing_metadata.md").read_text())

    assert metadata.present is False
    assert metadata.required_files == []
