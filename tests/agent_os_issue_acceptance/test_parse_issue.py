from pathlib import Path

from scripts.agent_os_issue_acceptance.issueplan_scanner import ScanFinding
from scripts.agent_os_issue_acceptance.models import IssueMetadata
from scripts.agent_os_issue_acceptance.parse_issue import (
    parse_issue_metadata,
    project_issue_metadata,
    scan_issue_metadata,
)

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parents[2]


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
    ):
        metadata = parse_issue_metadata(
            f"```yaml\nagent_os_issue_acceptance:\n  documentation_impact: {value}\n```"
        )
        assert metadata.documentation_impact == value

    unknown = parse_issue_metadata(
        "```yaml\nagent_os_issue_acceptance:\n  future_governed_field: value\n```"
    )
    assert unknown.present is False
    assert "issueplan-scanner:unknown-governed-field" in unknown.manual_review


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


def test_malformed_yaml_is_distinct_from_missing_metadata():
    metadata = parse_issue_metadata(
        "```yaml\nagent_os_issue_acceptance: [unterminated\n```"
    )

    assert metadata.present is False
    assert "issueplan-scanner:metadata-malformed" in metadata.manual_review
    assert "metadata-malformed" in metadata.raw["_scanner_findings"]


def test_conflicting_candidates_fail_closed():
    body = (
        "```yaml\nagent_os_issue_acceptance:\n  owner_agent: qa-test-agent\n```\n"
        "```yaml\nagent_os_issue_acceptance:\n  owner_agent: integration-manager\n```"
    )
    metadata = parse_issue_metadata(body)

    assert metadata.present is False
    assert "issueplan-scanner:metadata-conflicting" in metadata.manual_review


def test_duplicate_identical_candidates_fail_closed():
    block = "```yaml\nagent_os_issue_acceptance:\n  owner_agent: qa-test-agent\n```"
    metadata = parse_issue_metadata(f"{block}\n{block}")

    assert metadata.present is False
    assert "issueplan-scanner:metadata-duplicated-identical" in metadata.manual_review


def test_malformed_and_valid_candidates_remain_conflicting_in_both_orders():
    valid = "```yaml\nagent_os_issue_acceptance:\n  owner_agent: qa-test-agent\n```"
    malformed = "```yaml\nagent_os_issue_acceptance: [\n```"

    for body in (f"{malformed}\n{valid}", f"{valid}\n{malformed}"):
        metadata = parse_issue_metadata(body)
        assert metadata.present is False
        assert "issueplan-scanner:metadata-malformed" in metadata.manual_review
        assert "issueplan-scanner:metadata-conflicting" in metadata.manual_review


def test_unsupported_profile_version_fails_closed_without_coercion():
    metadata = parse_issue_metadata(
        "```yaml\nagent_os_issue_acceptance:\n  profile_version: issueplan-core/v99\n```"
    )

    assert metadata.present is False
    assert "issueplan-scanner:profile-version-unsupported" in metadata.manual_review


def test_source_preflight_findings_remain_distinct():
    body = "```yaml\nagent_os_issue_acceptance:\n  owner_agent: qa-test-agent\n```"

    partial = project_issue_metadata(scan_issue_metadata(body, retrieval_complete=False))
    inaccessible = project_issue_metadata(scan_issue_metadata(body, accessible=False))
    unsupported = project_issue_metadata(
        scan_issue_metadata(body, source_family="notion-page")
    )
    stale = project_issue_metadata(
        scan_issue_metadata(body, source_revision="rev-2", expected_revision="rev-1")
    )

    assert "issueplan-scanner:source-partial" in partial.manual_review
    assert "issueplan-scanner:source-inaccessible" in inaccessible.manual_review
    assert "issueplan-scanner:source-unsupported" in unsupported.manual_review
    assert "issueplan-scanner:source-stale" in stale.manual_review


def test_raw_body_scan_is_source_unbound():
    result = scan_issue_metadata(
        "```yaml\nagent_os_issue_acceptance:\n  owner_agent: qa-test-agent\n```"
    )

    assert result.source_locator == "compatibility:raw-body"
    assert result.source_revision == ""
    assert result.execution_authorized is False


def test_source_revision_mismatch_remains_visible():
    result = scan_issue_metadata(
        "```yaml\nagent_os_issue_acceptance:\n  owner_agent: qa-test-agent\n```",
        source_locator="github:Blummer92/agent-os#358",
        source_revision="rev-2",
        expected_revision="rev-1",
    )

    assert ScanFinding.SOURCE_STALE in result.findings


def test_only_canonical_scanner_parses_acceptance_yaml_candidates():
    consumers = (
        "scripts/agent_os_issue_acceptance/parse_issue.py",
        "scripts/agent_os_issue_acceptance/policy.py",
        "scripts/agent_os_issue_acceptance/readiness.py",
        "scripts/agent_os_issue_acceptance/legacy_preflight.py",
    )
    for relative_path in consumers:
        source = (ROOT / relative_path).read_text()
        assert "yaml.safe_load" not in source
        assert "_FENCED_YAML_RE" not in source
        assert "_METADATA_RE" not in source

    scanner_source = (
        ROOT / "scripts/agent_os_issue_acceptance/issueplan_scanner.py"
    ).read_text()
    assert "yaml.safe_load" in scanner_source
    assert "_FENCED_YAML_RE" in scanner_source


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


def test_missing_metadata_returns_exact_empty_metadata():
    metadata = parse_issue_metadata((FIXTURES / "issue_missing_metadata.md").read_text())

    assert metadata == IssueMetadata.empty()
