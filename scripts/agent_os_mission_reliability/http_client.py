"""Bounded JSON GETs to GitHub; no record acquisition, CLI, or environment reads."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from http.client import HTTPException

from .errors import ReadError, ValidationError

_API = "https://api.github.com"
_MAX_RESPONSE = 8 * 1024 * 1024
_MAX_ERROR = 8192
_TIMEOUT = 30


@dataclass(frozen=True)
class JsonPage:
    """An HTTP JSON value plus pagination metadata."""
    value: object
    has_next: bool


def normalize_token(token):
    """Validate and detach an optional token before any network operation."""
    if token is None:
        return None
    clean = token.strip(" \t") if type(token) is str else ""
    if not clean or len(clean) > 512 or not re.fullmatch(r"[!-~]+", clean):
        raise ValidationError("invalid_token", "GitHub token must be nonblank ASCII without whitespace.", "GITHUB_TOKEN")
    return clean

def _on_api(url):
    """Check exact HTTPS authority; credentials are not allowed in a URL."""
    try:
        parsed = urllib.parse.urlsplit(url)
        return parsed.scheme == "https" and parsed.hostname == "api.github.com" and (
            parsed.port in (None, 443)
        ) and parsed.username is None and parsed.password is None
    except ValueError:
        return False


class _GitHubRedirect(urllib.request.HTTPRedirectHandler):
    """Follow only same-origin redirects; never send a token to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        token = req.get_header("Authorization", "").removeprefix("Bearer ")
        if req.get_method() != "GET" or not _on_api(newurl) or (token and token in urllib.parse.unquote(newurl)):
            raise ReadError("redirect_refused", "GitHub redirect left the read-only API origin.", "github")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def _query(params):
    """Encode repeated values and canonical lowercase booleans for a GET query."""
    def scalar(value):
        return str(value).lower() if type(value) is bool else value
    return urllib.parse.urlencode(
        {k: [scalar(x) for x in v] if isinstance(v, (list, tuple)) else scalar(v)
         for k, v in (params or {}).items() if v is not None},
        doseq=True,
    )

def _rate_headers(headers, token):
    """Retain numeric limits and validated HTTP-date Retry-After without echoing arbitrary headers."""
    values = {}
    for header, key in (("X-RateLimit-Reset", "rate_limit_reset"), ("Retry-After", "retry_after")):
        value = headers.get(header, "") if headers else ""
        if type(value) is not str or len(value) > 80 or (token and token in value):
            continue
        if re.fullmatch(r"[0-9]{1,12}", value):
            values[key] = value
        elif key == "retry_after" and re.fullmatch(r"[A-Za-z0-9 ,:+-]+", value):
            try:
                parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                continue
            values[key] = value
    return values

def _safe_snippet(data, token):
    """Bound and sanitize a response excerpt, never including known token variants."""
    value = data.decode("utf-8", "replace")
    if token:
        variants = {token, urllib.parse.quote(token, safe=""), json.dumps(token)[1:-1]}
        for secret in sorted(variants, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
            if len(data) >= _MAX_ERROR:
                tail = next((n for n in range(len(secret) - 1, 0, -1) if value.endswith(secret[:n])), 0)
                if tail:
                    value = value[:-tail] + "[REDACTED]"
    return "".join(c if c.isprintable() else " " for c in value)[:240]

def _http_failure(error, token):
    """Retain sanitized provider status and retry evidence, not exception URLs."""
    try:
        data = error.read(_MAX_ERROR)
    except (OSError, ValueError, HTTPException):
        data = b""
    finally:
        error.close()
    return ReadError("http_error", "GitHub GET returned an error.", "github",
                     status=error.code, body_snippet=_safe_snippet(data, token),
                     **_rate_headers(error.headers, token))

def _parse_response(response):
    """Read and verify one nonempty JSON response, returning its next-page relation."""
    headers = response.headers
    content = headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content != "application/json" and not (content.startswith("application/") and content.endswith("+json")):
        raise ReadError("invalid_content_type", "Expected a GitHub JSON response.", "github")
    data = response.read(_MAX_RESPONSE + 1)
    if not data or len(data) > _MAX_RESPONSE:
        raise ReadError("invalid_body_size", "GitHub returned empty or oversized JSON.", "github")
    try:
        body = json.loads(data, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        raise ReadError("invalid_json", "GitHub returned malformed JSON.", "github") from None
    link = (", ".join(headers.get_all("Link", [])) if hasattr(headers, "get_all") else headers.get("Link", "")).strip()
    entry = r'<[^<>]+>\s*;\s*rel="(first|prev|next|last)"\s*'
    pieces = re.findall(entry, link)
    if link and (not re.fullmatch(rf"{entry}(?:,\s*{entry})*", link) or len(set(pieces)) != len(pieces)):
        raise ReadError("invalid_pagination", "GitHub returned unexpected pagination metadata.", "github")
    return JsonPage(body, "next" in pieces)

def _unique_object(pairs):
    """Reject duplicate keys before any identity or evidence projection."""
    object_value = dict(pairs)
    if len(object_value) != len(pairs):
        raise ValueError("ambiguous JSON object")
    return object_value

def _reject_constant(_):
    """Reject non-JSON numeric constants instead of producing unreportable values."""
    raise ValueError("not a JSON number")

def _reject_token_echo(value, token):
    """Fail before publication if GitHub returned credential bytes as data."""
    if token is None:
        return
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item)
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str) and token in item:
            raise ReadError("credential_echo", "GitHub response echoed request credentials.", "github")

def get_json(path, params=None, *, token=None):
    """Make one GitHub API GET with a timeout; raise structured read or token errors."""
    clean = normalize_token(token)
    if type(path) is not str or not re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues/[0-9]+|pulls(?:/[0-9]+)?)", path) or any(
        part in (".", "..") for part in path.split("/")
    ):
        raise ValidationError("invalid_endpoint", "Unrecognized GitHub read endpoint.", "github")
    query = _query(params)
    if clean and clean in urllib.parse.unquote(f"{path}?{query}"):
        raise ValidationError("invalid_endpoint", "Credentials are not allowed in a URL.", "github")
    request = urllib.request.Request(_API + path + ("?" + query if query else ""), headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "agent-os-mission-reliability",
    }, method="GET")
    if clean:
        request.add_header("Authorization", f"Bearer {clean}")
    try:
        with urllib.request.build_opener(_GitHubRedirect()).open(request, timeout=_TIMEOUT) as response:
            page = _parse_response(response)
            _reject_token_echo(page.value, clean)
            return page
    except urllib.error.HTTPError as error:
        raise _http_failure(error, clean) from None
    except (OSError, HTTPException, ValueError):
        raise ReadError("network_error", "GitHub GET did not complete.", "github") from None
