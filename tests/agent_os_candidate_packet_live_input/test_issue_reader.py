"""AOS-AUTO1H ``LiveIssueReader`` mapping tests (#1155)."""

from __future__ import annotations

import pytest

from scripts.agent_os_candidate_packet.stage_models import IssueReadResult, IssueReadStatus
from scripts.agent_os_candidate_packet_live_input.issue_reader import (
    LiveIssueReader,
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)

_REPOSITORY = "Blummer92/agent-os"
_ISSUE_NUMBER = 1155
_ITEM = {
    "number": _ISSUE_NUMBER,
    "html_url": f"https://github.com/{_REPOSITORY}/issues/{_ISSUE_NUMBER}",
    "created_at": "2026-08-15T00:00:00Z",
    "updated_at": "2026-08-15T00:00:00Z",
    "body": "live body",
}


class _FixedTransport:
    def __init__(self, result: SingleIssueTransportResult) -> None:
        self._result = result
        self.calls: list[tuple[str, int]] = []

    def get_issue(self, repository: str, issue_number: int) -> SingleIssueTransportResult:
        self.calls.append((repository, issue_number))
        return self._result


def test_ok_transport_result_maps_to_ok_issue_read_result() -> None:
    transport = _FixedTransport(
        SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.OK, item=dict(_ITEM))
    )
    reader = LiveIssueReader(transport=transport)

    result = reader.read_issue(_REPOSITORY, _ISSUE_NUMBER)

    assert isinstance(result, IssueReadResult)
    assert result.status is IssueReadStatus.OK
    assert result.item == _ITEM
    assert transport.calls == [(_REPOSITORY, _ISSUE_NUMBER)]


def test_not_found_maps_to_not_found() -> None:
    transport = _FixedTransport(
        SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.NOT_FOUND)
    )
    result = LiveIssueReader(transport=transport).read_issue(_REPOSITORY, _ISSUE_NUMBER)
    assert result.status is IssueReadStatus.NOT_FOUND
    assert result.item is None


def test_permission_denied_maps_to_permission_denied() -> None:
    transport = _FixedTransport(
        SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.PERMISSION_DENIED)
    )
    result = LiveIssueReader(transport=transport).read_issue(_REPOSITORY, _ISSUE_NUMBER)
    assert result.status is IssueReadStatus.PERMISSION_DENIED


def test_source_inaccessible_maps_to_source_inaccessible() -> None:
    transport = _FixedTransport(
        SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.SOURCE_INACCESSIBLE)
    )
    result = LiveIssueReader(transport=transport).read_issue(_REPOSITORY, _ISSUE_NUMBER)
    assert result.status is IssueReadStatus.SOURCE_INACCESSIBLE


def test_transport_malformed_response_maps_to_malformed_response() -> None:
    transport = _FixedTransport(
        SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.MALFORMED_RESPONSE)
    )
    result = LiveIssueReader(transport=transport).read_issue(_REPOSITORY, _ISSUE_NUMBER)
    assert result.status is IssueReadStatus.MALFORMED_RESPONSE


def test_api_error_maps_to_api_error_never_ok() -> None:
    transport = _FixedTransport(
        SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.API_ERROR)
    )
    result = LiveIssueReader(transport=transport).read_issue(_REPOSITORY, _ISSUE_NUMBER)
    assert result.status is IssueReadStatus.API_ERROR
    assert result.status is not IssueReadStatus.OK


def test_ok_outcome_with_non_mapping_item_maps_to_malformed_response() -> None:
    # Built via a valid result then mutated, to exercise the reader's own
    # independent Mapping-type guard rather than the dataclass's own check.
    result = SingleIssueTransportResult(
        outcome=SingleIssueTransportOutcome.OK, item={"number": _ISSUE_NUMBER}
    )
    object.__setattr__(result, "item", "not-a-mapping")

    class _Transport:
        def get_issue(self, repository: str, issue_number: int) -> SingleIssueTransportResult:
            return result

    reader_result = LiveIssueReader(transport=_Transport()).read_issue(_REPOSITORY, _ISSUE_NUMBER)

    assert reader_result.status is IssueReadStatus.MALFORMED_RESPONSE
    assert reader_result.item is None


def test_reported_issue_number_mismatch_fails_closed_to_malformed_response() -> None:
    mismatched_item = dict(_ITEM, number=_ISSUE_NUMBER + 1)
    transport = _FixedTransport(
        SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.OK, item=mismatched_item)
    )

    result = LiveIssueReader(transport=transport).read_issue(_REPOSITORY, _ISSUE_NUMBER)

    assert result.status is IssueReadStatus.MALFORMED_RESPONSE
    assert result.item is None


def test_transport_returning_a_foreign_object_raises_type_error() -> None:
    class _BadTransport:
        def get_issue(self, repository: str, issue_number: int) -> object:
            return {"outcome": "ok"}

    reader = LiveIssueReader(transport=_BadTransport())
    with pytest.raises(TypeError):
        reader.read_issue(_REPOSITORY, _ISSUE_NUMBER)


def test_missing_transport_raises_type_error() -> None:
    with pytest.raises(TypeError):
        LiveIssueReader(transport=None)


def test_reader_execution_authorized_is_always_false() -> None:
    transport = _FixedTransport(
        SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.OK, item=dict(_ITEM))
    )
    reader = LiveIssueReader(transport=transport)
    assert reader.execution_authorized is False
