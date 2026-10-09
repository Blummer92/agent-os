from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.github_issue_source import (
    GitHubIssuePageResponse,
    GitHubIssuePageSource,
    scan_connected_issues,
)
from scripts.agent_os_issue_acceptance.issue_scanner import (
    IssueStateFilter,
    RetrievalFinding,
    RetrievalStatus,
    scan_issues,
)


RETRIEVED_AT = "2026-07-21T22:00:00Z"


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


def _issue(number: int, *, state="open", **overrides):
    issue = {
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "body": f"Body {number}",
        "html_url": f"https://github.com/Blummer92/agent-os/issues/{number}",
        "created_at": "2026-07-20T00:00:00Z",
        "updated_at": f"2026-07-20T00:00:{number:02d}Z",
        "labels": [{"name": "status:ready"}],
    }
    issue.update(overrides)
    return issue


def test_connected_source_exhausts_pages_and_preserves_state_provenance():
    reader = FakeReader(
        {
            1: GitHubIssuePageResponse((_issue(2, state="closed"),), 2),
            2: GitHubIssuePageResponse((_issue(1, state="closed"),), None, terminal_page_proven=True),
        }
    )
    source = GitHubIssuePageSource(
        "Blummer92/agent-os",
        reader,
        state=IssueStateFilter.CLOSED,
    )

    result = scan_issues(
        source,
        requested_state=IssueStateFilter.CLOSED,
        retrieved_at=RETRIEVED_AT,
        source_query="state=closed",
    )

    assert result.status == RetrievalStatus.COMPLETE
    assert result.complete is True
    assert result.page_count == 2
    assert result.requested_state == IssueStateFilter.CLOSED
    assert [record.issue_number for record in result.records] == [1, 2]
    assert result.records[0].source_revision == result.records[0].updated_at
    assert reader.calls == [
        ("Blummer92/agent-os", 1, 100, "closed"),
        ("Blummer92/agent-os", 2, 100, "closed"),
    ]


def test_connected_all_state_passes_requested_state_unchanged_to_reader():
    reader = FakeReader(
        {
            1: GitHubIssuePageResponse(
                (_issue(1), _issue(2, state="closed")),
                None,
                terminal_page_proven=True,
            )
        }
    )

    result = scan_connected_issues(
        "Blummer92/agent-os",
        reader,
        state=IssueStateFilter.ALL,
        retrieved_at=RETRIEVED_AT,
        per_page=50,
    )

    assert result.complete is True
    assert result.requested_state == IssueStateFilter.ALL
    assert reader.calls == [("Blummer92/agent-os", 1, 50, "all")]


def test_source_excludes_pull_request_records_from_issue_endpoint():
    pull_request = dict(_issue(9), pull_request={"url": "example"})
    reader = FakeReader(
        {1: GitHubIssuePageResponse((_issue(1), pull_request), None, terminal_page_proven=True)}
    )

    result = scan_issues(
        GitHubIssuePageSource(
            "Blummer92/agent-os",
            reader,
            state=IssueStateFilter.OPEN,
        ),
        requested_state=IssueStateFilter.OPEN,
        retrieved_at=RETRIEVED_AT,
        source_query="repo=Blummer92/agent-os state=open",
    )

    assert result.status == RetrievalStatus.COMPLETE
    assert [record.issue_number for record in result.records] == [1]


def test_incomplete_page_fails_closed_without_false_exact_total():
    reader = FakeReader(
        {
            1: GitHubIssuePageResponse((_issue(1),), 2),
            2: GitHubIssuePageResponse((_issue(2),), 3, complete=False),
        }
    )

    result = scan_issues(
        GitHubIssuePageSource(
            "Blummer92/agent-os",
            reader,
            state=IssueStateFilter.OPEN,
        ),
        requested_state=IssueStateFilter.OPEN,
        retrieved_at=RETRIEVED_AT,
        source_query="repo=Blummer92/agent-os state=open",
    )
    assert result.status == RetrievalStatus.INCOMPLETE
    assert result.complete is False
    assert result.item_count == 1
    assert [record.issue_number for record in result.records] == [1]
    assert RetrievalFinding.PAGE_MISSING_NEXT in result.findings


