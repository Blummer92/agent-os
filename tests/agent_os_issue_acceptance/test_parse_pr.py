from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import LinkedIssueParseStatus
from scripts.agent_os_issue_acceptance.parse_pr import (
    missing_final_report_fields,
    parse_linked_issue,
    parse_linked_issue_result,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_linked_issue_from_closing_keyword():
    body = (FIXTURES / "pr_body_valid.md").read_text()
    result = parse_linked_issue_result(body)
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 164
    assert parse_linked_issue(body) == 164


def test_missing_linked_issue_returns_none():
    body = (FIXTURES / "pr_body_missing_report_fields.md").read_text()
    result = parse_linked_issue_result(body)
    assert result.status == LinkedIssueParseStatus.NONE
    assert parse_linked_issue(body) is None


def test_first_match_regression_prefers_explicit_target():
    body = (FIXTURES / "pr_body_ambiguous_first_match.md").read_text()
    result = parse_linked_issue_result(body)
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223
    assert [candidate.issue_number for candidate in result.bare_references] == [180]


@pytest.mark.parametrize(
    "keyword",
    ["close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"],
)
def test_supported_keyword_variants_resolve(keyword):
    for rendered in (keyword, keyword.upper(), keyword.title()):
        result = parse_linked_issue_result(f"{rendered} #223")
        assert result.status == LinkedIssueParseStatus.RESOLVED
        assert result.issue_number == 223


def test_optional_colon_resolves():
    result = parse_linked_issue_result("Closes: #223")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223


def test_incidental_title_reference_does_not_override_explicit_body_target():
    result = parse_linked_issue_result("Closes #223", "Follow-up to #180")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223
    assert result.explicit_candidates[0].source == "body"
    assert result.bare_references[0].source == "title"


def test_same_explicit_target_repeated_deduplicates_by_target():
    result = parse_linked_issue_result("Closes #223\nFixes #223")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223
    assert len(result.explicit_candidates) == 2


def test_multiple_unique_explicit_targets_require_manual_review():
    result = parse_linked_issue_result("Closes #223\nFixes #224")
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.issue_number is None
    assert "#223" in result.reasons[0]
    assert "#224" in result.reasons[0]
    assert parse_linked_issue("Closes #223\nFixes #224") is None


def test_conflicting_title_and_body_targets_require_manual_review():
    result = parse_linked_issue_result("Closes #224", "Fixes #223")
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert {candidate.source for candidate in result.explicit_candidates} == {"title", "body"}


@pytest.mark.parametrize("body", ["Related to #223.", "Related to #223 and #224."])
def test_bare_references_only_require_manual_review(body):
    result = parse_linked_issue_result(body)
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.explicit_candidates == []
    assert result.bare_references


def test_explicit_target_resolves_despite_unrelated_bare_reference():
    result = parse_linked_issue_result("See #180 for context.\n\nCloses #223.")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223


def test_addresses_without_supported_target_requires_manual_review():
    result = parse_linked_issue_result("Addresses #223")
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.bare_references[0].keyword == "addresses"


def test_addresses_does_not_override_supported_target():
    result = parse_linked_issue_result("Addresses #180 for context.\n\nCloses #223.")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223


def test_repository_qualified_target_preserves_identity_and_requires_review():
    result = parse_linked_issue_result("Fixes owner/repository#223")
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.repository == "owner/repository"
    assert result.explicit_candidates[0].normalized_target == "owner/repository#223"


def test_malformed_authoritative_syntax_requires_manual_review():
    result = parse_linked_issue_result("Closes issue #223")
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.bare_references[0].keyword == "closes"


@pytest.mark.parametrize(
    "body",
    [
        "```text\nCloses #223\n```",
        "Use `Closes #223` in the PR body.",
        "> Closes #223",
        "<!-- Closes #223 -->",
    ],
)
def test_non_authoritative_markdown_contexts_do_not_auto_resolve(body):
    result = parse_linked_issue_result(body)
    assert result.status == LinkedIssueParseStatus.NONE


@pytest.mark.parametrize("body", ["    Closes #223", "\tCloses #223"])
def test_indented_markdown_code_only_does_not_auto_resolve(body):
    result = parse_linked_issue_result(body)
    assert result.status == LinkedIssueParseStatus.NONE
    assert result.issue_number is None


def test_prose_target_after_indented_example_resolves():
    result = parse_linked_issue_result("    Closes #180\nCloses #223")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223


def test_indented_example_plus_bare_reference_requires_manual_review():
    result = parse_linked_issue_result("    Closes #180\nSee #223 for context.")
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.issue_number is None
    assert [candidate.issue_number for candidate in result.bare_references] == [223]


def test_valid_target_outside_example_context_resolves():
    body = "```text\nCloses #180\n```\n\nCloses #223"
    result = parse_linked_issue_result(body)
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223


def test_candidate_evidence_retains_source_keyword_and_position():
    result = parse_linked_issue_result("Closes #223")
    candidate = result.explicit_candidates[0]
    assert candidate.source == "body"
    assert candidate.keyword == "closes"
    assert candidate.position >= 0
    assert result.reasons


def test_required_final_report_fields_present():
    body = (FIXTURES / "pr_body_valid.md").read_text()
    assert missing_final_report_fields(body) == []


def test_required_final_report_fields_missing():
    body = (FIXTURES / "pr_body_missing_report_fields.md").read_text()
    assert "linked issue" in missing_final_report_fields(body)
    assert "tests run" in missing_final_report_fields(body)
