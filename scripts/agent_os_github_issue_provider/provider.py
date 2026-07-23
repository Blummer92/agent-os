from __future__ import annotations

from collections.abc import Mapping, Sequence

from scripts.agent_os_issue_acceptance.github_issue_source import (
    GitHubIssuePageResponse,
)

from .pagination import validated_next_page
from .revision import issue_source_revision
from .transport import GitHubRestTransport, GitHubTransportError


class PyGithubIssuePageProvider:
    """Read-only adapter implementing the existing issue-page reader contract."""

    def __init__(self, transport: GitHubRestTransport) -> None:
        if transport is None:
            raise TypeError("transport is required")
        self._transport = transport

    def read_issue_page(
        self,
        repository: str,
        *,
        page: int,
        per_page: int,
        state: str,
    ) -> GitHubIssuePageResponse:
        try:
            response = self._transport.get_issue_page(
                repository,
                page=page,
                per_page=per_page,
                state=state,
            )
        except GitHubTransportError as error:
            return GitHubIssuePageResponse(
                items=(), next_page=None, complete=False, error_kind=error.kind
            )

        if response.status != 200:
            return GitHubIssuePageResponse(
                items=(), next_page=None, complete=False, error_kind="api-error"
            )
        if not isinstance(response.payload, Sequence) or isinstance(
            response.payload, (str, bytes)
        ):
            return GitHubIssuePageResponse(
                items=(), next_page=None, complete=False, error_kind="malformed-payload"
            )

        normalized_items: list[Mapping[str, object]] = []
        for item in response.payload:
            if not isinstance(item, Mapping):
                return GitHubIssuePageResponse(
                    items=(), next_page=None, complete=False, error_kind="malformed-item"
                )
            normalized = dict(item)
            try:
                normalized["source_revision"] = issue_source_revision(normalized)
            except (TypeError, ValueError):
                return GitHubIssuePageResponse(
                    items=(), next_page=None, complete=False, error_kind="malformed-revision"
                )
            normalized_items.append(normalized)

        headers = {key.lower(): value for key, value in response.headers.items()}
        try:
            next_page, terminal_proven = validated_next_page(
                headers.get("link"),
                repository=repository,
                current_page=page,
                per_page=per_page,
                state=state,
            )
        except (TypeError, ValueError):
            return GitHubIssuePageResponse(
                items=(), next_page=None, complete=False, error_kind="malformed-pagination"
            )

        return GitHubIssuePageResponse(
            items=tuple(normalized_items),
            next_page=next_page,
            complete=True,
            terminal_page_proven=terminal_proven,
        )
