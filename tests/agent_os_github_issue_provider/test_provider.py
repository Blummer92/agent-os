from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from scripts.agent_os_github_issue_provider.provider import PyGithubIssuePageProvider
from scripts.agent_os_github_issue_provider.models import TransportResponse, TransportAttempt

def test_provider_read_page_success():
    transport = MagicMock()
    headers = {
        "link": '<https://api.github.com/repos/owner/repo/issues?page=2&per_page=100&state=open>; rel="next"'
    }
    payload = [
        {
            "number": 1,
            "title": "One",
            "state": "open",
            "body": "B1",
            "html_url": "https://github.com/o/r/issues/1",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "labels": ["L1"],
        }
    ]
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers=headers,
        payload=payload,
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

def test_provider_read_page_terminal():
    transport = MagicMock()
    headers = {"link": '<https://api.github.com/repos/owner/repo/issues?page=1>; rel="first"'}
    payload = []
    transport.get_issue_page.return_value = TransportResponse(
        status=200,
        headers=headers,
        payload=payload,
        attempts=(TransportAttempt(1),),
    )
    
    provider = PyGithubIssuePageProvider(transport)
    response = provider.read_issue_page("owner/repo", page=2, per_page=100, state="open")
    
    assert response.complete is True
    assert len(response.items) == 0
    assert response.next_page is None
    assert response.terminal_page_proven is True

def test_provider_read_page_transport_error():
    transport = MagicMock()
    from scripts.agent_os_github_issue_provider.transport import GitHubTransportError
    transport.get_issue_page.side_effect = GitHubTransportError("permission-denied", (TransportAttempt(1, "permission-denied"),))
    
    provider = PyGithubIssuePageProvider(transport)
    response = provider.read_issue_page("owner/repo", page=1, per_page=100, state="open")
    
    assert response.complete is False
    assert response.error_kind == "permission-denied"
    assert response.next_page is None
