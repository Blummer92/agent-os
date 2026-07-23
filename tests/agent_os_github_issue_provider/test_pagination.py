from __future__ import annotations

import pytest

from scripts.agent_os_github_issue_provider.models import TrustedRepositoryIdentity
from scripts.agent_os_github_issue_provider.pagination import (
    PaginationDiagnosticError,
    parse_link_header,
    validated_next_page,
)


def _assert_kind(kind: str, header: str, **overrides: object) -> None:
    arguments: dict[str, object] = {
        "repository": "owner/repo",
        "current_page": 1,
        "per_page": 100,
        "state": "open",
    }
    arguments.update(overrides)
    with pytest.raises(PaginationDiagnosticError) as caught:
        validated_next_page(header, **arguments)  # type: ignore[arg-type]
    assert caught.value.kind == kind


def _identity(
    repository: str = "owner/repo", repository_id: int = 123
) -> TrustedRepositoryIdentity:
    return TrustedRepositoryIdentity(repository=repository, repository_id=repository_id)


def test_trusted_repository_identity_validation():
    assert _identity().repository_id == 123
    for repository in ("", "owner", "owner/repo/extra", "owner repo/name"):
        with pytest.raises(ValueError):
            TrustedRepositoryIdentity(repository=repository, repository_id=123)
    for repository_id in (0, -1, True, 1.5, "123"):
        with pytest.raises(ValueError):
            TrustedRepositoryIdentity(  # type: ignore[arg-type]
                repository="owner/repo", repository_id=repository_id
            )


def test_parse_link_header_valid_quoted_and_token_relations():
    for header in (
        '<https://api.github.com/repos/owner/repo/issues?page=2>; rel="next"',
        "<https://api.github.com/repos/owner/repo/issues?page=2>; rel=next",
    ):
        parsed = parse_link_header(header)
        assert parsed["next"].endswith("page=2")


def test_parse_link_header_handles_rfc_delimiters_and_multiple_relations():
    header = (
        '<https://api.github.com/repos/owner/repo/issues?page=2,preview=true>; '
        'rel="next last"; title="a,b"'
    )
    parsed = parse_link_header(header)
    assert parsed["next"].endswith("page=2,preview=true")
    assert parsed["last"] == parsed["next"]


def test_parse_link_header_absent_is_not_present_empty():
    assert parse_link_header(None) == {}
    with pytest.raises(PaginationDiagnosticError) as caught:
        parse_link_header("   ")
    assert caught.value.kind == "pagination:link-empty"


@pytest.mark.parametrize(
    "header",
    [
        "not a link",
        "http://example.com; rel=next",
        '<https://example.com>; rel="next',
        '<https://example.com; rel="next"',
        '<https://example.com>>; rel="next"',
        '<https://example.com>; title="Something"',
        '<https://example.com>; rel=""',
        '<https://ex.com/1>; rel="next", <https://ex.com/2>; rel="next"',
        '<https://ex.com/1>; rel="next next"',
    ],
)
def test_parse_link_header_failures_use_fixed_kind(header: str):
    with pytest.raises(PaginationDiagnosticError) as caught:
        parse_link_header(header)
    assert caught.value.kind == "pagination:link-parse"


def test_validated_next_page_success_and_omitted_trusted_parameters():
    for header in (
        '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=100&state=open>; rel="next"',
        '<https://api.github.com/repos/owner/repo/issues?page=2>; rel="next"',
        '<https://api.github.com/repos/owner/repo/issues?page=2&state=open>; rel="next"',
        '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=100>; rel="next"',
    ):
        assert validated_next_page(
            header,
            repository="owner/repo",
            current_page=1,
            per_page=100,
            state="open",
        ) == (2, False)


def test_matching_numeric_repository_path_is_accepted_with_trusted_identity():
    header = (
        '<https://api.github.com/repositories/123/issues?'
        'page=2&per_page=100&state=open>; rel="next"'
    )
    assert validated_next_page(
        header,
        repository="owner/repo",
        current_page=1,
        per_page=100,
        state="open",
        trusted_repository_identity=_identity(),
    ) == (2, False)


def test_matching_numeric_path_preserves_page_state_and_page_size_checks():
    identity = _identity()
    for kind, query in (
        ("pagination:next-page-non-advancing", "page=1"),
        ("pagination:next-per-page-changed", "page=2&per_page=50"),
        ("pagination:next-state-changed", "page=2&state=closed"),
    ):
        _assert_kind(
            kind,
            f'<https://api.github.com/repositories/123/issues?{query}>; rel="next"',
            trusted_repository_identity=identity,
        )


