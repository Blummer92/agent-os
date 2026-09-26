import pytest

from scripts.agent_os_issue_acceptance.models import LinkedIssueParseStatus
from scripts.agent_os_issue_acceptance.parse_pr import parse_linked_issue_result


@pytest.mark.parametrize(
    "body",
    [
        "This does NOT fix #223.",
        "This doesn't fix #223.",
        "Do not close #223.",
        "Example: Closes #223",
        "Example: \u201cCloses #223\u201d",
        "Historical text says Closes #223 as an example.",
    ],
)
def test_non_directive_closing_language_never_auto_resolves(body: str) -> None:
    result = parse_linked_issue_result(body)
    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.issue_number is None


def test_standalone_closing_directive_still_resolves() -> None:
    result = parse_linked_issue_result("Closes #223")
    assert result.status == LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == 223


def test_shorter_inner_fences_cannot_expose_example_closing_directives() -> None:
    for marker in ("`", "~"):
        for width in (4, 5, 7):
            outer = marker * width
            for inner_width in range(3, width):
                inner = marker * inner_width
                body = f"{outer}markdown\n{inner}\nCloses #223\n{inner}\n{outer}"
                result = parse_linked_issue_result(body)
                assert result.status == LinkedIssueParseStatus.NONE
                assert result.issue_number is None
                assert result.explicit_candidates == []
                assert parse_linked_issue_result(body + "\nCloses #224").issue_number == 224


def test_only_matching_blank_suffix_fence_closes_code_block() -> None:
    for outer, invalid in (("````", "~~~~"), ("~~~~", "````"),
                           ("```", "```text"), ("~~~", "~~~~ text")):
        body = f"{outer}\n{invalid}\nCloses #223\n{outer}\nCloses #224"
        result = parse_linked_issue_result(body)
        assert result.status == LinkedIssueParseStatus.RESOLVED
        assert result.issue_number == 224


def test_equal_or_longer_fence_with_whitespace_closes_code_block() -> None:
    for marker in ("`", "~"):
        for width in (3, 4, 6):
            body = f"{marker * 3}\nCloses #223\n  {marker * width} \t\nCloses #224"
            assert parse_linked_issue_result(body).issue_number == 224
