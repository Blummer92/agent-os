import pytest

from scripts.agent_os_issue_acceptance.models import (
    AcceptanceInput,
    LinkedIssueParseStatus,
    Status,
)
from scripts.agent_os_issue_acceptance.parse_pr import parse_linked_issue_result
from scripts.agent_os_issue_acceptance.policy import evaluate_acceptance


@pytest.mark.parametrize("keyword", ["Closes", "Fixes", "Resolves"])
def test_authoritative_linkage_phrases_resolve(keyword):
    result = parse_linked_issue_result(f"{keyword} #223")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223


def test_incidental_reference_before_authoritative_link_does_not_win():
    result = parse_linked_issue_result(
        "See #180 for roadmap context.\n\nCloses #223."
    )
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223
    assert [candidate.issue_number for candidate in result.bare_references] == [180]


def test_addresses_is_explicitly_unsupported_and_requires_review():
    result = parse_linked_issue_result("Addresses #223")
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.issue_number is None
    assert result.bare_references[0].keyword == "addresses"


@pytest.mark.parametrize(
    "pr_body",
    [
        "",
        "Related to #223.",
        "Closes #223\nFixes #224",
        "Closes issue #223",
        "Addresses #223",
    ],
)
def test_missing_ambiguous_or_malformed_linkage_never_passes(pr_body):
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body="",
            pr_body=pr_body,
            changed_files=[],
            diff_text="",
        )
    )
    assert report.overall_status != Status.PASS
    assert report.linked_issue is None


def test_multiple_authoritative_targets_route_to_manual_review():
    result = parse_linked_issue_result("Closes #223\nFixes #224")
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.issue_number is None
    assert {candidate.issue_number for candidate in result.explicit_candidates} == {223, 224}


def test_markdown_examples_do_not_become_authoritative_links():
    result = parse_linked_issue_result(
        "```text\nCloses #180\n```\n\nCloses #223"
    )
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223


def test_bare_reference_only_is_manual_review_not_resolution():
    result = parse_linked_issue_result("See #223 for context.")
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.issue_number is None
    assert result.bare_references
