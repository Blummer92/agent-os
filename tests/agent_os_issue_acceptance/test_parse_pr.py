from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import LinkedIssueParseStatus
from scripts.agent_os_issue_acceptance.parse_pr import (
    detect_github_effective_closing_references,
    dual_implemented_issue_claims,
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


@pytest.mark.parametrize("keyword", ["close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"])
def test_supported_keyword_variants_resolve(keyword):
    for rendered in (keyword, keyword.upper(), keyword.title()):
        result = parse_linked_issue_result(f"{rendered} #223")
        assert result.status == LinkedIssueParseStatus.RESOLVED
        assert result.issue_number == 223


def test_optional_colon_resolves():
    result = parse_linked_issue_result("Closes: #223")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223


@pytest.mark.parametrize(
    "body,title,status,issue_number",
    [
        ("", "Fixes #100", LinkedIssueParseStatus.MANUAL_REVIEW, None),
        ("Closes #123", "", LinkedIssueParseStatus.RESOLVED, 123),
        ("Fixes https://github.com/Blummer92/agent-os/issues/123", "", LinkedIssueParseStatus.RESOLVED, 123),
        ("", "Fixes https://github.com/Blummer92/agent-os/issues/123", LinkedIssueParseStatus.MANUAL_REVIEW, None),
        ("Related to #123", "", LinkedIssueParseStatus.MANUAL_REVIEW, None),
        ("Closes #223\nFixes #223", "", LinkedIssueParseStatus.RESOLVED, 223),
        ("Closes #223\nFixes #224", "", LinkedIssueParseStatus.MANUAL_REVIEW, None),
        ("Closes owner/repo#77", "", LinkedIssueParseStatus.MANUAL_REVIEW, None),
        ("Closes https://github.com/owner/repo/issues/77", "", LinkedIssueParseStatus.MANUAL_REVIEW, None),
    ],
)
def test_github_linkage_semantics_matrix(body, title, status, issue_number):
    result = parse_linked_issue_result(body, title)
    assert result.status == status
    assert result.issue_number == issue_number


def test_incidental_title_reference_does_not_override_explicit_body_target():
    result = parse_linked_issue_result("Closes #223", "Follow-up to #180")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223
    assert result.explicit_candidates[0].source == "body"
    assert result.bare_references[0].source == "title"


def test_title_closing_keyword_is_retained_as_non_authoritative_evidence():
    result = parse_linked_issue_result("Closes #224", "Fixes #223")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 224
    assert [candidate.source for candidate in result.explicit_candidates] == ["body"]
    assert result.bare_references[0].source == "title"
    assert result.bare_references[0].keyword == "fixes"


def test_same_explicit_target_repeated_deduplicates_by_target():
    result = parse_linked_issue_result("Closes #223\nFixes #223")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223
    assert len(result.explicit_candidates) == 2


def test_multiple_unique_explicit_targets_require_manual_review():
    result = parse_linked_issue_result("Closes #223\nFixes #224")
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert "#223" in result.reasons[0] and "#224" in result.reasons[0]
    assert parse_linked_issue("Closes #223\nFixes #224") is None


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


@pytest.mark.parametrize("body", ["```text\nCloses #223\n```", "Use `Closes #223` in the PR body.", "> Closes #223", "<!-- Closes #223 -->", "```text\nFixes https://github.com/Blummer92/agent-os/issues/223\n```"])
def test_non_authoritative_markdown_contexts_do_not_auto_resolve(body):
    assert parse_linked_issue_result(body).status == LinkedIssueParseStatus.NONE


@pytest.mark.parametrize("body", ["    Closes #223", "\tCloses #223"])
def test_indented_markdown_code_only_does_not_auto_resolve(body):
    result = parse_linked_issue_result(body)
    assert result.status == LinkedIssueParseStatus.NONE
    assert result.issue_number is None


def test_list_continuation_indent_does_not_auto_resolve():
    result = parse_linked_issue_result("- Example:\n    Closes #223")
    assert result.status == LinkedIssueParseStatus.NONE
    assert result.issue_number is None


def test_prose_target_after_indented_example_resolves():
    result = parse_linked_issue_result("    Closes #180\nCloses #223")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223


def test_indented_example_plus_bare_reference_requires_manual_review():
    result = parse_linked_issue_result("    Closes #180\nSee #223 for context.")
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
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


# --- #2991: one primary PR cannot claim two distinct implemented issues ------
#
# Regression fixture: during #2854 execution a distinct defect was logged as
# #2989, and PR #2990 linked BOTH issues as implemented ("Fixes #2854" /
# "Fixes #2989"), conflating the prerequisite code repair with the parent
# activation task. The parent must be linked as dependency/consumer evidence,
# never a second closing target.


def _closing_refs(body, title=""):
    return detect_github_effective_closing_references(body, title)


def test_2991_single_closing_target_carries_no_lineage_conflict():
    """The focused prerequisite-fix PR closes only its own issue (#2989)."""
    assert dual_implemented_issue_claims(_closing_refs("Fixes #2989")) == ()


def test_2991_dual_closing_targets_flag_parent_and_prerequisite():
    """The #2990 shape — body closes both #2854 and #2989 — is flagged."""
    body = "Fixes #2989\n\nAlso fixes #2854"
    assert dual_implemented_issue_claims(_closing_refs(body)) == ("#2854", "#2989")


def test_2991_dual_closing_targets_detected_across_title_and_body():
    """Title linkage counts: title + body each closing a different issue."""
    refs = _closing_refs("Fixes #2989", title="Fix #2854")
    assert dual_implemented_issue_claims(refs) == ("#2854", "#2989")


def test_2991_negated_prose_still_claims_the_target():
    """GitHub ignores negation at merge, so it counts as a claimed target."""
    body = "Fixes #2989\n\nThis does not close #2854"
    assert dual_implemented_issue_claims(_closing_refs(body)) == ("#2854", "#2989")


def test_2991_dependency_style_parent_linkage_passes():
    """Parent as consumer evidence — Part of / Refs — is not an implemented claim."""
    body = "Fixes #2989\n\nPart of #2854. Refs #2854."
    assert dual_implemented_issue_claims(_closing_refs(body)) == ()


def test_2991_repeated_single_target_is_not_dual():
    assert dual_implemented_issue_claims(_closing_refs("Fixes #2989\nFixes #2989")) == ()


def test_2991_cross_repository_target_does_not_trigger():
    """GitHub never merge-closes cross-repo targets, so they stay out of scope."""
    body = "Fixes #2989\nFixes other/repo#45"
    assert dual_implemented_issue_claims(_closing_refs(body)) == ()
