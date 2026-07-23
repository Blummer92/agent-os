from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from scripts.agent_os_github_issue_provider import provider as provider_module
from scripts.agent_os_github_issue_provider.models import (
    TransportAttempt,
    TransportResponse,
    TrustedRepositoryIdentity,
)
from scripts.agent_os_github_issue_provider.provider import PyGithubIssuePageProvider
from scripts.agent_os_github_issue_provider.transport import GitHubTransportError


def _issue_payload() -> dict[str, object]:
    return {
        "number": 1,
        "title": "One",
        "state": "open",
        "body": "B1",
        "html_url": "https://github.com/o/r/issues/1",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "labels": ["L1"],
    }


def _transport_for_link(link: str | None) -> MagicMock:
    transport = MagicMock()
    headers = {} if link is None else {"link": link}
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers=headers,
        payload=[_issue_payload()],
        attempts=(TransportAttempt(1),),
    )
    return transport


def _identity(
    repository: str = "owner/repo", repository_id: int = 123
) -> TrustedRepositoryIdentity:
    return TrustedRepositoryIdentity(repository=repository, repository_id=repository_id)


def _read(
    transport: MagicMock,
    *,
    identities: tuple[TrustedRepositoryIdentity, ...] = (),
):
    return PyGithubIssuePageProvider(
        transport, trusted_repository_identities=identities
    ).read_issue_page("owner/repo", page=1, per_page=100, state="open")


def test_provider_rejects_invalid_or_duplicate_trusted_identities():
    transport = MagicMock()
    with pytest.raises(TypeError):
        PyGithubIssuePageProvider(  # type: ignore[arg-type]
            transport, trusted_repository_identities=(object(),)
        )
    with pytest.raises(ValueError):
        PyGithubIssuePageProvider(
            transport,
            trusted_repository_identities=(_identity(), _identity(repository_id=456)),
        )


def test_provider_read_page_success_emits_no_diagnostic(caplog):
    transport = _transport_for_link(
        '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=100&state=open>; rel="next"'
    )

    with caplog.at_level(logging.WARNING):
        response = _read(transport)

    assert response.complete is True
    assert len(response.items) == 1
    assert response.items[0]["number"] == 1
    assert "source_revision" in response.items[0]
    assert response.next_page == 2
    assert response.terminal_page_proven is False
    assert "github issue-page provider diagnostic=" not in caplog.text
    transport.get_issue_page.assert_called_once_with(
        "owner/repo", page=1, per_page=100, state="open"
    )


def test_provider_accepts_verified_numeric_path_without_extra_request(caplog):
    transport = _transport_for_link(
        '<https://api.github.com/repositories/123/issues?'
        'page=2&per_page=100&state=open>; rel="next"'
    )

    with caplog.at_level(logging.WARNING):
        response = _read(transport, identities=(_identity(),))

    assert response.complete is True
    assert response.next_page == 2
    assert response.terminal_page_proven is False
    assert "github issue-page provider diagnostic=" not in caplog.text
    transport.get_issue_page.assert_called_once_with(
        "owner/repo", page=1, per_page=100, state="open"
    )


def test_provider_numeric_path_without_matching_identity_fails_closed(caplog):
    header = '<https://api.github.com/repositories/123/issues?page=2>; rel="next"'
    for identities in ((), (_identity(repository_id=456),), (_identity("other/repo"),)):
        caplog.clear()
        transport = _transport_for_link(header)
        with caplog.at_level(logging.WARNING):
            response = _read(transport, identities=identities)

        assert response.complete is False
        assert response.items == ()
        assert response.next_page is None
        assert response.error_kind == "malformed-response"
        assert caplog.text.count(
            "github issue-page provider diagnostic=pagination:next-path"
        ) == 1
        transport.get_issue_page.assert_called_once_with(
            "owner/repo", page=1, per_page=100, state="open"
        )


def test_provider_accepts_omitted_trusted_link_parameters(caplog):
    transport = _transport_for_link(
        '<https://api.github.com/repos/owner/repo/issues?page=2>; rel="next"'
    )

    with caplog.at_level(logging.WARNING):
        response = _read(transport)

    assert response.complete is True
    assert response.next_page == 2
    assert response.terminal_page_proven is False
    assert "github issue-page provider diagnostic=" not in caplog.text


