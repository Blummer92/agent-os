"""Verify only the wire contracts using in-memory urllib doubles, never network."""

import io
import json
import socket
from email.message import Message
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest

from scripts.agent_os_mission_reliability.errors import ReadError, ValidationError
from scripts.agent_os_mission_reliability.http_client import _GitHubRedirect, get_json
from scripts.agent_os_mission_reliability.report import error_payload, render

PATH = "/repos/owner/repo/pulls"
TOKEN = "synthetic-token-01234"


class Response(io.BytesIO):
    def __init__(self, value, content_type="application/json", link=None):
        super().__init__(value)
        self.headers = {"Content-Type": content_type}
        if link is not None:
            self.headers["Link"] = link


def _stub(monkeypatch, result):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            if isinstance(result, Exception):
                raise result
            return result
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    return calls


def test_get_only_boolean_and_list_encoding_user_agent_and_header(monkeypatch):
    response = Response(b"[]")
    calls = _stub(monkeypatch, response)
    page = get_json(PATH, {"flag": True, "items": [False, 2], "skip": None}, token=f" {TOKEN} ")
    request, timeout = calls[0]
    assert page.value == [] and page.has_next is False
    assert len(calls) == 1 and timeout == 30 and request.get_method() == "GET"
    assert parse_qs(urlsplit(request.full_url).query) == {"flag": ["true"], "items": ["false", "2"]}
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert request.get_header("User-agent") == "agent-os-mission-reliability"
    assert TOKEN not in request.full_url


def test_redirects_never_forward_authorization_to_other_origins():
    handler = _GitHubRedirect()
    request = Request(f"https://api.github.com{PATH}", headers={"Authorization": f"Bearer {TOKEN}"}, method="GET")
    for location in ("https://example.invalid/path", "http://api.github.com/read", "https://api.github.com:444/read"):
        with pytest.raises(ReadError) as out:
            handler.redirect_request(request, None, 302, "redirect", {}, location)
        assert out.value.code == "redirect_refused"
    redirect = handler.redirect_request(request, None, 302, "redirect", {}, f"https://api.github.com{PATH}?page=2")
    assert redirect.get_method() == "GET" and redirect.get_header("Authorization") == f"Bearer {TOKEN}"


@pytest.mark.parametrize("token", [None," bad token ", "token\n", "token\r", "token\tX", "\t", "é"])
def test_invalid_tokens_do_not_enter_transport_and_none_is_anonymous(token, monkeypatch):
    calls = _stub(monkeypatch, Response(b"[]"))
    if token is None:
        get_json(PATH, token=token)
        assert calls[0][0].get_header("Authorization") is None
    else:
        with pytest.raises(ValidationError) as out:
            get_json(PATH, token=token)
        assert not calls and out.value.code == "invalid_token"


def test_http_error_body_and_rate_metadata_redacts_token(monkeypatch):
    headers = Message()
    headers["X-RateLimit-Reset"] = "1777777777"
    headers["Retry-After"] = "75"
    error = HTTPError(f"https://api.github.com/{TOKEN}", 429, TOKEN, headers,
                      io.BytesIO(f'{{"message":"limit {TOKEN}"}}'.encode()))
    _stub(monkeypatch, error)
    with pytest.raises(ReadError) as out:
        get_json(PATH, token=TOKEN)
    result = error_payload(out.value)["error"]
    assert result["status"] == 429 and result["rate_limit_reset"] == "1777777777" and result["retry_after"] == "75"
    assert "limit" in result["body_snippet"] and TOKEN not in render(result)


@pytest.mark.parametrize("error", [URLError(TOKEN), socket.timeout(TOKEN), IncompleteRead(b"", 2)])
def test_transport_failures_are_structured_without_exception_echo(error, monkeypatch):
    _stub(monkeypatch, error)
    with pytest.raises(ReadError) as out:
        get_json(PATH, token=TOKEN)
    assert out.value.code == "network_error"
    assert TOKEN not in render(error_payload(out.value))


@pytest.mark.parametrize("source,expected", [
    (lambda: Response(b"", "application/json"), "invalid_body_size"),
    (lambda: Response(b"<html>", "text/html"), "invalid_content_type"),
    (lambda: Response(b"{broken"), "invalid_json"),
    (lambda: Response(b'{"value": NaN}'), "invalid_json"),
    (lambda: Response(b"{}", link="nonsense"), "invalid_pagination"),
    (lambda: Response(json.dumps({"nested": [{"ref": TOKEN}]}).encode()), "credential_echo"),
])
def test_invalid_or_credential_echo_response_fails_closed(source, expected, monkeypatch):
    _stub(monkeypatch, source())
    with pytest.raises(ReadError) as out:
        get_json(PATH, token=TOKEN)
    assert out.value.code == expected
    assert TOKEN not in render(error_payload(out.value))


def test_github_link_explicitly_retains_next_page(monkeypatch):
    _stub(monkeypatch, Response(b"[]", link=f'<https://api.github.com{PATH}?page=2>; rel="next"'))
    assert get_json(PATH).has_next is True


def test_duplicate_provider_json_keys_are_ambiguous_not_last_wins(monkeypatch):
    _stub(monkeypatch, Response(b'{"number":2,"number":1}'))
    with pytest.raises(ReadError) as out:
        get_json(PATH)
    assert out.value.code == "invalid_json"


def test_invalid_endpoint_is_structured_and_never_read(monkeypatch):
    calls = _stub(monkeypatch, Response(b"[]"))
    for path in (None, "https://api.github.com/repos/owner/repo/pulls", "/repos/../repo/pulls"):
        with pytest.raises(ValidationError) as out:
            get_json(path)
        assert out.value.code == "invalid_endpoint"
    assert not calls
