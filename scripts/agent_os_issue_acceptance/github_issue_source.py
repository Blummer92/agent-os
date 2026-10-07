"""Connector-backed read-only GitHub issue paging."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .issue_scanner import (
    IssueScanPage,
    IssueStateFilter,
    scan_issues,
)

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ERROR_KINDS = frozenset({
    "rate-limited",
    "permission-denied",
    "malformed-response",
    "source-inaccessible",
    "api-error",
})


@dataclass(frozen=True, slots=True)
class GitHubIssuePageResponse:
    items: tuple[Mapping[str, object], ...]
    next_page: int | None
    complete: bool = True
    terminal_page_proven: bool = False
    error_kind: str | None = None
    # Phase 1 B5: per-page scan provenance. Every field is a transport
    # observation made by the reader that served the page; provenance never
    # manufactures state. All fields are additive with None defaults so every
    # existing constructor keeps working.
    page: int | None = None
    source_query_string: str | None = None
    link_next_url: str | None = None
    rate_limit_remaining: str | None = None

    def __post_init__(self) -> None:
        items = tuple(self.items)
        if not all(isinstance(item, Mapping) for item in items):
            raise TypeError("items must contain mappings")
        if self.next_page is not None and (
            not isinstance(self.next_page, int)
            or isinstance(self.next_page, bool)
            or self.next_page < 1
        ):
            raise ValueError("next_page must be a positive integer or None")
        if self.error_kind is not None and self.error_kind not in _ERROR_KINDS:
            raise ValueError("error_kind is unsupported")
        if self.page is not None and (
            not isinstance(self.page, int)
            or isinstance(self.page, bool)
            or self.page < 1
        ):
            raise ValueError("page must be a positive integer or None")
        if self.source_query_string is not None and (
            not isinstance(self.source_query_string, str)
            or not self.source_query_string.strip()
        ):
            raise ValueError("source_query_string must be non-empty text or None")
        if self.link_next_url is not None and (
            not isinstance(self.link_next_url, str) or not self.link_next_url
        ):
            raise ValueError("link_next_url must be non-empty text or None")
        if self.rate_limit_remaining is not None and not isinstance(
            self.rate_limit_remaining, str
        ):
            raise TypeError("rate_limit_remaining must be text or None")
        object.__setattr__(self, "items", items)


class GitHubIssuePageReader(Protocol):
    def read_issue_page(
        self,
        repository: str,
        *,
        page: int,
        per_page: int,
        state: str,
    ) -> GitHubIssuePageResponse:
        """Return one normalized issue page."""


class GitHubIssuePageSource:
    def __init__(
        self,
        repository: str,
        reader: GitHubIssuePageReader,
        *,
        state: IssueStateFilter,
        per_page: int = 100,
    ) -> None:
        if not isinstance(repository, str) or not _REPOSITORY_RE.fullmatch(repository):
            raise ValueError("repository must use owner/name form")
        if not isinstance(state, IssueStateFilter):
            raise TypeError("state must be an IssueStateFilter")
        if not isinstance(per_page, int) or isinstance(per_page, bool) or not 1 <= per_page <= 100:
            raise ValueError("per_page must be an integer from 1 to 100")
        if reader is None:
            raise TypeError("reader is required")
        self.repository = repository
        self.reader = reader
        self.state = state
        self.per_page = per_page

    def fetch_page(self, page: int) -> IssueScanPage:
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ValueError("page must be a positive integer")
        try:
            response = self.reader.read_issue_page(
                self.repository,
                page=page,
                per_page=self.per_page,
                state=self.state.value,
            )
        except (TypeError, ValueError):
            return IssueScanPage(items=(), next_page=None, error="malformed-response")
        except PermissionError:
            return IssueScanPage(items=(), next_page=None, error="permission-denied")
        except LookupError:
            return IssueScanPage(items=(), next_page=None, error="source-inaccessible")
        except RuntimeError:
            return IssueScanPage(items=(), next_page=None, error="api-error")

        if not isinstance(response, GitHubIssuePageResponse):
            return IssueScanPage(items=(), next_page=None, error="malformed-response")
        if response.error_kind is not None:
            return IssueScanPage(items=(), next_page=None, error=response.error_kind)
        if response.next_page is not None and response.next_page <= page:
            return IssueScanPage(items=(), next_page=None, complete=False)

        issues = tuple(item for item in response.items if "pull_request" not in item)
        return IssueScanPage(
            items=issues,
            next_page=response.next_page,
            complete=response.complete and (response.next_page is not None or response.terminal_page_proven),
        )


def scan_connected_issues(
    repository: str,
    reader: GitHubIssuePageReader,
    *,
    state: IssueStateFilter,
    retrieved_at: str,
    per_page: int = 100,
):
    """Run one state-aware scan over an explicitly supplied connected reader."""
    source = GitHubIssuePageSource(repository, reader, state=state, per_page=per_page)
    return scan_issues(
        source,
        requested_state=state,
        retrieved_at=retrieved_at,
        source_query=f"repo={repository} state={state.value}",
    )


def result_to_report(result: object) -> dict[str, Any]:
    """Project scanner evidence into a stable report-only payload for #346."""
    required = (
        "status",
        "complete",
        "page_count",
        "item_count",
        "requested_state",
        "retrieved_at",
        "source_query",
        "findings",
        "reasons",
        "records",
    )
    if not all(hasattr(result, name) for name in required):
        raise TypeError("result must be an IssueScanResult")
    return {
        "status": result.status.value,
        "complete": result.complete,
        "page_count": result.page_count,
        "item_count": result.item_count,
        "requested_state": result.requested_state.value,
        "retrieved_at": result.retrieved_at,
        "source_query": result.source_query,
        "findings": [finding.value for finding in result.findings],
        "reasons": list(result.reasons),
        "issues": [
            {
                "issue_number": record.issue_number,
                "title": record.title,
                "state": record.state,
                "labels": list(record.labels),
                "url": record.url,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "source_revision": record.source_revision,
                "closed_at": record.closed_at,
                "state_reason": record.state_reason,
            }
            for record in result.records
        ],
    }
