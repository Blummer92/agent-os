"""#3441: the canonical continuation validator proves the ``pulls`` listing too.

``validated_next_page`` historically accepted only ``/issues`` links. The
``endpoint`` keyword extends the identical rule set to the pull-request listing;
the default stays ``issues`` so existing behavior is unchanged.
"""

from __future__ import annotations

import pytest

from scripts.agent_os_github_issue_provider.models import TrustedRepositoryIdentity
from scripts.agent_os_github_issue_provider.pagination import (
    SUPPORTED_ENDPOINTS,
    PaginationDiagnosticError,
    validated_next_page,
)

NAMED_PULLS = (
    '<https://api.github.com/repos/owner/repo/pulls?state=all&per_page=100&page=2>; rel="next"'
)
NUMERIC_PULLS = (
    '<https://api.github.com/repositories/123/pulls?state=all&per_page=100&page=2>; rel="next"'
)


def _call(header, **overrides):
    arguments = {
        "repository": "owner/repo",
        "current_page": 1,
        "per_page": 100,
        "state": "all",
        "endpoint": "pulls",
    }
    arguments.update(overrides)
    return validated_next_page(header, **arguments)


def _kind(header, **overrides) -> str:
    with pytest.raises(PaginationDiagnosticError) as caught:
        _call(header, **overrides)
    return caught.value.kind


def test_supported_endpoints_are_exactly_issues_and_pulls() -> None:
    assert SUPPORTED_ENDPOINTS == frozenset({"issues", "pulls"})


def test_named_and_trusted_numeric_pulls_links_are_accepted() -> None:
    assert _call(NAMED_PULLS) == (2, False)
    identity = TrustedRepositoryIdentity(repository="owner/repo", repository_id=123)
    assert _call(NUMERIC_PULLS, trusted_repository_identity=identity) == (2, False)


def test_numeric_pulls_link_without_or_with_wrong_identity_fails_closed() -> None:
    assert _kind(NUMERIC_PULLS) == "pagination:next-path"
    wrong = TrustedRepositoryIdentity(repository="owner/repo", repository_id=124)
    assert _kind(NUMERIC_PULLS, trusted_repository_identity=wrong) == "pagination:next-path"
    other = TrustedRepositoryIdentity(repository="owner/other", repository_id=123)
    assert _kind(NUMERIC_PULLS, trusted_repository_identity=other) == "pagination:next-path"


def test_pulls_validation_rejects_an_issues_link_and_vice_versa() -> None:
    issues_link = NAMED_PULLS.replace("/pulls?", "/issues?")
    assert _kind(issues_link) == "pagination:next-path"
    assert validated_next_page(
        issues_link, repository="owner/repo", current_page=1, per_page=100, state="all"
    ) == (2, False)
    # The default endpoint is still issues: a pulls link is refused there.
    assert (
        _kind(NAMED_PULLS, endpoint="issues") == "pagination:next-path"
    )


@pytest.mark.parametrize(
    ("header", "kind"),
    [
        (NAMED_PULLS.replace("page=2", "page=3"), "pagination:next-page-non-contiguous"),
        (NAMED_PULLS.replace("page=2", "page=1"), "pagination:next-page-non-advancing"),
        (NAMED_PULLS.replace("per_page=100", "per_page=50"), "pagination:next-per-page-changed"),
        (NAMED_PULLS.replace("state=all", "state=open"), "pagination:next-state-changed"),
        (NAMED_PULLS.replace("api.github.com", "evil.example"), "pagination:next-host"),
        (NAMED_PULLS.replace("https://", "http://"), "pagination:next-scheme"),
        (NAMED_PULLS.replace("owner/repo", "owner/other"), "pagination:next-path"),
        (NAMED_PULLS.replace("&page=2", "&page=2&sort=updated"), "pagination:link-parse"),
    ],
)
def test_pulls_continuation_rules_are_the_canonical_rules(header, kind) -> None:
    assert _kind(header) == kind


def test_terminal_proof_semantics_are_unchanged_for_pulls() -> None:
    last_page = '<https://api.github.com/repos/owner/repo/pulls?page=1>; rel="prev"'
    assert _call(last_page, current_page=2) == (None, True)
    assert _call(None, current_page=1) == (None, True)  # single page: no Link header at all
    assert _call(None, current_page=2) == (None, False)  # later page without a header: unproven


def test_unsupported_endpoint_is_refused() -> None:
    for endpoint in ("commits", "", "pulls/1/files", "Issues"):
        with pytest.raises(ValueError, match="unsupported pagination endpoint"):
            _call(NAMED_PULLS, endpoint=endpoint)
