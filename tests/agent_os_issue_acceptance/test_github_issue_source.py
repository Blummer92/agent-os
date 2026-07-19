from scripts.agent_os_issue_acceptance.github_issue_source import (
    GitHubIssuePageSource,
    _parse_next_page,
    result_to_report,
)
from scripts.agent_os_issue_acceptance.issue_scanner import IssueScanPage, scan_open_issues


def test_page_url_uses_open_state_and_page_size():
    source = GitHubIssuePageSource("Blummer92/agent-os", per_page=50)

    assert source._page_url(3) == (
        "https://api.github.com/repos/Blummer92/agent-os/issues?"
        "state=open&per_page=50&page=3"
    )


def test_headers_include_token_only_when_provided():
    without_token = GitHubIssuePageSource("Blummer92/agent-os")._headers()
    with_token = GitHubIssuePageSource("Blummer92/agent-os", token="secret")._headers()

    assert "Authorization" not in without_token
    assert with_token["Authorization"] == "Bearer secret"


def test_parse_next_page_from_link_header():
    header = (
        '<https://api.github.com/repositories/1/issues?page=2>; rel="next", '
        '<https://api.github.com/repositories/1/issues?page=5>; rel="last"'
    )

    assert _parse_next_page(header) == 2


def test_parse_next_page_returns_none_without_next_relation():
    header = '<https://api.github.com/repositories/1/issues?page=5>; rel="last"'

    assert _parse_next_page(header) is None


def test_invalid_page_size_fails_closed():
    page = GitHubIssuePageSource("Blummer92/agent-os", per_page=101).fetch_page(1)

    assert page.complete is False
    assert page.error == "per_page must be between 1 and 100"


def test_invalid_page_number_fails_closed():
    page = GitHubIssuePageSource("Blummer92/agent-os").fetch_page(0)

    assert page.complete is False
    assert page.error == "page must be >= 1"


def test_result_to_report_preserves_counts_and_issue_provenance():
    source = _StaticSource(
        IssueScanPage(
            items=(
                {
                    "number": 1,
                    "title": "Scanner issue",
                    "state": "open",
                    "body": "Body",
                    "html_url": "https://github.com/Blummer92/agent-os/issues/1",
                    "created_at": "2026-07-19T00:00:00Z",
                    "updated_at": "2026-07-19T00:01:00Z",
                    "labels": [{"name": "status:ready"}],
                },
            ),
            next_page=None,
        )
    )

    result = scan_open_issues(source, source_query="repo=Blummer92/agent-os state=open")
    report = result_to_report(result)

    assert report["status"] == "complete"
    assert report["complete"] is True
    assert report["page_count"] == 1
    assert report["item_count"] == 1
    assert report["source_query"] == "repo=Blummer92/agent-os state=open"
    assert report["findings"] == ["scan-complete"]
    assert report["issues"] == [
        {
            "issue_number": 1,
            "title": "Scanner issue",
            "state": "open",
            "labels": ["status:ready"],
            "url": "https://github.com/Blummer92/agent-os/issues/1",
            "created_at": "2026-07-19T00:00:00Z",
            "updated_at": "2026-07-19T00:01:00Z",
            "source_revision": "2026-07-19T00:01:00Z",
        }
    ]


class _StaticSource:
    def __init__(self, page):
        self.page = page

    def fetch_page(self, page: int) -> IssueScanPage:
        assert page == 1
        return self.page
