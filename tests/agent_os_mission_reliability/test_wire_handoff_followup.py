"""Guard GET-only wire handoffs in offline transport fixture tests."""
from email.message import Message

import pytest

from scripts.agent_os_mission_reliability.errors import ReadError, ValidationError
from scripts.agent_os_mission_reliability.http_client import get_json
from .test_http_contract import PATH, TOKEN, Response, _stub


def _link_header(page, relation):
    return f'<https://api.github.com{PATH}?page={page}>; rel="{relation}"'


def test_folded_link_fields_do_not_lose_next_page(monkeypatch):
    response = Response(b"[]")
    response.headers = Message()
    response.headers["Content-Type"] = "application/json"
    response.headers["Link"] = _link_header(1, "prev")
    response.headers["Link"] = _link_header(3, "next")
    _stub(monkeypatch, response)
    assert get_json(PATH).has_next is True


@pytest.mark.parametrize("link", [
    f"unparsed-prefix, {_link_header(2, 'next')}",
    f"{_link_header(2, 'next')}, unparsed-suffix",
])
def test_partial_link_parse_is_not_success(monkeypatch, link):
    _stub(monkeypatch, Response(b"[]", link=link))
    with pytest.raises(ReadError) as out:
        get_json(PATH)
    assert out.value.code == "invalid_pagination"


@pytest.mark.parametrize("path,params", [
    (f"/repos/{TOKEN}/repo/pulls", None),
    (PATH, {"term": TOKEN}),
])
def test_credential_cannot_enter_request_target(monkeypatch, path, params):
    calls = _stub(monkeypatch, Response(b"[]"))
    with pytest.raises(ValidationError) as out:
        get_json(path, params, token=TOKEN)
    assert out.value.code == "invalid_endpoint"
    assert not calls and TOKEN not in str(out.value)


def test_same_origin_location_cannot_echo_credentials_into_target():
    from urllib.request import Request
    from scripts.agent_os_mission_reliability.http_client import _GitHubRedirect

    request = Request(f"https://api.github.com{PATH}",
                      headers={"Authorization": f"Bearer {TOKEN}"}, method="GET")
    with pytest.raises(ReadError) as out:
        _GitHubRedirect().redirect_request(
            request, None, 302, "redirect", {}, f"https://api.github.com{PATH}?echo={TOKEN}",
        )
    assert out.value.code == "redirect_refused" and TOKEN not in str(out.value)
