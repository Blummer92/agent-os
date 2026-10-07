"""Phase 1 B5: shadow-run CLI provenance capture and evidence ledger emission.

Covers: LivePageReader per-page provenance capture (query string, Link next
URL, rate-limit remainder, scan timestamps), --mission-id resolution
(explicit vs deterministic derivation), and the additive evidence_ledger
section of the experiment record.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "agent-os-shadow-run.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("agent_os_shadow_run_b5", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_os_shadow_run_b5"] = module
    spec.loader.exec_module(module)
    return module


cli = _load_cli()

from agent_os_execution_service.shadow_issue_selection import (  # noqa: E402
    ShadowIssueSelectionResult,
    ShadowSelectionStatus,
)


class FakeClient:
    """Stub GitHubReadClient.get: canned (status, headers, body) per path."""

    def __init__(self, pages: dict[str, tuple[int, dict[str, str], bytes]]) -> None:
        self._pages = pages
        self.get_requests = 0
        self.write_requests = 0
        self.paths: list[str] = []

    def get(self, path: str):
        self.get_requests += 1
        self.paths.append(path)
        return self._pages[path]


def _page(status: int, headers: dict[str, str], items: list) -> tuple[int, dict[str, str], bytes]:
    return (status, headers, json.dumps(items).encode("utf-8"))


def _two_page_client() -> FakeClient:
    return FakeClient(
        {
            "/repos/Blummer92/agent-os/issues?state=open&per_page=100&page=1": _page(
                200,
                {
                    "link": '<https://api.github.com/repos/Blummer92/agent-os/issues'
                    '?state=open&per_page=100&page=2>; rel="next"',
                    "x-ratelimit-remaining": "59",
                },
                [{"number": 1}],
            ),
            "/repos/Blummer92/agent-os/issues?state=open&per_page=100&page=2": _page(
                200,
                {"x-ratelimit-remaining": "58"},
                [{"number": 2}],
            ),
        }
    )


def test_live_page_reader_captures_per_page_provenance() -> None:
    log = cli.ScanProvenanceLog()
    reader = cli.LivePageReader(_two_page_client(), log)
    first = reader.read_issue_page("Blummer92/agent-os", page=1, per_page=100, state="open")
    second = reader.read_issue_page("Blummer92/agent-os", page=2, per_page=100, state="open")

    # Scan timestamps bracket the reads.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", log.scan_started_at or "")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", log.scan_ended_at or "")
    assert log.scan_started_at <= log.scan_ended_at

    # The responses themselves carry the provenance fields.
    assert first.page == 1
    assert first.source_query_string == "state=open&per_page=100&page=1"
    assert first.link_next_url == (
        "https://api.github.com/repos/Blummer92/agent-os/issues"
        "?state=open&per_page=100&page=2"
    )
    assert first.rate_limit_remaining == "59"
    assert second.page == 2
    assert second.source_query_string == "state=open&per_page=100&page=2"
    assert second.link_next_url is None
    assert second.rate_limit_remaining == "58"
    assert second.terminal_page_proven is True

    # The reader log mirrors the responses.
    assert len(log.entries) == 2
    logged = log.entries
    assert [entry.page for entry in logged] == [1, 2]
    assert [entry.item_count for entry in logged] == [1, 1]
    assert [entry.next_page for entry in logged] == [2, None]
    assert [entry.source_query_string for entry in logged] == [
        "state=open&per_page=100&page=1",
        "state=open&per_page=100&page=2",
    ]
    assert logged[0].link_next_url == first.link_next_url
    assert logged[1].terminal_page_proven is True


def test_live_page_reader_logs_rate_limited_provenance() -> None:
    client = FakeClient(
        {
            "/repos/Blummer92/agent-os/issues?state=open&per_page=100&page=1": _page(
                403, {"x-ratelimit-remaining": "0"}, []
            ),
        }
    )
    log = cli.ScanProvenanceLog()
    reader = cli.LivePageReader(client, log)
    response = reader.read_issue_page("Blummer92/agent-os", page=1, per_page=100, state="open")
    assert response.error_kind == "rate-limited"
    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.error_kind == "rate-limited"
    assert entry.rate_limit_remaining == "0"
    assert entry.source_query_string == "state=open&per_page=100&page=1"


def test_resolve_mission_id_explicit_wins() -> None:
    assert (
        cli._resolve_mission_id("my-mission", campaign_id="c1", retrieved_at="2026-10-05T16:00:00Z")
        == "my-mission"
    )


def test_resolve_mission_id_derives_deterministically() -> None:
    assert cli._resolve_mission_id(
        None, campaign_id="c1", retrieved_at="2026-10-05T16:00:00Z"
    ) == "shadow-run:c1:2026-10-05T16:00:00Z"


def test_resolve_mission_id_rejects_blank() -> None:
    with pytest.raises(ValueError, match="mission-id"):
        cli._resolve_mission_id("   ", campaign_id="c1", retrieved_at="2026-10-05T16:00:00Z")


def _fail_closed_result() -> ShadowIssueSelectionResult:
    return ShadowIssueSelectionResult(
        repository="Blummer92/agent-os",
        retrieved_at="2026-10-05T14:00:00Z",
        population_issue_numbers=(1, 2, 3, 3082),
        candidate_issue_numbers=(3082,),
        scan_page_count=1,
        scan_item_count=4,
        repository_source_revision=None,
        selection=None,
        selected_issue_number=None,
        selected_issue_revision=None,
        status=ShadowSelectionStatus.NO_SELECTION,
        reason_codes=("shadow-selection.candidate-evidence-incomplete",),
        narrowing_criterion="explicit-request:test-suite",
    )


def test_experiment_record_gains_evidence_ledger_section() -> None:
    client = cli.GitHubReadClient()
    entries = (
        {
            "schema_name": "agent-os-evidence-ledger-entry",
            "mission_id": "shadow-run:campaign-test:2026-10-05T14:00:00Z",
            "decision_type": "selection",
            "entry_digest": "0" * 64,
        },
    )
    record = cli._build_experiment_record(
        repository="Blummer92/agent-os",
        retrieved_at="2026-10-05T14:00:00Z",
        campaign_id="campaign-test",
        result=_fail_closed_result(),
        client=client,
        ledger_entries=entries,
    )
    assert record["evidence_ledger"] == list(entries)
    # The 11 Phase-0 fields are unchanged.
    assert record["population_receipt"]["scan_complete"] is True
    assert record["zero_mutation_verification"]["github_mutations"] == 0


def test_experiment_record_defaults_to_empty_ledger() -> None:
    client = cli.GitHubReadClient()
    record = cli._build_experiment_record(
        repository="Blummer92/agent-os",
        retrieved_at="2026-10-05T14:00:00Z",
        campaign_id="campaign-test",
        result=_fail_closed_result(),
        client=client,
    )
    assert record["evidence_ledger"] == []
