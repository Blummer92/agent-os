"""One read-only GitHub host transport for the governed-resume bootstrap (#1319).

Current ``main`` has a canonical GitHub *access* boundary -- a PyGithub
``Github`` client wrapped by a small read-only transport dataclass
(``scripts.agent_os_github_issue_provider.transport.PyGithubRestTransport``,
``scripts.agent_os_github_git_objects.transport.PyGithubGitObjectTransport``) --
but neither existing transport exposes a *single-issue* read or an
*issue-comments* read, so neither can be handed to ``LiveIssueReader``'s
``SingleIssueTransport`` or to ``ExecutionAuthorizationSourceTransport`` as-is.
This module is therefore the smallest reusable adapter over that same boundary,
not a second client: both protocols are satisfied by **one** object over **one**
injected JSON read callable, exactly as #1319 requires when a single canonical
transport can serve both contracts.

What this module is deliberately not:

- not a GitHub client framework -- there is one dataclass and one adapter
  function, no registry, no builder DSL, no retry/backoff policy of its own
  (the existing PyGithub client owns transport-level retry);
- not an authorization model -- ``read_authorization_source`` only reports what
  GitHub returned; ``reacquire_execution_authorization(...)`` stays the sole
  owner of trust, currentness, binding, and revocation semantics;
- not an issue-semantics owner -- ``get_issue`` returns the raw payload in the
  existing ``SingleIssueTransportResult`` vocabulary and ``LiveIssueReader``
  stays the sole owner of normalization and fail-closed status mapping;
- not a write surface -- there is no write method, and every request is a
  ``GET``.

Credentials never reach this module's state or its diagnostics. The token is
read once, inside :func:`build_host_github_read_transport_from_environment`,
from the ``GITHUB_TOKEN``/``GH_TOKEN`` convention this repository already uses
(``scripts/agent_os_github_git_objects/cli.py``); it is handed straight to the
existing PyGithub auth boundary and is never stored on, logged by, or echoed
from any object defined here. No new credential, IAM, GitHub App, or network
control plane is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from scripts.agent_os_candidate_packet_live_input import (
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)

from .execution_authorization_source import (
    ExecutionAuthorizationCommentSnapshot,
    ExecutionAuthorizationSourceSnapshot,
)

#: One authorized read of one GitHub REST path. ``parameters`` is the query
#: string only; the callable performs the credentialed ``GET`` and returns the
#: decoded JSON payload, or raises :class:`HostGitHubReadError`.
JsonReader = Callable[[str, Mapping[str, object] | None], object]

#: GitHub's maximum page size for the issue-comments endpoint.
COMMENTS_PAGE_SIZE = 100
#: Enough pages to cover ``ExecutionAuthorizationSourceSnapshot``'s own
#: ``MAX_COMMENTS`` bound; beyond it the snapshot is reported incomplete rather
#: than silently truncated.
MAX_COMMENT_PAGES = 6


class HostGitHubReadError(RuntimeError):
    """A read failed with a truthful outcome. Carries no credential material."""

    def __init__(self, outcome: SingleIssueTransportOutcome) -> None:
        if type(outcome) is not SingleIssueTransportOutcome:
            raise TypeError("outcome must be an exact SingleIssueTransportOutcome")
        super().__init__(outcome.value)
        self.outcome = outcome


class HostGitHubTransportUnavailable(RuntimeError):
    """Raised when no host GitHub read transport can be constructed."""


@dataclass(frozen=True, slots=True, kw_only=True)
class HostGitHubReadTransport:
    """Read-only transport satisfying both #1319 host transport protocols.

    ``get_issue`` satisfies ``SingleIssueTransport`` (consumed by the existing
    ``LiveIssueReader``) and ``read_authorization_source`` satisfies
    ``ExecutionAuthorizationSourceTransport`` (consumed by the existing
    ``reacquire_execution_authorization``). They share one ``read_json``
    callable and nothing else -- no shared cache, no shared mutable state, no
    shared interpretation of what either payload means.
    """

    read_json: JsonReader
    max_comment_pages: int = MAX_COMMENT_PAGES

    def __post_init__(self) -> None:
        if not callable(self.read_json):
            raise TypeError("read_json must be callable")
        if type(self.max_comment_pages) is not int or not 1 <= self.max_comment_pages <= 64:
            raise ValueError("max_comment_pages must be an exact int from 1 to 64")

    # -- SingleIssueTransport -------------------------------------------------

    def get_issue(self, repository: str, issue_number: int) -> SingleIssueTransportResult:
        """Perform exactly one authorized read of one issue.

        An error is never converted to ``OK`` and no field is invented:
        ``LiveIssueReader`` owns every normalization decision downstream.
        """
        repository = _repository(repository)
        issue_number = _issue_number(issue_number)
        try:
            payload = self.read_json(f"/repos/{repository}/issues/{issue_number}", None)
        except HostGitHubReadError as exc:
            return SingleIssueTransportResult(outcome=exc.outcome)
        except (OSError, RuntimeError, ValueError, TypeError):
            return SingleIssueTransportResult(
                outcome=SingleIssueTransportOutcome.SOURCE_INACCESSIBLE
            )
        if not isinstance(payload, Mapping):
            return SingleIssueTransportResult(
                outcome=SingleIssueTransportOutcome.MALFORMED_RESPONSE
            )
        return SingleIssueTransportResult(
            outcome=SingleIssueTransportOutcome.OK, item=dict(payload)
        )

    # -- ExecutionAuthorizationSourceTransport --------------------------------

    def read_authorization_source(
        self, repository: str, issue_number: int
    ) -> ExecutionAuthorizationSourceSnapshot:
        """Read the repository owner and the issue's complete comment list.

        Nothing here decides whether any comment authorizes anything. A read
        that cannot be completed truthfully raises, and
        ``reacquire_execution_authorization(...)`` already maps that to
        ``source-unavailable`` / ``needs-decision`` -- fail closed, never a
        partial snapshot presented as complete.
        """
        repository = _repository(repository)
        issue_number = _issue_number(issue_number)
        owner = _mapping(
            _mapping(self.read_json(f"/repos/{repository}", None), "repository payload").get(
                "owner"
            ),
            "repository owner",
        )
        comments: list[ExecutionAuthorizationCommentSnapshot] = []
        complete = False
        for page in range(1, self.max_comment_pages + 1):
            payload = self.read_json(
                f"/repos/{repository}/issues/{issue_number}/comments",
                {"per_page": COMMENTS_PAGE_SIZE, "page": page},
            )
            if type(payload) is not list:
                raise ValueError("issue comments payload is malformed")
            for item in payload:
                entry = _mapping(item, "issue comment")
                comments.append(
                    ExecutionAuthorizationCommentSnapshot(
                        comment_id=entry.get("id"),
                        author_login=_mapping(entry.get("user"), "comment author").get(
                            "login"
                        ),
                        created_at=entry.get("created_at"),
                        body=entry.get("body"),
                    )
                )
            if len(payload) < COMMENTS_PAGE_SIZE:
                complete = True
                break
        return ExecutionAuthorizationSourceSnapshot(
            repository=repository,
            issue_number=issue_number,
            owner_login=owner.get("login"),
            owner_type=owner.get("type"),
            comments_complete=complete,
            comments=tuple(comments),
        )


def build_pygithub_json_reader(client: object) -> JsonReader:
    """Adapt the existing canonical PyGithub access boundary to one read callable.

    ``client`` is the same ``github.Github`` object
    ``scripts.agent_os_github_issue_provider`` and
    ``scripts.agent_os_github_git_objects`` already use; this function reuses
    its authorized requester rather than opening a second client. ``github`` is
    imported locally so importing this module never requires the dependency --
    the same technique ``scripts/agent_os_github_git_objects/cli.py`` uses.
    """
    from github.GithubException import GithubException, RateLimitExceededException

    requester = getattr(client, "requester", None)
    if requester is None or not hasattr(requester, "requestJsonAndCheck"):
        raise HostGitHubTransportUnavailable(
            "client does not expose the canonical PyGithub requester boundary"
        )

    def read_json(path: str, parameters: Mapping[str, object] | None) -> object:
        try:
            _headers, payload = requester.requestJsonAndCheck(
                "GET",
                path,
                parameters=None if parameters is None else dict(parameters),
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                },
            )
        except RateLimitExceededException as exc:
            raise HostGitHubReadError(SingleIssueTransportOutcome.API_ERROR) from exc
        except GithubException as exc:
            raise HostGitHubReadError(_outcome_for_status(exc.status)) from exc
        return payload

    return read_json


def build_host_github_read_transport_from_environment(
    environ: Mapping[str, str] | None = None,
) -> HostGitHubReadTransport:
    """Build the host transport from the existing token convention.

    Reuses ``GITHUB_TOKEN``/``GH_TOKEN`` -- the convention already established
    by ``scripts/agent_os_github_git_objects/cli.py`` -- and the existing
    PyGithub auth boundary. No new credential, IAM, GitHub App, or network
    control plane is introduced, and the token value is never stored on the
    returned object or included in any diagnostic.
    """
    import os

    source = os.environ if environ is None else environ
    token = source.get("GITHUB_TOKEN") or source.get("GH_TOKEN")
    if not token or not token.strip():
        raise HostGitHubTransportUnavailable(
            "GITHUB_TOKEN or GH_TOKEN must be set for the host GitHub read "
            "transport; governed resume refuses to invent a credential source"
        )
    from github import Auth, Github

    client = Github(
        auth=Auth.Token(token),
        retry=None,
        lazy=False,
        user_agent="agent-os-governed-resume-host/1",
    )
    return HostGitHubReadTransport(read_json=build_pygithub_json_reader(client))


def _outcome_for_status(status: object) -> SingleIssueTransportOutcome:
    if status == 404:
        return SingleIssueTransportOutcome.NOT_FOUND
    if status in (401, 403):
        return SingleIssueTransportOutcome.PERMISSION_DENIED
    if status == 451:
        return SingleIssueTransportOutcome.SOURCE_INACCESSIBLE
    return SingleIssueTransportOutcome.API_ERROR


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} is malformed")
    return value


def _repository(value: object) -> str:
    if type(value) is not str or value.count("/") != 1 or not value.strip():
        raise ValueError("repository must be canonical owner/name text")
    owner, _, name = value.partition("/")
    if not owner or not name or any(character in value for character in "?#% \t\n"):
        raise ValueError("repository must be canonical owner/name text")
    return value


def _issue_number(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("issue_number must be a positive exact integer")
    return value
