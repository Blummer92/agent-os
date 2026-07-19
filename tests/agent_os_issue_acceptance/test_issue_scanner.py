from scripts.agent_os_issue_acceptance.issue_scanner import (
    IssueScanPage,
    RetrievalFinding,
    RetrievalStatus,
    scan_open_issues,
)


class FakePageSource:
    def __init__(self, pages):
        self.pages = pages
        self.requested_pages = []

    def fetch_page(self, page: int) -> IssueScanPage:
        self.requested_pages.append(page)
        return self.pages[page]


def _issue(number: int, *, labels=None):
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": "open",
        "body": f"Body {number}",
        "html_url": f"https://github.com/Blummer92/agent-os/issues/{number}",
        "created_at": "2026-07-19T00:00:00Z",
        "updated_at": f"2026-07-19T00:00:{number:02d}Z",
        "labels": labels or [{"name": "status:ready"}],
    }


def test_scanner_collects_complete_paginated_results_deterministically():
    source = FakePageSource(
        {
            1: IssueScanPage(items=(_issue(2),), next_page=2),
            2: IssueScanPage(items=(_issue(1),), next_page=None),
        }
    )

    result = scan_open_issues(source, source_query="state=open")

    assert result.status == RetrievalStatus.COMPLETE
    assert result.complete is True
    assert result.findings == (RetrievalFinding.COMPLETE,)
    assert result.page_count == 2
    assert result.item_count == 2
    assert [record.issue_number for record in result.records] == [1, 2]
    assert source.requested_pages == [1, 2]


def test_scanner_preserves_issue_provenance_and_labels():
    source = FakePageSource(
        {
            1: IssueScanPage(
                items=(
                    _issue(
                        3,
                        labels=(
                            {"name": "owner:integration-manager"},
                            "status:ready",
                        ),
                    ),
                ),
                next_page=None,
            )
        }
    )

    result = scan_open_issues(source)
    record = result.records[0]

    assert record.issue_number == 3
    assert record.url.endswith("/issues/3")
    assert record.source_revision == record.updated_at
    assert record.labels == ("owner:integration-manager", "status:ready")


def test_scanner_fails_closed_when_pagination_completeness_unknown():
    source = FakePageSource(
        {
            1: IssueScanPage(items=(_issue(1),), next_page=2, complete=False),
        }
    )

    result = scan_open_issues(source)

    assert result.status == RetrievalStatus.INCOMPLETE
    assert result.complete is False
    assert RetrievalFinding.PAGE_MISSING_NEXT in result.findings
    assert "pagination completeness is unknown" in result.reasons[0]
    assert result.item_count == 0


def test_scanner_fails_closed_on_missing_required_field():
    incomplete_issue = dict(_issue(1))
    incomplete_issue.pop("updated_at")
    source = FakePageSource(
        {
            1: IssueScanPage(items=(incomplete_issue,), next_page=None),
        }
    )

    result = scan_open_issues(source)

    assert result.status == RetrievalStatus.INCOMPLETE
    assert RetrievalFinding.MISSING_FIELD in result.findings
    assert "updated_at" in result.reasons[0]


def test_scanner_fails_closed_on_api_error():
    source = FakePageSource(
        {
            1: IssueScanPage(items=(), next_page=None, error="rate limit"),
        }
    )

    result = scan_open_issues(source)

    assert result.status == RetrievalStatus.INCOMPLETE
    assert RetrievalFinding.API_ERROR in result.findings
    assert result.reasons == ("page 1: rate limit",)


def test_scanner_fails_closed_on_duplicate_issue_number():
    source = FakePageSource(
        {
            1: IssueScanPage(items=(_issue(1),), next_page=2),
            2: IssueScanPage(items=(_issue(1),), next_page=None),
        }
    )

    result = scan_open_issues(source)

    assert result.status == RetrievalStatus.INCOMPLETE
    assert RetrievalFinding.DUPLICATE_ISSUE in result.findings
    assert result.reasons == ("duplicate issue number encountered: #1",)
    assert result.item_count == 1


def test_scanner_fails_closed_when_next_page_does_not_advance():
    source = FakePageSource(
        {
            1: IssueScanPage(items=(_issue(1),), next_page=1),
        }
    )

    result = scan_open_issues(source)

    assert result.status == RetrievalStatus.INCOMPLETE
    assert RetrievalFinding.PAGE_MISSING_NEXT in result.findings
    assert "does not advance pagination" in result.reasons[0]
