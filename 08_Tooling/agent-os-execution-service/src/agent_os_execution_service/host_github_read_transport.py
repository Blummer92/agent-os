"""One read-only GitHub host transport for the governed-resume bootstrap (#1319).

The transport keeps #1319's single-issue and authorization-source contracts
while reusing the repository's canonical PyGithub client-construction boundary.
It creates no authority and exposes no write method.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from scripts.agent_os_candidate_packet_live_input import (
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)
from scripts.agent_os_github_issue_provider.auth import build_token_client

from .execution_authorization_source import (
    ExecutionAuthorizationCommentSnapshot,
    ExecutionAuthorizationSourceSnapshot,
)

JsonReader = Callable[[str, Mapping[str, object] | None], object]
COMMENTS_PAGE_SIZE = 100
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
    """Read-only transport satisfying both #1319 host transport protocols."""

    read_json: JsonReader
    max_comment_pages: int = MAX_COMMENT_PAGES

    def __post_init__(self) -> None:
        if not callable(self.read_json):
            raise TypeError("read_json must be callable")
        if type(self.max_comment_pages) is not int or not 1 <= self.max_comment_pages <= 64:
            raise ValueError("max_comment_pages must be an exact int from 1 to 64")

    def get_issue(self, repository: str, issue_number: int) -> SingleIssueTransportResult:
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

    def read_authorization_source(
        self, repository: str, issue_number: int
    ) -> ExecutionAuthorizationSourceSnapshot:
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
    """Adapt the canonical PyGithub requester to one read-only JSON callable."""
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
    """Build #1319's read adapter over the canonical token client boundary."""
    import os

    source = os.environ if environ is None else environ
    try:
        client = build_token_client(
            source,
            user_agent="agent-os-governed-resume-host/1",
        )
    except RuntimeError as exc:
        raise HostGitHubTransportUnavailable(
            "GITHUB_TOKEN or GH_TOKEN must be set for the host GitHub read "
            "transport; governed resume refuses to invent a credential source"
        ) from exc
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