def test_nonadvancing_page_fails_closed():
    reader = FakeReader({1: GitHubIssuePageResponse((_issue(1),), 1)})

    result = scan_issues(
        GitHubIssuePageSource(
            "Blummer92/agent-os",
            reader,
            state=IssueStateFilter.OPEN,
        ),
        requested_state=IssueStateFilter.OPEN,
        retrieved_at=RETRIEVED_AT,
        source_query="repo=Blummer92/agent-os state=open",
    )

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

    result = scan_issues(
        GitHubIssuePageSource(
            "Blummer92/agent-os",
            reader,
            state=IssueStateFilter.OPEN,
        ),
        requested_state=IssueStateFilter.OPEN,
        retrieved_at=RETRIEVED_AT,
        source_query="repo=Blummer92/agent-os state=open",
    )

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

    result = scan_issues(
        GitHubIssuePageSource(
            "Blummer92/agent-os",
            reader,
            state=IssueStateFilter.OPEN,
        ),
        requested_state=IssueStateFilter.OPEN,
        retrieved_at=RETRIEVED_AT,
        source_query="repo=Blummer92/agent-os state=open",
    )

    assert result.status == RetrievalStatus.INCOMPLETE
    assert result.reasons == (f"page 1: {reason}",)


@pytest.mark.parametrize("state", [None, True, "open", "OPEN", ""])
def test_invalid_source_state_configuration_is_rejected(state):
    reader = FakeReader({})
    with pytest.raises(TypeError):
        GitHubIssuePageSource("Blummer92/agent-os", reader, state=state)


def test_invalid_source_configuration_is_rejected():
    reader = FakeReader({})
    with pytest.raises(ValueError):
        GitHubIssuePageSource(
            "not-a-repository", reader, state=IssueStateFilter.OPEN
        )
    with pytest.raises(ValueError):
        GitHubIssuePageSource(
            "Blummer92/agent-os",
            reader,
            state=IssueStateFilter.OPEN,
            per_page=101,
        )
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


def test_live_shaped_multipage_scan_over_200_proves_completeness_and_excludes_prs() -> None:
    """Phase 0 (Shadow Admission): committed pagination/completeness canary.

    Mirrors the 2026-10-05 live canary shape (two full 100-item pages plus a
    partial terminal page, pull requests interleaved on every page) through the
    canonical paginated scanner. Proves the scan completes beyond 100 items with
    scan-complete, exact page/item counts, PR exclusion, and per-record source
    provenance -- the properties the shadow experiment's population receipt
    depends on.
    """
    pr_numbers = iter(range(9000, 9200))

    def _page_items(numbers: tuple[int, ...]) -> tuple[dict, ...]:
        items: list[dict] = []
        for number in numbers:
            item = _issue(number)
            # The shared helper formats updated_at with the issue number as
            # seconds; keep timestamps valid for numbers past 59.
            item["updated_at"] = f"2026-07-20T00:{(number // 60) % 60:02d}:{number % 60:02d}Z"
            items.append(item)
            if number % 25 == 0:
                items.append(dict(_issue(next(pr_numbers)), pull_request={"url": "example"}))
        return tuple(items)

    reader = FakeReader(
        {
            1: GitHubIssuePageResponse(_page_items(tuple(range(1, 101))), 2),
            2: GitHubIssuePageResponse(_page_items(tuple(range(101, 201))), 3),
            3: GitHubIssuePageResponse(
                _page_items(tuple(range(201, 248))), None, terminal_page_proven=True
            ),
        }
    )

    result = scan_connected_issues(
        "Blummer92/agent-os",
        reader,
        state=IssueStateFilter.OPEN,
        retrieved_at=RETRIEVED_AT,
        per_page=100,
    )

    assert result.status == RetrievalStatus.COMPLETE
    assert result.complete is True
    assert result.page_count == 3
    assert result.item_count == 247
    assert [record.issue_number for record in result.records] == list(range(1, 248))
    assert all(record.source_revision == record.updated_at for record in result.records)
    assert reader.calls == [
        ("Blummer92/agent-os", 1, 100, "open"),
        ("Blummer92/agent-os", 2, 100, "open"),
        ("Blummer92/agent-os", 3, 100, "open"),
    ]
