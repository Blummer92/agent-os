"""Regression tests for #3157: GitHub-effective closing-reference detection.

The canonical detector answers "which issues would GitHub close if this PR
merged" — closing keyword anywhere in the title/body, negation ignored —
while parse_linked_issue_result keeps its stricter #2160 routing semantics.
PR #3156's prose "does **not** close #2772" closed #2772 at merge; the
detector must flag that shape and merge admission must block it.
"""

import pytest

from scripts.agent_os_issue_acceptance.checks import linked_issue
from scripts.agent_os_issue_acceptance.models import LinkedIssueParseStatus, Status
from scripts.agent_os_issue_acceptance.parse_pr import (
    GitHubEffectiveClosingReference,
    detect_github_effective_closing_references,
    normalize_issue_target,
    parse_linked_issue_result,
    unauthorized_closing_targets,
)

# Verbatim shape from PR #3156 (merged 2026-09-30), which closed #2772 at merge
# despite explicitly disavowing closure.
PR_3156_BODY = "Part of #2772. This PR deliberately does **not** close #2772."


def _refs(body, title=""):
    return [
        (reference.keyword, reference.target, reference.source)
        for reference in detect_github_effective_closing_references(body, title)
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Each closing keyword family.
        ("Closes #123", [("close", "#123", "body")]),
        ("Fixes #123", [("fix", "#123", "body")]),
        ("Resolves #123", [("resolve", "#123", "body")]),
        # Keyword variants and case.
        ("CLOSED #123", [("close", "#123", "body")]),
        ("fixed #123", [("fix", "#123", "body")]),
        ("RESOLVES #123", [("resolve", "#123", "body")]),
        # Negation never suppresses detection: GitHub closed #2772 on exactly
        # this class of prose, so negated wording fails closed.
        ("does not close #123", [("close", "#123", "body")]),
        ("do not fix #123", [("fix", "#123", "body")]),
        ("shouldn't resolve #123", [("resolve", "#123", "body")]),
        ("This PR will never fix #123.", [("fix", "#123", "body")]),
        # Non-closing linkage is not detected.
        ("Part of #123", []),
        ("Refs #123", []),
        ("See #123 for context.", []),
        ("#123", []),
        # Mid-sentence, colon, and URL forms.
        (
            "This incidentally closes #123 as a side effect.",
            [("close", "#123", "body")],
        ),
        ("Closes: #123", [("close", "#123", "body")]),
        (
            "Fixes https://github.com/other/repo/issues/7",
            [("fix", "other/repo#7", "body")],
        ),
        # Multiple references.
        (
            "Closes #1 and fixes #2",
            [("close", "#1", "body"), ("fix", "#2", "body")],
        ),
        # The verbatim #3156 shape: "Part of" does not shield the negated
        # closing keyword from GitHub's auto-close parser.
        (PR_3156_BODY, [("close", "#2772", "body")]),
        # Duplicates collapse to one reference.
        ("Closes #123\nCloses #123", [("close", "#123", "body")]),
        # Fail closed: keywords inside code spans and fenced blocks are
        # detected too — no masking special cases without reproduced GitHub
        # behavior proving the parser ignores them.
        ("`Fixes #123` in a code span", [("fix", "#123", "body")]),
        ("```\nFixes #123\n```", [("fix", "#123", "body")]),
    ],
)
def test_detects_closing_keyword_variants(text, expected):
    assert _refs(text) == expected


@pytest.mark.parametrize(
    ("body", "title", "expected"),
    [
        ("body text", "Resolves #42", [("resolve", "#42", "title")]),
        ("Fixes #1", "Closes #2", [("close", "#2", "title"), ("fix", "#1", "body")]),
    ],
)
def test_detects_title_references(body, title, expected):
    assert _refs(body, title=title) == expected


@pytest.mark.parametrize(
    ("body", "authorized", "expected"),
    [
        # Anything detected without canonical authorization is a blocker.
        ("Fixes #123", (), ("#123",)),
        ("Fixes #123", ("#123",), ()),
        # The canonical repository normalizes away in authorized targets.
        ("Fixes #123", ("Blummer92/agent-os#123",), ()),
        # Partial authorization leaves the remainder blocked.
        ("Fixes #123 and closes #124", ("#123",), ("#124",)),
        ("Fixes #123 and closes #124", ("#123", "#124"), ()),
        # Cross-repository targets are never confused with short targets.
        (
            "Fixes https://github.com/other/repo/issues/7",
            ("other/repo#7",),
            (),
        ),
        (
            "Fixes https://github.com/other/repo/issues/7",
            ("#7",),
            ("other/repo#7",),
        ),
        ("no references here", (), ()),
    ],
)
def test_unauthorized_closing_targets(body, authorized, expected):
    detected = detect_github_effective_closing_references(body)
    assert unauthorized_closing_targets(detected, authorized) == expected


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
