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
