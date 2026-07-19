from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .issue_scanner import IssueScanPage, scan_open_issues


GITHUB_API_ROOT = "https://api.github.com"


@dataclass(frozen=True)
class GitHubIssuePageSource:
    """Paginated GitHub issue source for report-only scanner execution."""

    repository: str
    token: str | None = None
    per_page: int = 100
    api_root: str = GITHUB_API_ROOT

    def fetch_page(self, page: int) -> IssueScanPage:
        if page < 1:
            return IssueScanPage((), None, complete=False, error="page must be >= 1")
        if not 1 <= self.per_page <= 100:
            return IssueScanPage((), None, complete=False, error="per_page must be between 1 and 100")

        url = self._page_url(page)
        request = Request(url, headers=self._headers())
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, list):
                    return IssueScanPage((), None, complete=False, error="GitHub response was not a list")
                next_page = _parse_next_page(response.headers.get("Link"))
                items = tuple(_normalise_issue_item(item) for item in payload)
                return IssueScanPage(items=items, next_page=next_page, complete=True)
        except HTTPError as exc:
            return IssueScanPage((), None, complete=False, error=f"GitHub API HTTP {exc.code}")
        except URLError as exc:
            return IssueScanPage((), None, complete=False, error=f"GitHub API URL error: {exc.reason}")
        except TimeoutError:
            return IssueScanPage((), None, complete=False, error="GitHub API request timed out")
        except json.JSONDecodeError:
            return IssueScanPage((), None, complete=False, error="GitHub response was not valid JSON")

    def _page_url(self, page: int) -> str:
        query = urlencode(
            {
                "state": "open",
                "per_page": self.per_page,
                "page": page,
            }
        )
        return f"{self.api_root}/repos/{self.repository}/issues?{query}"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agent-os-issue-scanner",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers


def scan_repository_open_issues(repository: str, *, token: str | None = None, per_page: int = 100):
    """Run the report-only scanner against one repository's open issues."""
    source = GitHubIssuePageSource(repository=repository, token=token, per_page=per_page)
    return scan_open_issues(source, source_query=f"repo={repository} state=open")


def scan_repository_from_env():
    """Run scanner from environment for explicit local use.

    Required: GITHUB_REPOSITORY in owner/name form.
    Optional: GITHUB_TOKEN, GITHUB_PER_PAGE.
    """
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        raise ValueError("GITHUB_REPOSITORY is required")
    per_page = int(os.environ.get("GITHUB_PER_PAGE", "100"))
    token = os.environ.get("GITHUB_TOKEN")
    return scan_repository_open_issues(repository, token=token, per_page=per_page)


def result_to_report(result) -> dict[str, Any]:
    """Return stable report-only output for #346."""
    return {
        "status": result.status.value,
        "complete": result.complete,
        "page_count": result.page_count,
        "item_count": result.item_count,
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
            }
            for record in result.records
        ],
    }


def _normalise_issue_item(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        return {}
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "state": item.get("state"),
        "body": item.get("body"),
        "html_url": item.get("html_url"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "labels": item.get("labels", ()),
    }


def _parse_next_page(link_header: str | None) -> int | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section, _, rel = part.partition(";")
        if 'rel="next"' not in rel:
            continue
        url = section.strip().strip("<>")
        _, _, query = url.partition("?")
        for item in query.split("&"):
            key, _, value = item.partition("=")
            if key == "page" and value.isdigit():
                return int(value)
    return None
