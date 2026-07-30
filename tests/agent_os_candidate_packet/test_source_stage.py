from __future__ import annotations

from scripts.agent_os_candidate_packet.source_stage import resolve_issue_snapshot
from scripts.agent_os_candidate_packet.stage_models import (
    IssueReadResult,
    IssueReadStatus,
    IssueSourceStageStatus,
)

_BASE_ITEM = {
    "number": 750,
    "title": "AOS-AUTO1A",
    "state": "open",
    "body": "Exact body text.",
    "html_url": "https://github.com/blummer92/agent-os/issues/750",
    "created_at": "2026-07-01T00:00:00Z",
    "updated_at": "2026-07-02T00:00:00Z",
    "closed_at": None,
    "state_reason": None,
    "labels": [],
}


class _FakeReader:
    def __init__(self, result: IssueReadResult) -> None:
        self._result = result
        self.calls: list[tuple[str, int]] = []

    def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
        self.calls.append((repository, issue_number))
        return self._result


class _RaisingReader:
    def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
        raise RuntimeError("boom")


def test_exact_issue_body_and_source_revision_binding() -> None:
    reader = _FakeReader(IssueReadResult(status=IssueReadStatus.OK, item=dict(_BASE_ITEM)))
    result = resolve_issue_snapshot(
        "blummer92/agent-os", 750, reader, retrieved_at="2026-07-30T00:00:00Z"
    )
    assert result.status == IssueSourceStageStatus.RESOLVED
    snapshot = result.snapshot
    assert snapshot is not None
    assert snapshot.body == _BASE_ITEM["body"]
    assert snapshot.repository == "blummer92/agent-os"
    assert snapshot.issue_number == 750
    assert snapshot.url == _BASE_ITEM["html_url"]
    assert snapshot.source_revision.startswith("github-issue-v1:")
    assert len(snapshot.body_sha256) == 64
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_deterministic_repeated_output() -> None:
    reader = _FakeReader(IssueReadResult(status=IssueReadStatus.OK, item=dict(_BASE_ITEM)))
    first = resolve_issue_snapshot(
        "blummer92/agent-os", 750, reader, retrieved_at="2026-07-30T00:00:00Z"
    )
    second = resolve_issue_snapshot(
        "blummer92/agent-os", 750, reader, retrieved_at="2026-07-30T00:00:00Z"
    )
    assert first.snapshot == second.snapshot
    assert first.status == second.status


def test_malformed_source_fails_closed_to_incomplete_evidence() -> None:
    reader = _FakeReader(
        IssueReadResult(status=IssueReadStatus.MALFORMED_RESPONSE, item=None)
    )
    result = resolve_issue_snapshot(
        "blummer92/agent-os", 750, reader, retrieved_at="2026-07-30T00:00:00Z"
    )
    assert result.status == IssueSourceStageStatus.INCOMPLETE_EVIDENCE
    assert result.snapshot is None
    assert "source.malformed-response" in result.reason_codes


def test_inaccessible_source_fails_closed_to_source_failure() -> None:
    reader = _FakeReader(
        IssueReadResult(status=IssueReadStatus.SOURCE_INACCESSIBLE, item=None)
    )
    result = resolve_issue_snapshot(
        "blummer92/agent-os", 750, reader, retrieved_at="2026-07-30T00:00:00Z"
    )
    assert result.status == IssueSourceStageStatus.SOURCE_FAILURE
    assert result.snapshot is None
    assert "source.inaccessible" in result.reason_codes


def test_partial_source_missing_fields_fails_closed() -> None:
    incomplete_item = dict(_BASE_ITEM)
    del incomplete_item["updated_at"]
    reader = _FakeReader(IssueReadResult(status=IssueReadStatus.OK, item=incomplete_item))
    result = resolve_issue_snapshot(
        "blummer92/agent-os", 750, reader, retrieved_at="2026-07-30T00:00:00Z"
    )
    assert result.status == IssueSourceStageStatus.INCOMPLETE_EVIDENCE
    assert result.snapshot is None
    assert "source.missing-fields" in result.reason_codes


def test_reader_exception_fails_closed_to_source_failure() -> None:
    result = resolve_issue_snapshot(
        "blummer92/agent-os", 750, _RaisingReader(), retrieved_at="2026-07-30T00:00:00Z"
    )
    assert result.status == IssueSourceStageStatus.SOURCE_FAILURE
    assert "source.reader-error" in result.reason_codes


def test_source_movement_changes_source_revision() -> None:
    reader_a = _FakeReader(IssueReadResult(status=IssueReadStatus.OK, item=dict(_BASE_ITEM)))
    moved_item = dict(_BASE_ITEM)
    moved_item["body"] = "Body changed after issue movement."
    reader_b = _FakeReader(IssueReadResult(status=IssueReadStatus.OK, item=moved_item))

    result_a = resolve_issue_snapshot(
        "blummer92/agent-os", 750, reader_a, retrieved_at="2026-07-30T00:00:00Z"
    )
    result_b = resolve_issue_snapshot(
        "blummer92/agent-os", 750, reader_b, retrieved_at="2026-07-30T00:01:00Z"
    )
    assert result_a.snapshot is not None
    assert result_b.snapshot is not None
    assert result_a.snapshot.source_revision != result_b.snapshot.source_revision


def test_issue_reader_protocol_has_no_write_method() -> None:
    from scripts.agent_os_candidate_packet.stage_models import IssueSourceReader

    protocol_members = {
        name for name in dir(IssueSourceReader) if not name.startswith("_")
    }
    assert protocol_members == {"read_issue"}
