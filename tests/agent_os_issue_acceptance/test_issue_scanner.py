from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from scripts.agent_os_issue_acceptance.issue_scanner import (
    IssueScanPage,
    IssueStateFilter,
    RetrievalFinding,
    RetrievalStatus,
    scan_issues,
    scan_open_issues,
)


RETRIEVED_AT = "2026-07-21T22:00:00Z"


class OtherState(str, __import__("enum").Enum):
    OPEN = "open"


class FakePageSource:
    def __init__(self, pages):
        self.pages = pages
        self.requested_pages = []

    def fetch_page(self, page: int) -> IssueScanPage:
        self.requested_pages.append(page)
        return self.pages[page]


def _issue(number: int, *, state="open", labels=None, **overrides):
    issue = {
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "body": f"Body {number}",
        "html_url": f"https://github.com/Blummer92/agent-os/issues/{number}",
        "created_at": "2026-07-19T00:00:00Z",
        "updated_at": f"2026-07-19T00:00:{number:02d}Z",
        "labels": labels if labels is not None else [{"name": "status:ready"}],
    }
    issue.update(overrides)
    return issue


def _scan(source, state=IssueStateFilter.OPEN):
    return scan_issues(
        source,
        requested_state=state,
        retrieved_at=RETRIEVED_AT,
        source_query=f"state={state.value}",
    )


def test_scanner_collects_complete_paginated_results_deterministically():
    source = FakePageSource(
        {
            1: IssueScanPage(items=(_issue(2),), next_page=2),
            2: IssueScanPage(items=(_issue(1),), next_page=None),
        }
    )

    result = _scan(source)

    assert result.status == RetrievalStatus.COMPLETE
    assert result.complete is True
    assert result.findings == (RetrievalFinding.COMPLETE,)
    assert result.page_count == 2
    assert result.item_count == 2
    assert result.requested_state == IssueStateFilter.OPEN
    assert result.retrieved_at == RETRIEVED_AT
    assert [record.issue_number for record in result.records] == [1, 2]
    assert source.requested_pages == [1, 2]


def test_scanner_preserves_issue_provenance_labels_and_optional_closure_evidence():
    source = FakePageSource(
        {
            1: IssueScanPage(
                items=(
                    _issue(
                        3,
                        state="closed",
                        labels=(
                            {"name": "owner:integration-manager"},
                            "status:ready",
                        ),
                        closed_at="2026-07-20T00:00:00Z",
                        state_reason="completed",
                    ),
                ),
                next_page=None,
            )
        }
    )

    result = _scan(source, IssueStateFilter.CLOSED)
    record = result.records[0]

    assert record.issue_number == 3
    assert record.url.endswith("/issues/3")
    assert record.source_revision == record.updated_at
    assert record.labels == ("owner:integration-manager", "status:ready")
    assert record.closed_at == "2026-07-20T00:00:00Z"
    assert record.state_reason == "completed"


def test_closed_record_without_closure_evidence_is_valid():
    result = _scan(
        FakePageSource(
            {
                1: IssueScanPage(
                    (_issue(1, state="closed", state_reason=None),),
                    None,
                )
            }
        ),
        IssueStateFilter.CLOSED,
    )

    assert result.complete is True
    assert result.records[0].closed_at is None
    assert result.records[0].state_reason is None


def test_open_record_preserves_closure_evidence_without_inferring_state():
    result = _scan(
        FakePageSource(
            {
                1: IssueScanPage(
                    (
                        _issue(
                            1,
                            state="open",
                            closed_at="2026-07-20T00:00:00Z",
                            state_reason="reopened",
                        ),
                    ),
                    None,
                )
            }
        )
    )

    assert result.complete is True
    assert result.records[0].state == "open"
    assert result.records[0].closed_at == "2026-07-20T00:00:00Z"
    assert result.records[0].state_reason == "reopened"


@pytest.mark.parametrize("state", [IssueStateFilter.OPEN, IssueStateFilter.CLOSED])
def test_all_state_scan_accepts_single_state_results(state):
    result = _scan(
        FakePageSource({1: IssueScanPage((_issue(1, state=state.value),), None)}),
        IssueStateFilter.ALL,
    )

    assert result.complete is True
    assert result.records[0].state == state.value


def test_all_state_scan_accepts_mixed_records():
    result = _scan(
        FakePageSource(
            {
                1: IssueScanPage(
                    (_issue(2, state="closed"), _issue(1, state="open")),
                    None,
                )
            }
        ),
        IssueStateFilter.ALL,
    )

    assert result.complete is True
    assert [(record.issue_number, record.state) for record in result.records] == [
        (1, "open"),
        (2, "closed"),
    ]


@pytest.mark.parametrize(
    "requested_state", [None, True, False, "open", "OPEN", "all", "", OtherState.OPEN]
)
def test_invalid_requested_state_is_rejected(requested_state):
    source = FakePageSource({1: IssueScanPage((), None)})
    with pytest.raises(TypeError):
        scan_issues(
            source,
            requested_state=requested_state,
            retrieved_at=RETRIEVED_AT,
        )


def test_state_aware_scan_requires_caller_supplied_timestamp():
    source = FakePageSource({1: IssueScanPage((), None)})
    with pytest.raises(TypeError):
        scan_issues(
            source,
            requested_state=IssueStateFilter.OPEN,
            retrieved_at=None,
        )


