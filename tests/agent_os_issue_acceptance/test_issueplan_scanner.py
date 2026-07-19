from scripts.agent_os_issue_acceptance.issueplan_scanner import (
    AdoptionClass,
    ScanFinding,
    SourceEnvelope,
    scan_issueplan_source,
)


def _block(body: str) -> str:
    return f"```yaml\nagent_os_issue_acceptance:\n{body}\n```"


def _scan(content: str, **kwargs):
    return scan_issueplan_source(
        SourceEnvelope(
            source_locator="github:Blummer92/agent-os#1",
            source_revision="rev-1",
            content=content,
            **kwargs,
        )
    )


def test_single_strict_block_is_strict_native_and_never_authorized():
    result = _scan(_block("  entity_id: issue-1\n  owner_agent: Integration Manager"))
    assert ScanFinding.METADATA_SINGLE in result.findings
    assert result.adoption_class == AdoptionClass.STRICT_NATIVE
    assert result.strict_valid is True
    assert result.execution_authorized is False


def test_missing_metadata_is_legacy_compatible():
    result = _scan("legacy issue body")
    assert ScanFinding.METADATA_MISSING in result.findings
    assert result.adoption_class == AdoptionClass.LEGACY_COMPATIBLE


def test_duplicate_identical_blocks_are_not_silently_collapsed():
    content = _block("  entity_id: issue-1") + "\n" + _block("  entity_id: issue-1")
    result = _scan(content)
    assert ScanFinding.METADATA_DUPLICATED_IDENTICAL in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_BLOCKED


def test_conflicting_blocks_are_adoption_blocked():
    content = _block("  entity_id: issue-1") + "\n" + _block("  entity_id: issue-2")
    result = _scan(content)
    assert ScanFinding.METADATA_CONFLICTING in result.findings
    assert ScanFinding.IDENTITY_FINDING_PRESENT in result.findings
    assert result.adoption_class == AdoptionClass.IDENTITY_QUARANTINED


def test_malformed_plus_valid_candidate_remains_blocked():
    content = "```yaml\nagent_os_issue_acceptance: [\n```\n" + _block("  entity_id: issue-1")
    result = _scan(content)
    assert ScanFinding.METADATA_MALFORMED in result.findings
    assert ScanFinding.METADATA_CONFLICTING in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_BLOCKED


def test_unknown_governed_field_remains_visible():
    result = _scan(_block("  entity_id: issue-1\n  future_governed_field: value"))
    assert ScanFinding.UNKNOWN_GOVERNED_FIELD in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_BLOCKED
    assert any(item.field_name == "future_governed_field" for item in result.provenance)


def test_missing_identity_can_only_be_adoption_candidate():
    result = _scan(_block("  owner_agent: Integration Manager"))
    assert result.adoption_class == AdoptionClass.ADOPTION_CANDIDATE
    assert result.strict_valid is False


def test_partial_or_unknown_pagination_fails_closed():
    result = _scan(_block("  entity_id: issue-1"), pagination_complete=False)
    assert ScanFinding.SOURCE_PARTIAL in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_BLOCKED


def test_inaccessible_source_fails_closed():
    result = _scan("", accessible=False)
    assert ScanFinding.SOURCE_INACCESSIBLE in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_BLOCKED


def test_unsupported_source_is_not_issueplan_source():
    result = _scan("", source_family="unsupported")
    assert ScanFinding.SOURCE_UNSUPPORTED in result.findings
    assert result.adoption_class == AdoptionClass.NOT_ISSUEPLAN_SOURCE


def test_revision_mismatch_is_stale():
    result = _scan(
        _block("  entity_id: issue-1"),
        expected_revision="rev-2",
    )
    assert ScanFinding.SOURCE_STALE in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_BLOCKED


def test_repeated_scan_is_deterministic():
    envelope = SourceEnvelope(
        source_locator="github:Blummer92/agent-os#1",
        source_revision="rev-1",
        content=_block("  entity_id: issue-1\n  required_files:\n    - scripts/a.py"),
    )
    assert scan_issueplan_source(envelope) == scan_issueplan_source(envelope)


def test_all_candidates_are_discovered_before_classification():
    content = (
        _block("  entity_id: issue-1")
        + "\ntext\n"
        + _block("  entity_id: issue-1\n  owner_agent: Integration Manager")
    )
    result = _scan(content)
    assert len(result.candidates) == 2
    assert ScanFinding.METADATA_CONFLICTING in result.findings
