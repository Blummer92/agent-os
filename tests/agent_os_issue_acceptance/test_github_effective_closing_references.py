"""Regression tests for #3157: GitHub-effective closing-reference detection.

The canonical detector answers "which issues would GitHub close if this PR
merged" — closing keyword anywhere in the title/body, negation ignored —
while parse_linked_issue_result keeps its stricter #2160 routing semantics.
PR #3156's prose "does **not** close #2772" closed #2772 at merge; the
detector must flag that shape and merge admission must block it.
"""

from scripts.agent_os_issue_acceptance.checks import linked_issue
from scripts.agent_os_issue_acceptance.models import LinkedIssueParseStatus, Status
from scripts.agent_os_issue_acceptance.parse_pr import (
    GitHubEffectiveClosingReference,
    detect_github_effective_closing_references,
    normalize_issue_target,
    parse_linked_issue_result,
)

# Verbatim shape from PR #3156 (merged 2026-09-30), which closed #2772 at merge
# despite explicitly disavowing closure.
PR_3156_BODY = "Part of #2772. This PR deliberately does **not** close #2772."


def _refs(body, title=""):
    return [
        (reference.keyword, reference.target, reference.source)
        for reference in detect_github_effective_closing_references(body, title)
    ]


def test_detects_each_closing_keyword_family():
    assert _refs("Closes #123") == [("close", "#123", "body")]
    assert _refs("Fixes #123") == [("fix", "#123", "body")]
    assert _refs("Resolves #123") == [("resolve", "#123", "body")]


def test_detects_keyword_variants_and_case():
    assert _refs("CLOSED #123") == [("close", "#123", "body")]
    assert _refs("fixed #123") == [("fix", "#123", "body")]
    assert _refs("RESOLVES #123") == [("resolve", "#123", "body")]


def test_negation_does_not_suppress_detection():
    # GitHub closed #2772 on exactly this class of prose; negated wording
    # must fail closed, never be treated as non-closing.
    assert _refs("does not close #123") == [("close", "#123", "body")]
    assert _refs("do not fix #123") == [("fix", "#123", "body")]
    assert _refs("shouldn't resolve #123") == [("resolve", "#123", "body")]
    assert _refs("This PR will never fix #123.") == [("fix", "#123", "body")]


def test_non_closing_linkage_is_not_detected():
    assert _refs("Part of #123") == []
    assert _refs("Refs #123") == []
    assert _refs("See #123 for context.") == []


def test_detects_mid_sentence_colon_and_url_forms():
    assert _refs("This incidentally closes #123 as a side effect.") == [
        ("close", "#123", "body")
    ]
    assert _refs("Closes: #123") == [("close", "#123", "body")]
    assert _refs("Fixes https://github.com/other/repo/issues/7") == [
        ("fix", "other/repo#7", "body")
    ]


def test_detects_multiple_references():
    assert _refs("Closes #1 and fixes #2") == [
        ("close", "#1", "body"),
        ("fix", "#2", "body"),
    ]


def test_detects_title_references():
    assert _refs("body text", title="Resolves #42") == [("resolve", "#42", "title")]


def test_verbatim_3156_shape_is_detected():
    # The exact #3156 prose: "Part of" does not shield the negated closing
    # keyword from GitHub's auto-close parser.
    assert _refs(PR_3156_BODY) == [("close", "#2772", "body")]


def test_code_spans_and_fences_are_masked():
    assert _refs("`Fixes #123` in a code span") == []
    assert _refs("```\nFixes #123\n```") == []


def test_duplicates_collapse_to_one_reference():
    assert _refs("Closes #123\nCloses #123") == [("close", "#123", "body")]


def test_reference_fields_are_validated():
    reference = GitHubEffectiveClosingReference(
        keyword="close", target="#123", source="body"
    )
    assert reference.keyword == "close"
    for bad in (
        {"keyword": "closes", "target": "#123", "source": "body"},
        {"keyword": "close", "target": "123", "source": "body"},
        {"keyword": "close", "target": "#123", "source": "summary"},
    ):
        try:
            GitHubEffectiveClosingReference(**bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad}")


def test_normalize_issue_target_canonical_form():
    assert normalize_issue_target("#123") == "#123"
    assert normalize_issue_target("Foo/Bar#12") == "foo/bar#12"
    assert (
        normalize_issue_target("https://github.com/Blummer92/agent-os/issues/3157")
        == "#3157"
    )


def test_routing_parser_semantics_are_unchanged():
    # #2160 routing contract preserved: the verbatim #3156 prose stays
    # manual-review for routing even though it is GitHub-effective closing.
    result = parse_linked_issue_result(PR_3156_BODY)
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.issue_number is None


def test_linked_issue_check_surfaces_github_effective_closing():
    result = linked_issue.check(PR_3156_BODY)
    assert result.status == Status.MANUAL_REVIEW
    assert "close #2772" in result.message
    assert "GitHub-effective closing references detected" in result.message
    assert "merge admission rejects" in result.message
    assert (
        "github_effective_closing keyword=close target=#2772 source=body"
        in result.evidence
    )


def test_linked_issue_check_pass_case_reports_closing_evidence():
    result = linked_issue.check("Fixes #123")
    assert result.status == Status.PASS
    assert (
        "github_effective_closing keyword=fix target=#123 source=body"
        in result.evidence
    )
