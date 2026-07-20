from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.github_issue_source import (
    GitHubIssuePageResponse,
    GitHubIssuePageSource,
    result_to_report,
    scan_connected_open_issues,
)
from scripts.agent_os_issue_acceptance.issue_scanner import (
    RetrievalFinding,
    RetrievalStatus,
    scan_open_issues,
)


class FakeReader:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def read_issue_page(self, repository, *, page, per_page, state):
        self.calls.append((repository, page, per_page, state))
        value = self.pages[page]
        if isinstance(value, BaseException):
            raise value
        return value


def _issue(number: int):
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": "open",
        "body": f"Body {number}",
        "html_url": f"https://github.com/Blummer92/agent-os/issues/{number}",
        "created_at": "2026-07-20T00:00:00Z",
        "updated_at": f"2026-07-20T00:00:{number:02d}Z",
        "labels": [{"name": "status:ready"}],
    }


def test_connected_source_exhausts_pages_and_preserves_provenance():
    reader = FakeReader(
        {
            1: GitHubIssuePageResponse((_issue(2),), 2),
            2: GitHubIssuePageResponse((_issue(1),), None),
        }
    )
    source = GitHubIssuePageSource("Blummer92/agent-os", reader)

    result = scan_open_issues(source, source_query="state=open")

    assert result.status == RetrievalStatus.COMPLETE
    assert result.complete is True
    assert result.page_count == 2
    assert [record.issue_number for record in result.records] == [1, 2]
    assert result.records[0].source_revision == result.records[0].updated_at
    assert reader.calls == [
        ("Blummer92/agent-os", 1, 100, "open"),
        ("Blummer92/agent-os", 2, 100, "open"),
    ]


def test_report_handoff_preserves_exact_scan_counts_and_sources():
    reader = FakeReader({1: GitHubIssuePageResponse((_issue(3),), None)})

    result = scan_connected_open_issues("Blummer92/agent-os", reader, per_page=50)
    report = result_to_report(result)

    assert report["status"] == "complete"
    assert report["complete"] is True
    assert report["page_count"] == 1
    assert report["item_count"] == 1
    assert report["source_query"] == "repo=Blummer92/agent-os state=open"
    assert report["issues"] == [
        {
            "issue_number": 3,
            "title": "Issue 3",
            "state": "open",
            "labels": ["status:ready"],
            "url": "https://github.com/Blummer92/agent-os/issues/3",
            "created_at": "2026-07-20T00:00:00Z",
            "updated_at": "2026-07-20T00:00:03Z",
            "source_revision": "2026-07-20T00:00:03Z",
        }
    ]
    assert reader.calls == [("Blummer92/agent-os", 1, 50, "open")]


def test_source_excludes_pull_request_records_from_issue_endpoint():
    pull_request = dict(_issue(9), pull_request={"url": "example"})
    reader = FakeReader(
        {1: GitHubIssuePageResponse((_issue(1), pull_request), None)}
    )

    result = scan_open_issues(GitHubIssuePageSource("Blummer92/agent-os", reader))

    assert result.status == RetrievalStatus.COMPLETE
    assert [record.issue_number for record in result.records] == [1]


def test_incomplete_page_fails_closed_without_false_totals():
    reader = FakeReader(
        {1: GitHubIssuePageResponse((_issue(1),), 2, complete=False)}
    )

    result = scan_open_issues(GitHubIssuePageSource("Blummer92/agent-os", reader))

    assert result.status == RetrievalStatus.INCOMPLETE
    assert result.item_count == 0
    assert RetrievalFinding.PAGE_MISSING_NEXT in result.findings
    assert "pagination completeness is unknown" in result.reasons[0]


def test_nonadvancing_page_fails_closed():
    reader = FakeReader({1: GitHubIssuePageResponse((_issue(1),), 1)})

    result = scan_open_issues(GitHubIssuePageSource("Blummer92/agent-os", reader))

    assert result.status == RetrievalStatus.INCOMPLETE
    assert RetrievalFinding.PAGE_MISSING_NEXT in result.findings


@pytest.mark.parametrize(
    "error_kind",
    [
        "rate-limited",
        "permission-denied",
        "malformed-response",
        "source-inaccessible",
        "api-error",
    ],
)
def test_bounded_error_classes_remain_visible(error_kind):
    reader = FakeReader(
        {1: GitHubIssuePageResponse((), None, error_kind=error_kind)}
    )

    result = scan_open_issues(GitHubIssuePageSource("Blummer92/agent-os", reader))

    assert result.status == RetrievalStatus.INCOMPLETE
    assert result.reasons == (f"page 1: {error_kind}",)
    assert result.item_count == 0


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (PermissionError(), "permission-denied"),
        (LookupError(), "source-inaccessible"),
        (RuntimeError(), "api-error"),
        (ValueError(), "malformed-response"),
    ],
)
def test_reader_exceptions_are_bounded(error, reason):
    reader = FakeReader({1: error})

    result = scan_open_issues(GitHubIssuePageSource("Blummer92/agent-os", reader))

    assert result.status == RetrievalStatus.INCOMPLETE
    assert result.reasons == (f"page 1: {reason}",)


def test_invalid_source_configuration_is_rejected():
    reader = FakeReader({})
    with pytest.raises(ValueError):
        GitHubIssuePageSource("not-a-repository", reader)
    with pytest.raises(ValueError):
        GitHubIssuePageSource("Blummer92/agent-os", reader, per_page=101)
    with pytest.raises(TypeError):
        result_to_report(object())


def test_response_is_immutable():
    response = GitHubIssuePageResponse((), None)
    with pytest.raises(FrozenInstanceError):
        response.complete = False


def test_adapter_defines_no_write_surface():
    module_path = Path(
        "scripts/agent_os_issue_acceptance/github_issue_source.py"
    )
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    method_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert method_names.isdisjoint(
        {"create", "update", "delete", "post", "patch", "put", "mutate"}
    )
    assert "Authorization" not in source
