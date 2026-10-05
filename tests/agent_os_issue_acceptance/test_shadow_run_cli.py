"""Phase 0 (Shadow Admission): focused coverage for scripts/agent-os-shadow-run.py.

Pins the CLI's pure contracts without network access: argument parsing,
the read-only client shape, the #3329 production evidence reader wiring
(Wire-or-Retire disposition of the Phase-0 always-None stub), and the
11-field shadow experiment record.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "agent-os-shadow-run.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("agent_os_shadow_run", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_os_shadow_run"] = module
    spec.loader.exec_module(module)
    return module


cli = _load_cli()

from agent_os_execution_service.shadow_issue_selection import (  # noqa: E402
    ShadowIssueSelectionResult,
    ShadowSelectionStatus,
)


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
        reason_codes=(
            "shadow-selection.candidate-evidence-incomplete",
            "shadow-selection.population-narrowed",
        ),
        narrowing_criterion="explicit-request:test-suite",
    )


def test_parse_issue_list_accepts_sorted_unique_output() -> None:
    assert cli._parse_issue_list("3082, 10, 7", "candidates") == (7, 10, 3082)
    assert cli._parse_issue_list(None, "candidates") is None


def test_parse_issue_list_rejects_bad_input() -> None:
    for bad in ("", "0", "-3", "1,2,2", "abc", "1,,2x"):
        with pytest.raises(ValueError):
            cli._parse_issue_list(bad, "candidates")


def test_read_client_exposes_no_write_method() -> None:
    client = cli.GitHubReadClient()
    for name in ("post", "put", "patch", "delete", "request"):
        assert not hasattr(client, name), f"read-only client must not expose {name}"
    assert client.write_requests == 0


def test_production_reader_wired_fail_closed_with_named_reason() -> None:
    """#3329 Wire-or-Retire: the always-None stub is gone.

    The CLI wires the production ``LiveCandidateEvidenceReader``; with no
    canonical live owners for the required inputs in the shadow-run context,
    it fail-closes with the exact named missing owner instead of
    manufacturing evidence.
    """
    assert not hasattr(cli, "Phase0CandidateEvidenceReader")

    class _NeverCalled:
        def get_issue(self, repository: str, issue_number: int):
            raise AssertionError("fail-closed checks must precede any live read")

    inner = cli.LiveCandidateEvidenceReader(
        cli.LiveCandidateEvidence(
            repository="Blummer92/agent-os",
            issue_transport=_NeverCalled(),
            observed_at="2026-10-05T18:00:00Z",
            source_revision=None,
            lifecycle_stage=None,
            primary_claims=None,
            approval_applicability=None,
            freshness_state=None,
            requested_mode=None,
            environment=None,
            dependency_depth=None,
            substitutable=None,
        )
    )
    reader = cli._RecordingCandidateEvidenceReader(inner)
    assert reader.read_candidate_evidence("Blummer92/agent-os", 3082) is None
    assert (
        reader.first_failure_reason
        == "candidate-evidence.no-canonical-repository-source-revision"
    )


def test_experiment_record_carries_named_evidence_gap_reason() -> None:
    client = cli.GitHubReadClient()
    record = cli._build_experiment_record(
        repository="Blummer92/agent-os",
        retrieved_at="2026-10-05T14:00:00Z",
        campaign_id="campaign-test",
        narrowing_criterion="explicit-request:test-suite",
        result=_fail_closed_result(),
        client=client,
        evidence_gap_reason="candidate-evidence.no-canonical-requested-mode",
    )
    stale = record["stale_or_ambiguous_evidence"]
    assert any(
        "candidate-evidence-unavailable:"
        "candidate-evidence.no-canonical-requested-mode" in item
        for item in stale
    )


def test_experiment_record_carries_all_eleven_fields() -> None:
    client = cli.GitHubReadClient()
    client.get_requests = 2
    record = cli._build_experiment_record(
        repository="Blummer92/agent-os",
        retrieved_at="2026-10-05T14:00:00Z",
        campaign_id="campaign-test",
        narrowing_criterion="explicit-request:test-suite",
        result=_fail_closed_result(),
        client=client,
    )

    # 1. complete population receipt
    assert record["population_receipt"]["scan_complete"] is True
    assert record["population_receipt"]["population_issue_numbers"] == [1, 2, 3, 3082]
    # 2. candidate population considered
    assert record["candidate_population"]["candidate_issue_numbers"] == [3082]
    assert (
        record["candidate_population"]["narrowing_criterion"]
        == "explicit-request:test-suite"
    )
    # 3. excluded candidates and deterministic reasons
    excluded = record["excluded_candidates"]
    assert [item["issue_number"] for item in excluded] == [1, 2, 3]
    assert all(
        item["reason"] == "excluded-by-narrowing:explicit-request:test-suite"
        for item in excluded
    )
    # 4. AI-selected/recommended candidate (operator-filled)
    assert record["ai_recommended_candidate"] is None
    # 5. deterministic selector result
    selector = record["deterministic_selector_result"]
    assert selector["status"] == "no-selection"
    assert selector["selected_issue_number"] is None
    assert selector["execution_authorized"] is False
    assert selector["side_effects_performed"] is False
    # 6-8. human comparison (operator-filled)
    assert record["human_selected_candidate"] is None
    assert record["agreement"] is None
    assert record["disagreement_reason"] is None
    # 9. stale/ambiguous evidence names the evidence gap, not a selection
    # (fallback gap text when no specific named reason is supplied)
    assert any("candidate-evidence-unavailable" in item for item in record["stale_or_ambiguous_evidence"])
    # 10. manual-review cases
    assert len(record["manual_review_cases"]) == 1
    # 11. zero-mutation verification
    zero = record["zero_mutation_verification"]
    assert zero["http_get_requests"] == 2
    assert zero["http_write_requests"] == 0
    assert zero["github_mutations"] == 0
