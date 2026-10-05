"""Phase 1 B5: per-page scan provenance on shadow selection results.

Covers: provenance recorded verbatim on ShadowIssueSelectionResult, additive
backward compatibility of every touched constructor, provenance validation,
and scan replay from recorded provenance (decisions are reconstructible).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agent_os_execution_service.shadow_issue_selection import (
    ScanPageProvenance,
    ScanProvenanceLog,
    ShadowIssueSelectionResult,
    ShadowSelectionStatus,
    select_shadow_issue,
)
from scripts.agent_os_candidate_packet_live_input import (
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)
from scripts.agent_os_github_issue_provider.revision import issue_source_revision
from scripts.agent_os_issue_acceptance.github_issue_source import GitHubIssuePageResponse


REPOSITORY = "Blummer92/agent-os"
RETRIEVED_AT = "2026-10-05T16:00:00Z"
SCAN_STARTED_AT = "2026-10-05T16:00:01Z"
SCAN_ENDED_AT = "2026-10-05T16:00:04Z"


def raw_issue(number: int) -> dict[str, object]:
    item: dict[str, object] = {
        "number": number,
        "title": f"Issue {number}",
        "state": "open",
        "body": f"body-{number}",
        "html_url": f"https://github.com/Blummer92/agent-os/issues/{number}",
        "created_at": "2026-10-05T15:00:00Z",
        "updated_at": "2026-10-05T15:30:00Z",
        "closed_at": None,
        "state_reason": None,
        "labels": [{"name": "agent-os"}],
    }
    item["source_revision"] = issue_source_revision(item)
    return item


def make_provenance(page: int, item_count: int, *, next_page: int | None) -> ScanPageProvenance:
    return ScanPageProvenance(
        page=page,
        item_count=item_count,
        next_page=next_page,
        source_query_string=f"state=open&per_page=100&page={page}",
        link_next_url=(
            f"https://api.github.com/repos/{REPOSITORY}/issues"
            f"?state=open&per_page=100&page={next_page}"
            if next_page is not None
            else None
        ),
        rate_limit_remaining="59",
        terminal_page_proven=next_page is None,
        error_kind=None,
    )


@dataclass
class RecordingPageReader:
    """Serves fixed pages while noting the provenance a live reader observes."""

    pages: dict[int, tuple[dict[str, object], ...]]
    log: ScanProvenanceLog

    def read_issue_page(
        self, repository: str, *, page: int, per_page: int, state: str
    ) -> GitHubIssuePageResponse:
        assert repository == REPOSITORY
        assert per_page == 100
        assert state == "open"
        items = self.pages[page]
        next_page = page + 1 if page + 1 in self.pages else None
        entry = make_provenance(page, len(items), next_page=next_page)
        self.log.note_page(entry, at=SCAN_STARTED_AT if page == 1 else SCAN_ENDED_AT)
        return GitHubIssuePageResponse(
            items=tuple(items),
            next_page=entry.next_page,
            complete=True,
            terminal_page_proven=entry.terminal_page_proven,
            page=entry.page,
            source_query_string=entry.source_query_string,
            link_next_url=entry.link_next_url,
            rate_limit_remaining=entry.rate_limit_remaining,
        )


class ReplayPageReader:
    """Replays a recorded scan using only its provenance fields.

    Pages are routed by the recorded source_query_string; the served items
    must match the recorded per-page item_count, and the replayed provenance
    log must equal the original, proving the provenance suffices to
    reconstruct the scan.
    """

    def __init__(
        self, recorded_pages: list[dict[str, object]], log: ScanProvenanceLog
    ) -> None:
        self._pages = {
            str(entry["source_query_string"]): entry for entry in recorded_pages
        }
        self._log = log
        self._at = SCAN_STARTED_AT

    def read_issue_page(
        self, repository: str, *, page: int, per_page: int, state: str
    ) -> GitHubIssuePageResponse:
        assert repository == REPOSITORY
        query_string = f"state={state}&per_page={per_page}&page={page}"
        recorded = self._pages[query_string]
        assert recorded["page"] == page
        items = tuple(recorded["items"])  # type: ignore[arg-type]
        assert len(items) == recorded["item_count"], "provenance item_count mismatch"
        entry = ScanPageProvenance(
            **{k: v for k, v in recorded.items() if k != "items"}
        )
        self._log.note_page(entry, at=self._at)
        self._at = SCAN_ENDED_AT
        return GitHubIssuePageResponse(
            items=items,
            next_page=entry.next_page,
            complete=True,
            terminal_page_proven=entry.terminal_page_proven,
            page=entry.page,
            source_query_string=entry.source_query_string,
            link_next_url=entry.link_next_url,
            rate_limit_remaining=entry.rate_limit_remaining,
        )


class NoEvidenceReader:
    """Phase-0 boundary: supplies no candidate evidence."""

    def read_candidate_evidence(self, repository: str, issue_number: int):
        return None


class NullTransport:
    def get_issue(self, repository: str, issue_number: int) -> SingleIssueTransportResult:
        return SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.NOT_FOUND)


def run_selection(pages: dict[int, tuple[dict[str, object], ...]]):
    """Run one fail-closed selection; return (result, filled provenance log)."""
    log = ScanProvenanceLog()
    reader = RecordingPageReader(pages, log)
    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-b5",
        page_reader=reader,
        issue_transport=NullTransport(),
        candidate_evidence_reader=NoEvidenceReader(),
        scan_provenance_log=log,
    )
    return result, log


def test_result_records_scan_provenance_verbatim() -> None:
    result, log = run_selection({1: (raw_issue(3), raw_issue(1)), 2: (raw_issue(2),)})

    assert result.scan_started_at == SCAN_STARTED_AT
    assert result.scan_ended_at == SCAN_ENDED_AT
    assert result.scan_source_query == f"repo={REPOSITORY} state=open"
    assert result.scan_page_provenance == tuple(log.entries)
    assert [entry.page for entry in result.scan_page_provenance] == [1, 2]
    assert [entry.item_count for entry in result.scan_page_provenance] == [2, 1]
    assert result.scan_page_provenance[0].link_next_url == (
        f"https://api.github.com/repos/{REPOSITORY}/issues?state=open&per_page=100&page=2"
    )
    assert result.scan_page_provenance[1].link_next_url is None
    assert result.scan_page_provenance[1].terminal_page_proven is True
    assert all(entry.rate_limit_remaining == "59" for entry in result.scan_page_provenance)
    # The provenance never alters the decision itself.
    assert result.status is ShadowSelectionStatus.NO_SELECTION
    assert result.reason_codes == ("shadow-selection.candidate-evidence-incomplete",)
    assert result.population_issue_numbers == (1, 2, 3)


def test_provenance_fields_default_for_existing_constructors() -> None:
    result = ShadowIssueSelectionResult(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        population_issue_numbers=(1, 2),
        candidate_issue_numbers=(1, 2),
        scan_page_count=1,
        scan_item_count=2,
        repository_source_revision=None,
        selection=None,
        selected_issue_number=None,
        selected_issue_revision=None,
        status=ShadowSelectionStatus.NO_SELECTION,
        reason_codes=("shadow-selection.candidate-evidence-incomplete",),
    )
    assert result.scan_started_at is None
    assert result.scan_ended_at is None
    assert result.scan_source_query is None
    assert result.scan_page_provenance == ()


def test_select_shadow_issue_defaults_to_empty_provenance() -> None:
    reader = RecordingPageReader({1: (raw_issue(1),)}, ScanProvenanceLog())
    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-b5",
        page_reader=reader,
        issue_transport=NullTransport(),
        candidate_evidence_reader=NoEvidenceReader(),
    )
    assert result.scan_page_provenance == ()
    assert result.scan_started_at is None


def test_provenance_log_note_page_validates() -> None:
    log = ScanProvenanceLog()
    with pytest.raises(TypeError, match="ScanPageProvenance"):
        log.note_page("not-provenance", at=SCAN_STARTED_AT)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at must use"):
        log.note_page(make_provenance(1, 1, next_page=None), at="not-a-timestamp")
    log.note_page(make_provenance(1, 1, next_page=2), at=SCAN_STARTED_AT)
    log.note_page(make_provenance(2, 1, next_page=None), at=SCAN_ENDED_AT)
    assert log.scan_started_at == SCAN_STARTED_AT
    assert log.scan_ended_at == SCAN_ENDED_AT
    assert [entry.page for entry in log.entries] == [1, 2]


def test_provenance_validation_rejects_bad_input() -> None:
    good = (make_provenance(1, 2, next_page=None),)
    base = {
        "repository": REPOSITORY,
        "retrieved_at": RETRIEVED_AT,
        "population_issue_numbers": (1,),
        "candidate_issue_numbers": (1,),
        "scan_page_count": 1,
        "scan_item_count": 1,
        "repository_source_revision": None,
        "selection": None,
        "selected_issue_number": None,
        "selected_issue_revision": None,
        "status": ShadowSelectionStatus.NO_SELECTION,
        "reason_codes": ("shadow-selection.candidate-evidence-incomplete",),
        "scan_page_provenance": good,
    }
    with pytest.raises(ValueError, match="scan_started_at"):
        ShadowIssueSelectionResult(**{**base, "scan_started_at": "not-a-timestamp"})
    with pytest.raises(ValueError, match="scan_started_at cannot be later"):
        ShadowIssueSelectionResult(
            **{
                **base,
                "scan_started_at": SCAN_ENDED_AT,
                "scan_ended_at": SCAN_STARTED_AT,
            }
        )
    with pytest.raises(TypeError, match="scan_page_provenance"):
        ShadowIssueSelectionResult(**{**base, "scan_page_provenance": list(good)})
    with pytest.raises(TypeError, match="scan_provenance_log"):
        select_shadow_issue(
            repository=REPOSITORY,
            retrieved_at=RETRIEVED_AT,
            campaign_id="campaign-b5",
            page_reader=RecordingPageReader({1: (raw_issue(1),)}, ScanProvenanceLog()),
            issue_transport=NullTransport(),
            candidate_evidence_reader=NoEvidenceReader(),
            scan_provenance_log="not-a-log",  # type: ignore[arg-type]
        )


def test_scan_replay_from_provenance_reproduces_population_receipt() -> None:
    """Item 4: the provenance suffices to reconstruct the decision inputs."""
    pages = {1: (raw_issue(3), raw_issue(1)), 2: (raw_issue(2),)}
    first, first_log = run_selection(pages)

    # Durable record: provenance fields plus the per-page items they describe.
    recorded = [
        {**entry.to_dict(), "items": [dict(item) for item in pages[entry.page]]}
        for entry in first.scan_page_provenance
    ]

    # Replay uses ONLY the recorded provenance (plus the durable page items):
    # routing comes from source_query_string, expectations from item_count,
    # and the replayed log must equal the original.
    replay_log = ScanProvenanceLog()
    replay_reader = ReplayPageReader(recorded, replay_log)
    second = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-b5",
        page_reader=replay_reader,
        issue_transport=NullTransport(),
        candidate_evidence_reader=NoEvidenceReader(),
        scan_provenance_log=replay_log,
    )

    assert second.population_issue_numbers == first.population_issue_numbers == (1, 2, 3)
    assert second.scan_page_count == first.scan_page_count == 2
    assert second.scan_item_count == first.scan_item_count == 3
    assert replay_log.entries == first_log.entries
    assert [entry.page for entry in second.scan_page_provenance] == [1, 2]
    assert [entry.source_query_string for entry in second.scan_page_provenance] == [
        "state=open&per_page=100&page=1",
        "state=open&per_page=100&page=2",
    ]
    assert second.reason_codes == first.reason_codes


def test_page_response_provenance_fields_are_additive() -> None:
    legacy = GitHubIssuePageResponse(items=(), next_page=None)
    assert legacy.page is None
    assert legacy.source_query_string is None
    assert legacy.link_next_url is None
    assert legacy.rate_limit_remaining is None

    with pytest.raises(ValueError, match="page"):
        GitHubIssuePageResponse(items=(), next_page=None, page=0)
    with pytest.raises(ValueError, match="source_query_string"):
        GitHubIssuePageResponse(items=(), next_page=None, source_query_string="  ")
    with pytest.raises(TypeError, match="rate_limit_remaining"):
        GitHubIssuePageResponse(items=(), next_page=None, rate_limit_remaining=57)
