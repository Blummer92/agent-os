from __future__ import annotations

from unittest.mock import MagicMock

from scripts.agent_os_github_issue_provider.models import TransportAttempt, TransportResponse
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


def test_provider_read_page_success():
    transport = MagicMock()
    headers = {
        "link": '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=100&state=open>; rel="next"'
    }
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers=headers,
        payload=[_issue_payload()],
        attempts=(TransportAttempt(1),),
    )

    provider = PyGithubIssuePageProvider(transport)
    response = provider.read_issue_page("owner/repo", page=1, per_page=100, state="open")

    assert response.complete is True
    assert len(response.items) == 1
    assert response.items[0]["number"] == 1
    assert "source_revision" in response.items[0]
    assert response.next_page == 2
    assert response.terminal_page_proven is False
    assert provider.last_diagnostic_kind is None


def test_provider_read_page_terminal():
    transport = MagicMock()
    headers = {"link": '<https://api.github.com/repos/owner/repo/issues?page=1>; rel="first"'}
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers=headers,
        payload=[],
        attempts=(TransportAttempt(1),),
    )

    provider = PyGithubIssuePageProvider(transport)
    response = provider.read_issue_page("owner/repo", page=2, per_page=100, state="open")

    assert response.complete is True
    assert len(response.items) == 0
    assert response.next_page is None
    assert response.terminal_page_proven is True
    assert provider.last_diagnostic_kind is None


def test_provider_read_page_transport_error():
    transport = MagicMock()
    transport.get_issue_page.side_effect = GitHubTransportError(
        "permission-denied",
        (TransportAttempt(1, "permission-denied"),),
    )

    provider = PyGithubIssuePageProvider(transport)
    response = provider.read_issue_page("owner/repo", page=1, per_page=100, state="open")

    assert response.complete is False
    assert response.error_kind == "permission-denied"
    assert response.next_page is None
    assert provider.last_diagnostic_kind == "transport:permission-denied"


def test_provider_read_page_distinguishes_payload_shape_failure():
    transport = MagicMock()
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers={},
        payload={"message": "not-a-page"},
        attempts=(TransportAttempt(1),),
    )
    provider = PyGithubIssuePageProvider(transport)

    response = provider.read_issue_page(
        "owner/repo",
        page=1,
        per_page=100,
        state="open",
    )

    assert response.complete is False
    assert response.error_kind == "malformed-response"
    assert provider.last_diagnostic_kind == "payload-shape"


def test_provider_read_page_distinguishes_item_shape_failure():
    transport = MagicMock()
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers={},
        payload=["not-a-mapping"],
        attempts=(TransportAttempt(1),),
    )
    provider = PyGithubIssuePageProvider(transport)

    response = provider.read_issue_page(
        "owner/repo",
        page=1,
        per_page=100,
        state="open",
    )

    assert response.complete is False
    assert response.error_kind == "malformed-response"
    assert provider.last_diagnostic_kind == "item-shape"


def test_provider_read_page_distinguishes_revision_failure():
    transport = MagicMock()
    payload = _issue_payload()
    payload.pop("updated_at")
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers={},
        payload=[payload],
        attempts=(TransportAttempt(1),),
    )
    provider = PyGithubIssuePageProvider(transport)

    response = provider.read_issue_page(
        "owner/repo",
        page=1,
        per_page=100,
        state="open",
    )

    assert response.complete is False
    assert response.error_kind == "malformed-response"
    assert provider.last_diagnostic_kind == "revision-normalization"


def test_provider_read_page_distinguishes_pagination_failure():
    transport = MagicMock()
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers={
            "link": '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=100>; rel="next"'
        },
        payload=[_issue_payload()],
        attempts=(TransportAttempt(1),),
    )
    provider = PyGithubIssuePageProvider(transport)

    response = provider.read_issue_page(
        "owner/repo",
        page=1,
        per_page=100,
        state="open",
    )

    assert response.complete is False
    assert response.error_kind == "malformed-response"
    assert provider.last_diagnostic_kind == "pagination-validation"
