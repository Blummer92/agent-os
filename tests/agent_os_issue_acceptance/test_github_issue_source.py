from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.github_issue_source import (
    GitHubIssuePageResponse,
    GitHubIssuePageSource,
    result_to_report,
    scan_connected_issues,
    scan_connected_open_issues,
)
from scripts.agent_os_issue_acceptance.issue_scanner import (
    IssueStateFilter,
    RetrievalFinding,
    RetrievalStatus,
    scan_issues,
    scan_open_issues,
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
            2: GitHubIssuePageResponse((_issue(1, state="closed"),), None),
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


def test_report_handoff_preserves_existing_keys_and_adds_state_evidence():
    reader = FakeReader(
        {
            1: GitHubIssuePageResponse(
                (
                    _issue(
                        3,
                        state="closed",
                        closed_at="2026-07-21T00:00:00Z",
                        state_reason="completed",
                    ),
                ),
                None,
            )
        }
    )

    result = scan_connected_issues(
        "Blummer92/agent-os",
        reader,
        state=IssueStateFilter.CLOSED,
        retrieved_at=RETRIEVED_AT,
        per_page=50,
    )
    report = result_to_report(result)

    assert list(report) == [
        "status",
        "complete",
        "page_count",
        "item_count",
        "requested_state",
        "retrieved_at",
        "source_query",
        "findings",
        "reasons",
        "issues",
    ]
    assert report["status"] == "complete"
    assert report["complete"] is True
    assert report["page_count"] == 1
    assert report["item_count"] == 1
    assert report["requested_state"] == "closed"
    assert report["retrieved_at"] == RETRIEVED_AT
    assert report["source_query"] == "repo=Blummer92/agent-os state=closed"
    assert report["issues"] == [
        {
            "issue_number": 3,
            "title": "Issue 3",
            "state": "closed",
            "labels": ["status:ready"],
            "url": "https://github.com/Blummer92/agent-os/issues/3",
            "created_at": "2026-07-20T00:00:00Z",
            "updated_at": "2026-07-20T00:00:03Z",
            "source_revision": "2026-07-20T00:00:03Z",
            "closed_at": "2026-07-21T00:00:00Z",
            "state_reason": "completed",
        }
    ]
    assert reader.calls == [("Blummer92/agent-os", 1, 50, "closed")]


def test_compatibility_connected_wrapper_preserves_open_contract_without_clock():
    reader = FakeReader({1: GitHubIssuePageResponse((_issue(1),), None)})

    result = scan_connected_open_issues("Blummer92/agent-os", reader, per_page=25)
    report = result_to_report(result)

    assert result.requested_state == IssueStateFilter.OPEN
    assert result.retrieved_at is None
    assert report["requested_state"] == "open"
    assert report["retrieved_at"] is None
    assert reader.calls == [("Blummer92/agent-os", 1, 25, "open")]


def test_source_excludes_pull_request_records_from_issue_endpoint():
    pull_request = dict(_issue(9), pull_request={"url": "example"})
    reader = FakeReader(
        {1: GitHubIssuePageResponse((_issue(1), pull_request), None)}
    )

    result = scan_open_issues(
        GitHubIssuePageSource(
            "Blummer92/agent-os",
            reader,
            state=IssueStateFilter.OPEN,
        )
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

    result = scan_open_issues(
        GitHubIssuePageSource(
            "Blummer92/agent-os",
            reader,
            state=IssueStateFilter.OPEN,
        )
    )
    report = result_to_report(result)

    assert result.status == RetrievalStatus.INCOMPLETE
    assert report["complete"] is False
    assert report["item_count"] == 1
    assert [issue["issue_number"] for issue in report["issues"]] == [1]
    assert RetrievalFinding.PAGE_MISSING_NEXT in result.findings


def test_nonadvancing_page_fails_closed():
    reader = FakeReader({1: GitHubIssuePageResponse((_issue(1),), 1)})

    result = scan_open_issues(
        GitHubIssuePageSource(
            "Blummer92/agent-os",
            reader,
            state=IssueStateFilter.OPEN,
        )
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

    result = scan_open_issues(
        GitHubIssuePageSource(
            "Blummer92/agent-os",
            reader,
            state=IssueStateFilter.OPEN,
        )
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

    result = scan_open_issues(
        GitHubIssuePageSource(
            "Blummer92/agent-os",
            reader,
            state=IssueStateFilter.OPEN,
        )
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
    with pytest.raises(TypeError):
        result_to_report(object())


def test_response_is_immutable():
    response = GitHubIssuePageResponse((), None)
    with pytest.raises(FrozenInstanceError):
        response.complete = False


def test_repeated_report_output_is_deterministic():
    def build_report():
        reader = FakeReader({1: GitHubIssuePageResponse((_issue(1),), None)})
        return result_to_report(
            scan_connected_issues(
                "Blummer92/agent-os",
                reader,
                state=IssueStateFilter.OPEN,
                retrieved_at=RETRIEVED_AT,
            )
        )

    assert build_report() == build_report()


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
