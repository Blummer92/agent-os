from __future__ import annotations

import pytest
from unittest.mock import MagicMock
import requests.exceptions
from github import GithubException, RateLimitExceededException
from scripts.agent_os_github_issue_provider.transport import (
    PyGithubRestTransport,
    GitHubTransportError,
)

def test_transport_success():
    client = MagicMock()
    client.requester.requestJsonAndCheck.return_value = ({"Status": "200 OK"}, [{"number": 1}])
    transport = PyGithubRestTransport(client)
    response = transport.get_issue_page("owner/repo", page=1, per_page=30, state="open")
    assert response.status == 200
    assert response.payload == [{"number": 1}]
    assert len(response.attempts) == 1
    assert response.attempts[0].number == 1
    assert response.attempts[0].error_kind is None

def test_transport_retry_on_500():
    client = MagicMock()
    # Fail twice with 500, then succeed
    client.requester.requestJsonAndCheck.side_effect = [
        GithubException(500, {"message": "internal error"}, {}),
        GithubException(502, {"message": "bad gateway"}, {}),
        ({"Status": "200 OK"}, [{"number": 1}]),
    ]
    transport = PyGithubRestTransport(client, max_attempts=3)
    response = transport.get_issue_page("owner/repo", page=1, per_page=30, state="open")
    assert response.status == 200
    assert len(response.attempts) == 3
    assert response.attempts[0].error_kind == "api-error"
    assert response.attempts[1].error_kind == "api-error"
    assert response.attempts[2].error_kind is None

def test_transport_no_retry_on_404():
    client = MagicMock()
    client.requester.requestJsonAndCheck.side_effect = GithubException(404, {"message": "not found"}, {})
    transport = PyGithubRestTransport(client, max_attempts=3)
    with pytest.raises(GitHubTransportError) as excinfo:
        transport.get_issue_page("owner/repo", page=1, per_page=30, state="open")
    assert excinfo.value.kind == "source-inaccessible"
    assert len(excinfo.value.attempts) == 1

def test_transport_no_retry_on_401():
    client = MagicMock()
    client.requester.requestJsonAndCheck.side_effect = GithubException(401, {"message": "unauthorized"}, {})
    transport = PyGithubRestTransport(client, max_attempts=3)
    with pytest.raises(GitHubTransportError) as excinfo:
        transport.get_issue_page("owner/repo", page=1, per_page=30, state="open")
    assert excinfo.value.kind == "permission-denied"
    assert len(excinfo.value.attempts) == 1

def test_transport_rate_limit_immediate_failure():
    client = MagicMock()
    client.requester.requestJsonAndCheck.side_effect = RateLimitExceededException(403, {"message": "rate limit"}, {})
    transport = PyGithubRestTransport(client, max_attempts=3)
    with pytest.raises(GitHubTransportError) as excinfo:
        transport.get_issue_page("owner/repo", page=1, per_page=30, state="open")
    assert excinfo.value.kind == "rate-limited"
    assert len(excinfo.value.attempts) == 1

def test_transport_timeout_retry():
    client = MagicMock()
    client.requester.requestJsonAndCheck.side_effect = [TimeoutError("timed out"), ({"Status": "200 OK"}, [])]
    transport = PyGithubRestTransport(client, max_attempts=3)
    response = transport.get_issue_page("owner/repo", page=1, per_page=30, state="open")
    assert response.status == 200
    assert len(response.attempts) == 2
    assert response.attempts[0].error_kind == "api-error"

def test_transport_retry_on_408():
    client = MagicMock()
    client.requester.requestJsonAndCheck.side_effect = [
        GithubException(408, {"message": "request timeout"}, {}),
        ({"Status": "200 OK"}, []),
    ]
    transport = PyGithubRestTransport(client, max_attempts=3)
    response = transport.get_issue_page("owner/repo", page=1, per_page=30, state="open")
    assert response.status == 200
    assert len(response.attempts) == 2
    assert response.attempts[0].error_kind == "api-error"

def test_transport_retry_on_requests_timeout():
    client = MagicMock()
    client.requester.requestJsonAndCheck.side_effect = [
        requests.exceptions.Timeout("requests timeout"),
        ({"Status": "200 OK"}, []),
    ]
    transport = PyGithubRestTransport(client, max_attempts=3)
    response = transport.get_issue_page("owner/repo", page=1, per_page=30, state="open")
    assert response.status == 200
    assert len(response.attempts) == 2
    assert response.attempts[0].error_kind == "api-error"

def test_transport_retry_on_requests_connection_error():
    client = MagicMock()
    client.requester.requestJsonAndCheck.side_effect = [
        requests.exceptions.ConnectionError("requests conn error"),
        ({"Status": "200 OK"}, []),
    ]
    transport = PyGithubRestTransport(client, max_attempts=3)
    response = transport.get_issue_page("owner/repo", page=1, per_page=30, state="open")
    assert response.status == 200
    assert len(response.attempts) == 2
    assert response.attempts[0].error_kind == "api-error"

def test_transport_wrap_unexpected_exception():
    client = MagicMock()
    client.requester.requestJsonAndCheck.side_effect = ValueError("unexpected")
    transport = PyGithubRestTransport(client, max_attempts=3)
    with pytest.raises(GitHubTransportError) as excinfo:
        transport.get_issue_page("owner/repo", page=1, per_page=30, state="open")
    assert excinfo.value.kind == "api-error"
    # Even unexpected exceptions cause immediate failure in this task's design to prevent leak
    assert len(excinfo.value.attempts) == 1
