from __future__ import annotations

from importlib.metadata import version

import pytest

pytest.importorskip(
    "hypothesis",
    reason="Hypothesis is selectively adopted and supplied task-scoped for #1477",
)

from hypothesis import given, settings, strategies as st

from scripts.agent_os_issue_acceptance.models import LinkedIssueParseStatus
from scripts.agent_os_issue_acceptance.parse_pr import parse_linked_issue_result

QUALIFIED_HYPOTHESIS_VERSION = "6.165.9"

KEYWORDS = st.sampled_from(
    ["close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"]
)
CASE_VARIANTS = st.sampled_from([str.lower, str.upper, str.title])
SEPARATOR = st.sampled_from([" ", "  ", "\t", ": ", " : ", ":\t"])
TRAILING = st.sampled_from(["", ".", ",", ";", "!", ")"])
ISSUE_NUMBER = st.integers(min_value=1, max_value=999_999)

BOILERPLATE = st.sampled_from(
    [
        "Related discussion: #{number}",
        "See #{number} for context.",
        "Follow-up to #{number}",
        "Prior work: #{number}",
    ]
)


def _explicit(keyword: str, transform, separator: str, number: int, trailing: str = "") -> str:
    return f"{transform(keyword)}{separator}#{number}{trailing}"


def test_hypothesis_uses_exact_qualified_version() -> None:
    assert version("hypothesis") == QUALIFIED_HYPOTHESIS_VERSION


@settings(max_examples=80, deadline=None, database=None, derandomize=True)
@given(
    keyword=KEYWORDS,
    transform=CASE_VARIANTS,
    separator=SEPARATOR,
    number=ISSUE_NUMBER,
    trailing=TRAILING,
)
def test_generated_single_authoritative_target_is_stable(
    keyword: str,
    transform,
    separator: str,
    number: int,
    trailing: str,
) -> None:
    result = parse_linked_issue_result(_explicit(keyword, transform, separator, number, trailing))
    assert result.status is LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == number


@settings(max_examples=80, deadline=None, database=None, derandomize=True)
@given(
    explicit_number=ISSUE_NUMBER,
    incidental_number=ISSUE_NUMBER,
    boilerplate=BOILERPLATE,
    keyword=KEYWORDS,
)
def test_generated_incidental_reference_never_outranks_explicit_body_target(
    explicit_number: int,
    incidental_number: int,
    boilerplate: str,
    keyword: str,
) -> None:
    body = f"{boilerplate.format(number=incidental_number)}\n\n{keyword} #{explicit_number}"
    result = parse_linked_issue_result(body)
    assert result.status is LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == explicit_number


@settings(max_examples=80, deadline=None, database=None, derandomize=True)
@given(first=ISSUE_NUMBER, second=ISSUE_NUMBER.filter(lambda value: value > 1))
def test_generated_distinct_explicit_targets_fail_closed(first: int, second: int) -> None:
    if first == second:
        second = 1 if first != 1 else 2
    result = parse_linked_issue_result(f"Closes #{first}\nFixes #{second}")
    assert result.status is LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.issue_number is None


@settings(max_examples=60, deadline=None, database=None, derandomize=True)
@given(number=ISSUE_NUMBER, keyword=KEYWORDS)
def test_generated_duplicate_target_is_idempotent(number: int, keyword: str) -> None:
    result = parse_linked_issue_result(f"Closes #{number}\n{keyword} #{number}")
    assert result.status is LinkedIssueParseStatus.RESOLVED
    assert result.issue_number == number


@settings(max_examples=60, deadline=None, database=None, derandomize=True)
@given(
    owner=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=12),
    repo=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_.-", min_size=1, max_size=12),
    number=ISSUE_NUMBER,
)
def test_generated_repository_qualified_target_never_becomes_local_issue(
    owner: str,
    repo: str,
    number: int,
) -> None:
    result = parse_linked_issue_result(f"Closes {owner}/{repo}#{number}")
    assert result.status is LinkedIssueParseStatus.MANUAL_REVIEW
    assert result.issue_number is None
    assert result.repository == f"{owner}/{repo}"