@pytest.mark.parametrize(
    "path",
    [
        "/repositories/0/issues",
        "/repositories/-123/issues",
        "/repositories/+123/issues",
        "/repositories/00123/issues",
        "/repositories/12.3/issues",
        "/repositories/not-a-number/issues",
        "/repositories//issues",
        "/repositories/123/issues/extra",
        "/repositories/123/pulls",
        "/repositories/123/issues/",
        "/repositories/123/456/issues",
        "/repositories/%31%32%33/issues",
        "/repositories/123%2Fissues",
    ],
)
def test_numeric_repository_path_alternate_forms_fail_closed(path: str):
    _assert_kind(
        "pagination:next-path",
        f'<https://api.github.com{path}?page=2>; rel="next"',
        trusted_repository_identity=_identity(),
    )


def test_numeric_repository_path_requires_independent_matching_identity():
    header = '<https://api.github.com/repositories/123/issues?page=2>; rel="next"'
    _assert_kind("pagination:next-path", header)
    _assert_kind(
        "pagination:next-path",
        header,
        trusted_repository_identity=_identity(repository_id=456),
    )
    _assert_kind(
        "pagination:next-path",
        header,
        trusted_repository_identity=_identity(repository="other/repo"),
    )


def test_validated_next_page_terminal_contract():
    assert validated_next_page(
        None, repository="a/b", current_page=1, per_page=10, state="open"
    ) == (None, True)
    assert validated_next_page(
        None, repository="a/b", current_page=2, per_page=10, state="open"
    ) == (None, False)
    assert validated_next_page(
        '<https://api.github.com/repos/owner/repo/issues?page=5>; rel="last"',
        repository="owner/repo",
        current_page=1,
        per_page=100,
        state="open",
    ) == (None, True)


@pytest.mark.parametrize(
    ("kind", "header"),
    [
        ("pagination:link-empty", " "),
        ("pagination:link-parse", "not a link"),
        (
            "pagination:next-scheme",
            '<http://api.github.com/repos/owner/repo/issues?page=2>; rel="next"',
        ),
        (
            "pagination:next-host",
            '<https://api.evil.com/repos/owner/repo/issues?page=2>; rel="next"',
        ),
        (
            "pagination:next-host",
            '<https://user@api.github.com/repos/owner/repo/issues?page=2>; rel="next"',
        ),
        (
            "pagination:next-host",
            '<https://api.github.com:443/repos/owner/repo/issues?page=2>; rel="next"',
        ),
        (
            "pagination:next-path",
            '<https://api.github.com/repos/other/repo/issues?page=2>; rel="next"',
        ),
        (
            "pagination:next-path",
            '<https://api.github.com/repositories/123/issues?page=2>; rel="next"',
        ),
        (
            "pagination:next-page-missing",
            '<https://api.github.com/repos/owner/repo/issues?state=open>; rel="next"',
        ),
        (
            "pagination:next-page-invalid",
            '<https://api.github.com/repos/owner/repo/issues?page=nope>; rel="next"',
        ),
        (
            "pagination:next-page-ambiguous",
            '<https://api.github.com/repos/owner/repo/issues?page=2&page=3>; rel="next"',
        ),
        (
            "pagination:next-page-non-advancing",
            '<https://api.github.com/repos/owner/repo/issues?page=1>; rel="next"',
        ),
        (
            "pagination:next-per-page-invalid",
            '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=nope>; rel="next"',
        ),
        (
            "pagination:next-per-page-ambiguous",
            '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=100&per_page=50>; rel="next"',
        ),
        (
            "pagination:next-per-page-changed",
            '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=50>; rel="next"',
        ),
        (
            "pagination:next-state-ambiguous",
            '<https://api.github.com/repos/owner/repo/issues?page=2&state=open&state=closed>; rel="next"',
        ),
        (
            "pagination:next-state-changed",
            '<https://api.github.com/repos/owner/repo/issues?page=2&state=closed>; rel="next"',
        ),
    ],
)
def test_validated_next_page_fixed_diagnostic_contract(kind: str, header: str):
    _assert_kind(kind, header)


def test_repeated_calls_do_not_retain_diagnostic_state():
    _assert_kind(
        "pagination:next-host",
        '<https://example.com/repos/owner/repo/issues?page=2>; rel="next"',
    )
    assert validated_next_page(
        '<https://api.github.com/repositories/123/issues?page=2>; rel="next"',
        repository="owner/repo",
        current_page=1,
        per_page=100,
        state="open",
        trusted_repository_identity=_identity(),
    ) == (2, False)
