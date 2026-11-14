"""Read-only GitHub issue-comment reader for CKR6 R07 consumption (#2425).

The CKR6 result consumer (``ckr6_github_bridge``) takes the GitHub
issue-comment *record*, not a bare body. A record pasted through an MCP tool
argument is caller-supplied text, so it cannot establish provenance: every
check in the bridge (producer login/id, location, timestamps) can be
fabricated by a caller who copies a genuine record. The checks only have
force when the record arrives from an authenticated GitHub read the caller
cannot edit. This module is that read, and nothing else:

* exactly one repository (``Blummer92/agent-os``), read-only issue comments;
* exactly one HTTP method (``GET``), one endpoint family
  (``/repos/{repository}/issues/{issue_number}/comments``);
* the credential is a GitHub App installation token supplied through an
  *injectable* provider (``GitHubAppInstallationTokenProvider``), never as a
  tool argument, never pasted by the host, never read from a comment body;
* no credential is created, stored, logged, or returned by this module;
* no GitHub write is performed or authorized here.

Wiring: the host operator installs a reader at server startup with
``set_github_issue_comment_reader``. Until one is installed, the MCP
wrapper returns ``HOST_READ_PATH_UNAVAILABLE``. Minting, scoping, and
rotating the installation token remain host-operator work; this module only
consumes a token a provider hands it, for one read at a time.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Mapping, Protocol

ALLOWED_REPOSITORY = "Blummer92/agent-os"
GITHUB_API_BASE_URL = "https://api.github.com"
_READ_TIMEOUT_SECONDS = 30
_USER_AGENT = "agent-os-ckr6-reader"
# One page of at most 100 comments; bound the response so a slow or
# oversized reply cannot grow the read without limit; production reads at most
# _MAX_RESPONSE_BYTES + 1 before rejecting it.
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class GitHubIssueCommentReadUnavailable(RuntimeError):
    """The trusted GitHub read path is unavailable for this call.

    Carries a stable ``reason_code`` (``HOST_READ_PATH_UNAVAILABLE`` when no
    reader/token is configured, ``github-api-failure`` on transport or HTTP
    failure, ``github-api-unexpected-response`` on a malformed response).
    The credential itself is never included in the message.
    """

    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)
        self.reason_code = reason_code
        self.detail = detail


class GitHubAppInstallationTokenProvider(Protocol):
    """Supplies a short-lived GitHub App installation token for one read.

    The provider mints (or returns a cached, still-valid) installation token
    scoped to ``Blummer92/agent-os`` with read-only issue permissions. It
    must return ``None`` when no token can be supplied; it must never return
    a token for a different repository or with write scope.
    """

    def get_installation_token(self) -> str | None: ...


# ``http_get(url, headers) -> (status_code, body_bytes)``. Injectable so
# tests never touch the network; production uses ``_urllib_http_get``.
HttpGet = Callable[[str, dict[str, str]], tuple[int, bytes]]


def _urllib_http_get(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    request = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_READ_TIMEOUT_SECONDS) as response:
            return response.status, response.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # HTTPError is raised for non-2xx responses; the status is evidence,
        # the body is not needed and may contain provider detail.
        raise GitHubIssueCommentReadUnavailable(
            "github-api-failure", f"GitHub API returned HTTP {exc.code}"
        ) from exc
    except Exception as exc:  # URLError, timeout, TLS failure: no read happened.
        raise GitHubIssueCommentReadUnavailable(
            "github-api-failure", f"GitHub API read failed: {type(exc).__name__}"
        ) from exc


_READ_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": _USER_AGENT,
    "X-GitHub-Api-Version": "2022-11-28",
}


def _parse_comment_record(status: int, body: bytes) -> dict[str, object]:
    """Validate one exact-ID comment response; fail closed, never leak detail."""
    if status != 200:
        raise GitHubIssueCommentReadUnavailable(
            "github-api-failure", f"GitHub API returned HTTP {status}"
        )
    if len(body) > _MAX_RESPONSE_BYTES:
        raise GitHubIssueCommentReadUnavailable(
            "github-api-unexpected-response",
            "GitHub API response exceeds the bounded size",
        )
    try:
        record = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GitHubIssueCommentReadUnavailable(
            "github-api-unexpected-response", "GitHub API response is not valid JSON"
        ) from exc
    if not isinstance(record, Mapping):
        raise GitHubIssueCommentReadUnavailable(
            "github-api-unexpected-response",
            "GitHub API response is not one comment record",
        )
    return dict(record)


class GitHubIssueCommentReader:
    """Bounded read-only reader for one repository's issue comments."""

    def __init__(
        self,
        *,
        token_provider: GitHubAppInstallationTokenProvider | None = None,
        http_get: HttpGet | None = None,
    ) -> None:
        self._token_provider = token_provider
        self._http_get = http_get or _urllib_http_get

    def read_issue_comments(
        self, repository: str, issue_number: int
    ) -> list[dict[str, object]]:
        """Return the issue's comment records, newest-last, as GitHub returns them.

        Raises ``ValueError`` on malformed caller identity (wrong repository,
        non-positive issue number) and
        ``GitHubIssueCommentReadUnavailable`` when no token is available, the
        transport fails, or the response is not a list of comment records.
        The token is used only in the ``Authorization`` header of this one
        request and is never returned, logged, or embedded in any result.
        """
        if type(repository) is not str or repository != ALLOWED_REPOSITORY:
            raise ValueError(
                "GitHub issue-comment reads are scoped to exactly "
                f"{ALLOWED_REPOSITORY}"
            )
        if type(issue_number) is not int or isinstance(issue_number, bool) or issue_number < 1:
            raise ValueError("issue_number must be a positive integer")
        token = self._read_token()
        url = (
            f"{GITHUB_API_BASE_URL}/repos/{repository}/issues/{issue_number}"
            "/comments?per_page=100"
        )
        status, body = self._http_get(
            url,
            _READ_HEADERS | {"Authorization": "Bearer " + token},
        )
        if status != 200:
            raise GitHubIssueCommentReadUnavailable(
                "github-api-failure", f"GitHub API returned HTTP {status}"
            )
        if len(body) > _MAX_RESPONSE_BYTES:
            raise GitHubIssueCommentReadUnavailable(
                "github-api-unexpected-response",
                "GitHub API response exceeds the bounded size",
            )
        try:
            comments = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubIssueCommentReadUnavailable(
                "github-api-unexpected-response", "GitHub API response is not valid JSON"
            ) from exc
        if type(comments) is not list or any(
            not isinstance(item, Mapping) for item in comments
        ):
            raise GitHubIssueCommentReadUnavailable(
                "github-api-unexpected-response",
                "GitHub API response is not a list of comment records",
            )
        return [dict(item) for item in comments]

    def read_issue_comment(self, repository: str, comment_id: int) -> dict[str, object]:
        """Return ONE issue-comment record fetched by its exact GitHub id.

        Same trust bound as ``read_issue_comments``: the record arrives from
        the authenticated GitHub read, never from caller-supplied text, so
        its server-assigned id, author, location and timestamps are evidence
        a caller cannot fabricate. Used by the CKR7 receipt barrier (#3418):
        a receipt reference is only an identifier until the exact comment it
        names is retrieved through this path.

        Raises ``ValueError`` on malformed caller identity and
        ``GitHubIssueCommentReadUnavailable`` when no token is available, the
        transport fails (including HTTP 404 for a missing/deleted comment),
        or the response is not one comment record.
        """
        if type(repository) is not str or repository != ALLOWED_REPOSITORY:
            raise ValueError(
                "GitHub issue-comment reads are scoped to exactly "
                f"{ALLOWED_REPOSITORY}"
            )
        if type(comment_id) is not int or isinstance(comment_id, bool) or comment_id < 1:
            raise ValueError("comment_id must be a positive integer")
        token = self._read_token()
        status, body = self._http_get(
            f"{GITHUB_API_BASE_URL}/repos/{repository}/issues/comments/{comment_id}",
            _READ_HEADERS | {"Authorization": "Bearer " + token},
        )
        return _parse_comment_record(status, body)

    def _read_token(self) -> str:
        if self._token_provider is None:
            raise GitHubIssueCommentReadUnavailable(
                "HOST_READ_PATH_UNAVAILABLE", "no GitHub App installation-token provider is installed"
            )
        try:
            token = self._token_provider.get_installation_token()
        except Exception:
            # Provider failures are unavailable reads, never MCP exceptions.
            # Do not propagate provider exception text or credential details.
            raise GitHubIssueCommentReadUnavailable(
                "HOST_READ_PATH_UNAVAILABLE",
                "GitHub App installation token is unavailable",
            ) from None
        if type(token) is not str or not token.strip():
            raise GitHubIssueCommentReadUnavailable(
                "HOST_READ_PATH_UNAVAILABLE", "no GitHub App installation token is available"
            )
        return token


_READER: GitHubIssueCommentReader | None = None


def set_github_issue_comment_reader(
    reader: GitHubIssueCommentReader | None,
) -> None:
    """Install (or clear, with ``None``) the server-wide trusted comment reader.

    Called by the host operator at server startup, after minting a GitHub App
    installation token provider. Nothing in this repository calls it with a
    real provider; the default is ``None`` (read path unavailable).
    """
    global _READER
    _READER = reader


def get_github_issue_comment_reader() -> GitHubIssueCommentReader | None:
    """Return the installed trusted comment reader, or ``None`` if none is."""
    return _READER
