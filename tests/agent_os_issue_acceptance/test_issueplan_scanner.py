from scripts.agent_os_issue_acceptance.issueplan_scanner import (
    AdoptionClass,
    ScanFinding,
    SourceEnvelope,
    scan_issueplan_source,
)


def _block(body: str) -> str:
    return f"```yaml\nagent_os_issue_acceptance:\n{body}\n```"


def _strict_body() -> str:
    return "\n".join(
        [
            "  profile_version: issueplan-core/v1",
            "  entity_id: issue-1",
            "  owner_agent: Integration Manager",
            "  source_of_truth: GitHub",
            "  external_writes: no-external-write",
            "  required_files: []",
            "  forbidden_paths: []",
            "  required_tests: []",
            "  required_docs: []",
            "  manual_review: []",
            "  documentation_impact: docs-not-required",
        ]
    )


def _scan(content: str, **kwargs):
    return scan_issueplan_source(
        SourceEnvelope(
            source_locator="github:Blummer92/agent-os#1",
            source_revision="rev-1",
            content=content,
            **kwargs,
        )
    )


def test_complete_strict_block_is_strict_native_and_never_authorized():
    result = _scan(_block(_strict_body()))
    assert ScanFinding.METADATA_SINGLE in result.findings
    assert result.adoption_class == AdoptionClass.STRICT_NATIVE
    assert result.strict_valid is True
    assert result.execution_authorized is False


def test_identity_only_block_is_not_strict_native():
    result = _scan(_block("  entity_id: issue-1"))
    assert ScanFinding.STRICT_FIELDS_INCOMPLETE in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_CANDIDATE
    assert result.strict_valid is False


def test_partial_block_is_not_strict_native():
    result = _scan(
        _block(
            "  profile_version: issueplan-core/v1\n"
            "  entity_id: issue-1\n"
            "  owner_agent: Integration Manager"
        )
    )
    assert ScanFinding.STRICT_FIELDS_INCOMPLETE in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_CANDIDATE


def test_unsupported_profile_version_is_not_strict_native():
    result = _scan(_block(_strict_body().replace("issueplan-core/v1", "issueplan-core/v9")))
    assert ScanFinding.PROFILE_VERSION_UNSUPPORTED in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_CANDIDATE


def test_missing_metadata_is_legacy_compatible():
    result = _scan("legacy issue body")
    assert ScanFinding.METADATA_MISSING in result.findings
    assert result.adoption_class == AdoptionClass.LEGACY_COMPATIBLE


def test_duplicate_identical_blocks_are_not_silently_collapsed():
    content = _block(_strict_body()) + "\n" + _block(_strict_body())
    result = _scan(content)
    assert ScanFinding.METADATA_DUPLICATED_IDENTICAL in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_BLOCKED


def test_conflicting_blocks_are_identity_quarantined():
    content = _block(_strict_body()) + "\n" + _block(
        _strict_body().replace("entity_id: issue-1", "entity_id: issue-2")
    )
    result = _scan(content)
    assert ScanFinding.METADATA_CONFLICTING in result.findings
    assert ScanFinding.IDENTITY_FINDING_PRESENT in result.findings
    assert result.adoption_class == AdoptionClass.IDENTITY_QUARANTINED


def test_malformed_intended_metadata_plus_valid_candidate_remains_blocked():
    content = "```yaml\nagent_os_issue_acceptance: [\n```\n" + _block(_strict_body())
    result = _scan(content)
    assert ScanFinding.METADATA_MALFORMED in result.findings
    assert ScanFinding.METADATA_CONFLICTING in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_BLOCKED


def test_unrelated_valid_yaml_is_ignored():
    content = "```yaml\nexample:\n  enabled: true\n```\n" + _block(_strict_body())
    result = _scan(content)
    assert len(result.candidates) == 1
    assert ScanFinding.METADATA_MALFORMED not in result.findings
    assert result.adoption_class == AdoptionClass.STRICT_NATIVE


def test_unrelated_malformed_yaml_is_ignored():
    content = "```yaml\nexample: [\n```\n" + _block(_strict_body())
    result = _scan(content)
    assert len(result.candidates) == 1
    assert ScanFinding.METADATA_MALFORMED not in result.findings
    assert result.adoption_class == AdoptionClass.STRICT_NATIVE


def test_unknown_governed_field_remains_visible():
    result = _scan(_block(_strict_body() + "\n  future_governed_field: value"))
    assert ScanFinding.UNKNOWN_GOVERNED_FIELD in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_BLOCKED
    assert any(item.field_name == "future_governed_field" for item in result.provenance)


def test_missing_identity_is_legacy_compatible():
    result = _scan(_block("  owner_agent: Integration Manager"))
    assert result.adoption_class == AdoptionClass.LEGACY_COMPATIBLE
    assert result.strict_valid is False


def test_partial_or_unknown_pagination_fails_closed():
    result = _scan(_block(_strict_body()), pagination_complete=False)
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
        _block(_strict_body()),
        expected_revision="rev-2",
    )
    assert ScanFinding.SOURCE_STALE in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_BLOCKED


def test_repeated_scan_is_deterministic():
    envelope = SourceEnvelope(
        source_locator="github:Blummer92/agent-os#1",
        source_revision="rev-1",
        content=_block(_strict_body()),
    )
    assert scan_issueplan_source(envelope) == scan_issueplan_source(envelope)


def test_all_candidates_are_discovered_before_classification():
    content = (
        _block(_strict_body())
        + "\ntext\n"
        + _block(_strict_body().replace("owner_agent: Integration Manager", "owner_agent: QA / Test Agent"))
    )
    result = _scan(content)
    assert len(result.candidates) == 2
    assert ScanFinding.METADATA_CONFLICTING in result.findings
