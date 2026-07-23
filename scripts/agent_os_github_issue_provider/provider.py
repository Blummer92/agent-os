from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging

from scripts.agent_os_issue_acceptance.github_issue_source import (
    GitHubIssuePageResponse,
)

from .pagination import validated_next_page
from .revision import issue_source_revision
from .transport import GitHubRestTransport, GitHubTransportError

_LOGGER = logging.getLogger(__name__)


def _record_diagnostic(kind: str) -> None:
    """Emit one bounded, non-sensitive provider failure identifier."""
    _LOGGER.warning("github issue-page provider diagnostic=%s", kind)


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
            _record_diagnostic(f"transport:{error.kind}")
            return GitHubIssuePageResponse(
                items=(), next_page=None, complete=False, error_kind=error.kind
            )

        if response.status != 200:
            _record_diagnostic("unexpected-status")
            return GitHubIssuePageResponse(
                items=(), next_page=None, complete=False, error_kind="api-error"
            )
        if not isinstance(response.payload, Sequence) or isinstance(
            response.payload, (str, bytes)
        ):
            _record_diagnostic("payload-shape")
            return GitHubIssuePageResponse(
                items=(), next_page=None, complete=False, error_kind="malformed-response"
            )

        normalized_items: list[Mapping[str, object]] = []
        for item in response.payload:
            if not isinstance(item, Mapping):
                _record_diagnostic("item-shape")
                return GitHubIssuePageResponse(
                    items=(), next_page=None, complete=False, error_kind="malformed-response"
                )
            normalized = dict(item)
            try:
                normalized["source_revision"] = issue_source_revision(normalized)
            except (TypeError, ValueError):
                _record_diagnostic("revision-normalization")
                return GitHubIssuePageResponse(
                    items=(), next_page=None, complete=False, error_kind="malformed-response"
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
            _record_diagnostic("pagination-validation")
            return GitHubIssuePageResponse(
                items=(), next_page=None, complete=False, error_kind="malformed-response"
            )

        return GitHubIssuePageResponse(
            items=tuple(normalized_items),
            next_page=next_page,
            complete=True,
            terminal_page_proven=terminal_proven,
        )
