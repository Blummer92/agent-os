from __future__ import annotations

import logging
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


def test_provider_read_page_success(caplog):
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

    with caplog.at_level(logging.WARNING):
        response = PyGithubIssuePageProvider(transport).read_issue_page(
            "owner/repo", page=1, per_page=100, state="open"
        )

    assert response.complete is True
    assert len(response.items) == 1
    assert response.items[0]["number"] == 1
    assert "source_revision" in response.items[0]
    assert response.next_page == 2
    assert response.terminal_page_proven is False
    assert "github issue-page provider diagnostic=" not in caplog.text


def test_provider_read_page_terminal(caplog):
    transport = MagicMock()
    headers = {"link": '<https://api.github.com/repos/owner/repo/issues?page=1>; rel="first"'}
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers=headers,
        payload=[],
        attempts=(TransportAttempt(1),),
    )

    with caplog.at_level(logging.WARNING):
        response = PyGithubIssuePageProvider(transport).read_issue_page(
            "owner/repo", page=2, per_page=100, state="open"
        )

    assert response.complete is True
    assert len(response.items) == 0
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
        response = PyGithubIssuePageProvider(transport).read_issue_page(
            "owner/repo", page=1, per_page=100, state="open"
        )

    assert response.complete is False
    assert response.error_kind == "permission-denied"
    assert response.next_page is None
    assert "github issue-page provider diagnostic=transport:permission-denied" in caplog.text


def test_provider_read_page_distinguishes_payload_shape_failure(caplog):
    transport = MagicMock()
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers={},
        payload={"message": "not-a-page"},
        attempts=(TransportAttempt(1),),
    )

    with caplog.at_level(logging.WARNING):
        response = PyGithubIssuePageProvider(transport).read_issue_page(
            "owner/repo", page=1, per_page=100, state="open"
        )

    assert response.complete is False
    assert response.error_kind == "malformed-response"
    assert "github issue-page provider diagnostic=payload-shape" in caplog.text


def test_provider_read_page_distinguishes_item_shape_failure(caplog):
    transport = MagicMock()
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers={},
        payload=["not-a-mapping"],
        attempts=(TransportAttempt(1),),
    )

    with caplog.at_level(logging.WARNING):
        response = PyGithubIssuePageProvider(transport).read_issue_page(
            "owner/repo", page=1, per_page=100, state="open"
        )

    assert response.complete is False
    assert response.error_kind == "malformed-response"
    assert "github issue-page provider diagnostic=item-shape" in caplog.text


def test_provider_read_page_distinguishes_revision_failure(caplog):
    transport = MagicMock()
    payload = _issue_payload()
    payload.pop("updated_at")
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers={},
        payload=[payload],
        attempts=(TransportAttempt(1),),
    )

    with caplog.at_level(logging.WARNING):
        response = PyGithubIssuePageProvider(transport).read_issue_page(
            "owner/repo", page=1, per_page=100, state="open"
        )

    assert response.complete is False
    assert response.error_kind == "malformed-response"
    assert "github issue-page provider diagnostic=revision-normalization" in caplog.text


def test_provider_read_page_distinguishes_pagination_failure(caplog):
    transport = MagicMock()
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers={
            "link": '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=100>; rel="next"'
        },
        payload=[_issue_payload()],
        attempts=(TransportAttempt(1),),
    )

    with caplog.at_level(logging.WARNING):
        response = PyGithubIssuePageProvider(transport).read_issue_page(
            "owner/repo", page=1, per_page=100, state="open"
        )

    assert response.complete is False
    assert response.error_kind == "malformed-response"
    assert "github issue-page provider diagnostic=pagination-validation" in caplog.text