def test_provider_terminal_page_emits_no_diagnostic(caplog):
    transport = MagicMock()
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers={"link": '<https://api.github.com/repos/owner/repo/issues?page=1>; rel="first"'},
        payload=[],
        attempts=(TransportAttempt(1),),
    )

    with caplog.at_level(logging.WARNING):
        response = PyGithubIssuePageProvider(transport).read_issue_page(
            "owner/repo", page=2, per_page=100, state="open"
        )

    assert response.complete is True
    assert response.items == ()
    assert response.next_page is None
    assert response.terminal_page_proven is True
    assert "github issue-page provider diagnostic=" not in caplog.text


def test_provider_read_page_transport_error(caplog):
    transport = MagicMock()
    transport.get_issue_page.side_effect = GitHubTransportError(
        "permission-denied",
        (TransportAttempt(1, "permission-denied"),),
    )

    with caplog.at_level(logging.WARNING):
        response = _read(transport)

    assert response.complete is False
    assert response.error_kind == "permission-denied"
    assert response.next_page is None
    assert "github issue-page provider diagnostic=transport:permission-denied" in caplog.text


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
def test_provider_emits_each_pagination_code_once(
    caplog, kind: str, header: str
):
    transport = _transport_for_link(header)

    with caplog.at_level(logging.WARNING):
        response = _read(transport)

    marker = f"github issue-page provider diagnostic={kind}"
    assert caplog.text.count(marker) == 1
    assert response.complete is False
    assert response.items == ()
    assert response.next_page is None
    assert response.error_kind == "malformed-response"
    transport.get_issue_page.assert_called_once_with(
        "owner/repo", page=1, per_page=100, state="open"
    )


def test_provider_unexpected_pagination_failure_hides_exception_message(
    caplog, monkeypatch
):
    transport = _transport_for_link(
        '<https://api.github.com/repos/owner/repo/issues?page=2>; rel="next"'
    )
    secret_message = "DO_NOT_LOG_EXCEPTION_SECRET"

    def fail_unexpectedly(*args, **kwargs):
        raise RuntimeError(secret_message)

    monkeypatch.setattr(provider_module, "validated_next_page", fail_unexpectedly)

    with caplog.at_level(logging.WARNING):
        response = _read(transport)

    assert response.complete is False
    assert response.error_kind == "malformed-response"
    assert "github issue-page provider diagnostic=pagination:unexpected" in caplog.text
    assert secret_message not in caplog.text


def test_provider_diagnostic_logs_exclude_sensitive_inputs(caplog):
    link_secret = "LINK_SECRET_TOKEN"
    title_secret = "TITLE_SECRET_TOKEN"
    body_secret = "BODY_SECRET_TOKEN"
    transport = MagicMock()
    payload = _issue_payload()
    payload["title"] = title_secret
    payload["body"] = body_secret
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers={
            "link": (
                "<https://api.github.com/repositories/456/issues"
                f"?page=2&token={link_secret}>; rel=\"next\""
            )
        },
        payload=[payload],
        attempts=(TransportAttempt(1),),
    )

    with caplog.at_level(logging.WARNING):
        response = _read(transport, identities=(_identity(),))

    assert response.complete is False
    assert "github issue-page provider diagnostic=pagination:next-path" in caplog.text
    assert link_secret not in caplog.text
    assert title_secret not in caplog.text
    assert body_secret not in caplog.text
    assert "repositories/456" not in caplog.text


def test_sequential_calls_do_not_contaminate_diagnostics(caplog):
    failing = _transport_for_link(
        '<https://api.github.com/repositories/456/issues?page=2>; rel="next"'
    )
    succeeding = _transport_for_link(
        '<https://api.github.com/repositories/123/issues?page=2>; rel="next"'
    )

    with caplog.at_level(logging.WARNING):
        failed_response = _read(failing, identities=(_identity(),))
        caplog.clear()
        successful_response = _read(succeeding, identities=(_identity(),))

    assert failed_response.complete is False
    assert successful_response.complete is True
    assert "github issue-page provider diagnostic=" not in caplog.text


def test_existing_non_pagination_failure_contracts_remain_stable(caplog):
    transport = MagicMock()
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers={},
        payload={"message": "not-a-page"},
        attempts=(TransportAttempt(1),),
    )

    with caplog.at_level(logging.WARNING):
        response = _read(transport)

    assert response.complete is False
    assert response.error_kind == "malformed-response"
    assert "github issue-page provider diagnostic=payload-shape" in caplog.text