@pytest.mark.parametrize("retrieved_at", ["", "2026-07-21", "2026-13-21T22:00:00Z", True])
def test_state_aware_scan_rejects_malformed_timestamp(retrieved_at):
    source = FakePageSource({1: IssueScanPage((), None)})
    with pytest.raises((TypeError, ValueError)):
        scan_issues(
            source,
            requested_state=IssueStateFilter.OPEN,
            retrieved_at=retrieved_at,
        )


def test_compatibility_wrapper_yields_open_state_without_reading_clock():
    source = FakePageSource({1: IssueScanPage((_issue(1),), None)})

    result = scan_open_issues(source)

    assert result.complete is True
    assert result.requested_state == IssueStateFilter.OPEN
    assert result.retrieved_at is None
    assert result.source_query == "state=open"


@pytest.mark.parametrize("actual_state", ["all", "OPEN", "", True, None])
def test_scanner_rejects_malformed_actual_state(actual_state):
    result = _scan(
        FakePageSource({1: IssueScanPage((_issue(1, state=actual_state),), None)})
    )

    assert result.status == RetrievalStatus.INCOMPLETE
    assert RetrievalFinding.MISSING_FIELD in result.findings
    assert "exactly 'open' or 'closed'" in result.reasons[0]


@pytest.mark.parametrize(
    ("requested_state", "actual_state"),
    [
        (IssueStateFilter.OPEN, "closed"),
        (IssueStateFilter.CLOSED, "open"),
    ],
)
def test_scanner_fails_closed_on_requested_actual_state_mismatch(
    requested_state, actual_state
):
    result = _scan(
        FakePageSource({1: IssueScanPage((_issue(1, state=actual_state),), None)}),
        requested_state,
    )

    assert result.status == RetrievalStatus.INCOMPLETE
    assert result.findings == (RetrievalFinding.SOURCE_STATE_MISMATCH,)
    assert "returned state" in result.reasons[0]
    assert result.item_count == 0


@pytest.mark.parametrize("number", [True, False, 0, -1, "1", 1.0])
def test_scanner_rejects_non_positive_or_non_integer_issue_number(number):
    malformed_issue = _issue(1)
    malformed_issue["number"] = number
    result = _scan(
        FakePageSource({1: IssueScanPage((malformed_issue,), None)})
    )

    assert result.status == RetrievalStatus.INCOMPLETE
    assert "positive integer" in result.reasons[0]


def test_scanner_fails_closed_when_pagination_completeness_unknown():
    source = FakePageSource(
        {
            1: IssueScanPage(items=(_issue(1),), next_page=2, complete=False),
        }
    )

    result = _scan(source)

    assert result.status == RetrievalStatus.INCOMPLETE
    assert result.complete is False
    assert RetrievalFinding.PAGE_MISSING_NEXT in result.findings
    assert "pagination completeness is unknown" in result.reasons[0]
    assert result.item_count == 0


def test_incomplete_later_page_preserves_prior_diagnostic_records_without_exact_total():
    source = FakePageSource(
        {
            1: IssueScanPage(items=(_issue(2),), next_page=2),
            2: IssueScanPage(items=(_issue(1),), next_page=3, complete=False),
        }
    )

    result = _scan(source)

    assert result.status == RetrievalStatus.INCOMPLETE
    assert result.complete is False
    assert result.item_count == 1
    assert [record.issue_number for record in result.records] == [2]
    assert RetrievalFinding.PAGE_MISSING_NEXT in result.findings


def test_scanner_fails_closed_on_missing_required_field():
    incomplete_issue = dict(_issue(1))
    incomplete_issue.pop("updated_at")
    source = FakePageSource(
        {
            1: IssueScanPage(items=(incomplete_issue,), next_page=None),
        }
    )

    result = _scan(source)

    assert result.status == RetrievalStatus.INCOMPLETE
    assert RetrievalFinding.MISSING_FIELD in result.findings
    assert "updated_at" in result.reasons[0]


def test_scanner_fails_closed_on_api_error_and_preserves_prior_records():
    source = FakePageSource(
        {
            1: IssueScanPage(items=(_issue(1),), next_page=2),
            2: IssueScanPage(items=(), next_page=None, error="rate limit"),
        }
    )

    result = _scan(source)

    assert result.status == RetrievalStatus.INCOMPLETE
    assert RetrievalFinding.API_ERROR in result.findings
    assert result.reasons == ("page 2: rate limit",)
    assert result.item_count == 1


def test_scanner_fails_closed_on_duplicate_issue_number():
    source = FakePageSource(
        {
            1: IssueScanPage(items=(_issue(1),), next_page=2),
            2: IssueScanPage(items=(_issue(1),), next_page=None),
        }
    )

    result = _scan(source)

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

    result = _scan(source)

    assert result.status == RetrievalStatus.INCOMPLETE
    assert RetrievalFinding.PAGE_MISSING_NEXT in result.findings
    assert "does not advance pagination" in result.reasons[0]


def test_repeated_scan_results_are_deterministic_and_immutable():
    def build_source():
        return FakePageSource({1: IssueScanPage((_issue(1),), None)})

    first = _scan(build_source())
    second = _scan(build_source())

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.item_count = 99
