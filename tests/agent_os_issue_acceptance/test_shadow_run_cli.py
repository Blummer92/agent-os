"""Phase 0 (Shadow Admission): focused coverage for scripts/agent-os-shadow-run.py.

Pins the CLI's pure contracts without network access: argument parsing,
the read-only client shape, the #3329 production evidence reader wiring
(Wire-or-Retire disposition of the Phase-0 always-None stub), and the
11-field shadow experiment record.
"""

from __future__ import annotations

import importlib.util
import json
import os
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
from agent_os_execution_service.evidence_ledger import (  # noqa: E402
    EvidenceLedgerEntry,
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


# ---------------------------------------------------------------------------
# #3329 real-live composition: actual sources for the previously-None inputs.
# ---------------------------------------------------------------------------

import json


class _FakeGitHubClient:
    """Stub for _fetch_repository_head_sha: canned GET responses, read-only."""

    def __init__(self, responses: dict):
        self._responses = responses
        self.get_requests = 0
        self.write_requests = 0

    def get(self, path: str):
        self.get_requests += 1
        status, body = self._responses[path]
        return status, {}, json.dumps(body).encode("utf-8")


def _repo_responses(sha: str = "a" * 40):
    return {
        "/repos/Blummer92/agent-os": (200, {"default_branch": "main"}),
        "/repos/Blummer92/agent-os/branches/main": (
            200,
            {"commit": {"sha": sha}},
        ),
    }


def test_fetch_repository_head_sha_returns_live_ref() -> None:
    sha = cli._fetch_repository_head_sha(
        _FakeGitHubClient(_repo_responses()), "Blummer92/agent-os"
    )
    assert sha == "a" * 40


def test_fetch_repository_head_sha_fail_closed_on_http_error() -> None:
    responses = {"/repos/Blummer92/agent-os": (404, {"message": "Not Found"})}
    with pytest.raises(RuntimeError, match="repository read failed"):
        cli._fetch_repository_head_sha(
            _FakeGitHubClient(responses), "Blummer92/agent-os"
        )


def test_fetch_repository_head_sha_fail_closed_on_malformed_sha() -> None:
    responses = _repo_responses(sha="not-a-sha")
    with pytest.raises(RuntimeError, match="sha malformed"):
        cli._fetch_repository_head_sha(
            _FakeGitHubClient(responses), "Blummer92/agent-os"
        )


def test_request_context_args_parsed() -> None:
    args = cli._parse_args(
        [
            "--campaign-id",
            "c1",
            "--requested-mode",
            "planning",
            "--dependency-depth",
            "2",
            "--substitutable",
        ]
    )
    assert args.requested_mode == "planning"
    assert args.dependency_depth == 2
    assert args.substitutable is True


def test_request_context_args_absent_stays_absent() -> None:
    args = cli._parse_args(["--campaign-id", "c1"])
    assert args.requested_mode is None
    assert args.dependency_depth is None
    assert args.substitutable is None


def test_no_substitutable_explicit_false() -> None:
    args = cli._parse_args(["--campaign-id", "c1", "--no-substitutable"])
    assert args.substitutable is False


def test_requested_mode_rejects_unknown_choice() -> None:
    with pytest.raises(SystemExit):
        cli._parse_args(["--campaign-id", "c1", "--requested-mode", "turbo"])


def test_shadow_environment_capability_is_honest_read_only() -> None:
    env = cli._shadow_environment_capability()
    assert env.local_execution_state is cli.EnvironmentCapabilityState.UNPROBED
    assert env.push_state is cli.EnvironmentCapabilityState.UNSUPPORTED


def test_wired_composition_advances_past_sourced_inputs_to_lifecycle_blocker() -> None:
    """With real sources wired, the fail-closed gate moves to lifecycle_stage.

    source_revision (live API), freshness (CURRENT: the composition performs
    the live read), environment (honest read-only), and request context are
    now supplied; lifecycle_stage/primary_claims/approval_applicability have
    no canonical live owner (#1460), so the reader names the lifecycle
    blocker -- the bounded #3329 outcome, not manufactured evidence.
    """

    class _NeverCalled:
        def get_issue(self, repository: str, issue_number: int):
            raise AssertionError("fail-closed checks must precede any live read")

    inner = cli.LiveCandidateEvidenceReader(
        cli.LiveCandidateEvidence(
            repository="Blummer92/agent-os",
            issue_transport=_NeverCalled(),
            observed_at="2026-10-05T18:00:00Z",
            source_revision="a" * 40,
            lifecycle_stage=None,
            primary_claims=None,
            approval_applicability=None,
            freshness_state=cli.FreshnessState.CURRENT,
            requested_mode="planning",
            environment=cli._shadow_environment_capability(),
            dependency_depth=0,
            substitutable=False,
        )
    )
    reader = cli._RecordingCandidateEvidenceReader(inner)
    assert reader.read_candidate_evidence("Blummer92/agent-os", 3082) is None
    assert (
        reader.first_failure_reason
        == "candidate-evidence.no-canonical-lifecycle-stage"
    )


# ---------------------------------------------------------------------------
# #3328: the production CLI consumes canonical request/mission cohort
# admission end to end (live scan -> admission -> existing selector -> record).
# ---------------------------------------------------------------------------

_SHA = "c" * 40
_REPO = "Blummer92/agent-os"


def _raw_issue(number: int) -> dict:
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": "open",
        "body": f"body-{number}",
        "html_url": f"https://github.com/{_REPO}/issues/{number}",
        "created_at": "2026-10-07T10:00:00Z",
        "updated_at": "2026-10-07T10:30:00Z",
        "closed_at": None,
        "state_reason": None,
        "labels": [{"name": "agent-os"}],
    }


class _FakeLiveClient:
    """GET-only stand-in for GitHubReadClient over a 2-page, 101-issue backlog."""

    instances: list["_FakeLiveClient"] = []

    def __init__(self) -> None:
        self.get_requests = 0
        self.write_requests = 0
        self.paths: list[str] = []
        _FakeLiveClient.instances.append(self)

    def get(self, path: str):
        self.get_requests += 1
        self.paths.append(path)
        if path == f"/repos/{_REPO}":
            return 200, {}, json.dumps({"default_branch": "main", "id": 4242}).encode()
        if path == f"/repos/{_REPO}/branches/main":
            return 200, {}, json.dumps({"commit": {"sha": _SHA}}).encode()
        if path == f"/repos/{_REPO}/pulls?state=all&per_page=100&page=1":
            # #3441: an empty, single-page all-state pull-request listing.
            return 200, {}, json.dumps([]).encode()
        if path == f"/repos/{_REPO}/issues?state=open&per_page=100&page=1":
            items = [_raw_issue(n) for n in range(1, 101)]
            link = f'<https://api.github.com/repos/{_REPO}/issues?page=2>; rel="next"'
            return 200, {"link": link}, json.dumps(items).encode()
        if path == f"/repos/{_REPO}/issues?state=open&per_page=100&page=2":
            return 200, {}, json.dumps([_raw_issue(101)]).encode()
        if path.startswith(f"/repos/{_REPO}/issues/"):
            number = int(path.rsplit("/", 1)[1])
            return 200, {}, json.dumps(_raw_issue(number)).encode()
        raise AssertionError(f"unexpected GET {path}")


def _request_file(tmp_path: Path, *, kind: str, resource_id: str | None) -> Path:
    payload = {
        "schema_name": "request-interpretation",
        "contract_version": "request-interpretation-v1",
        "record_revision": 1,
        "observed_at": "2026-10-07T11:00:00Z",
        "interpreter_id": "chatgpt-orchestrator",
        "raw_input_digest": "d" * 64,
        "instruction_origin": "direct-user",
        "action": "implement",
        "requested_effect": "mutate",
        "continuation_mode": "new",
        "target": {
            "system": "github",
            "resource_kind": kind,
            "repository": _REPO,
            "resource_id": resource_id,
        },
        "requested_outputs": ["implementation"],
        "constraints": [],
        "reason_codes": [],
        "evidence_references": [],
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_cli(monkeypatch, tmp_path: Path, *extra: str) -> tuple[int, dict | None]:
    _FakeLiveClient.instances.clear()
    monkeypatch.setattr(cli, "GitHubReadClient", _FakeLiveClient)
    output = tmp_path / "record.json"
    code = cli.main(
        [
            "--repository",
            _REPO,
            "--campaign-id",
            "campaign-3328",
            "--retrieved-at",
            "2026-10-07T11:00:00Z",
            "--output",
            str(output),
            *extra,
        ]
    )
    record = json.loads(output.read_text()) if output.exists() else None
    return code, record


def _assert_ledgers_equal_except_recording_time(first, second) -> None:
    """Compare two evidence ledgers across independent CLI runs.

    ``recorded_at`` is wall-clock time at second resolution, and
    ``entry_digest`` binds it, so full ledger equality is timing-flaky
    whenever two runs straddle a second boundary (the #3738 intermittent
    failure: only those two fields differed, inputs_digest identical).
    Exclude only those two run-specific fields from cross-run equality,
    and instead validate each entry's cryptographic digest independently:
    ``EvidenceLedgerEntry.from_dict`` recomputes ``entry_digest`` and
    raises on any mismatch, so a tampered or drifted entry still fails.
    Chain linkage is checked explicitly (genesis ``previous_digest`` is
    empty, each later entry binds its predecessor's ``entry_digest``).
    """
    assert len(first) == len(second)
    for ledger in (first, second):
        previous = ""
        for entry in ledger:
            # Independent digest validation (raises on mismatch).
            EvidenceLedgerEntry.from_dict(entry)
            assert entry["previous_digest"] == previous
            previous = entry["entry_digest"]
    for left, right in zip(first, second):
        assert left["inputs_digest"] == right["inputs_digest"]
        stripped_left = {
            k: v for k, v in left.items() if k not in ("recorded_at", "entry_digest")
        }
        stripped_right = {
            k: v for k, v in right.items() if k not in ("recorded_at", "entry_digest")
        }
        assert stripped_left == stripped_right


def test_cli_consumes_canonical_cohort_admission_end_to_end(monkeypatch, tmp_path) -> None:
    request = _request_file(tmp_path, kind="issue", resource_id="90")
    code, record = _run_cli(monkeypatch, tmp_path, "--request-interpretation", str(request))

    assert code == 0
    admission = record["cohort_admission"]
    assert admission["status"] == "admitted"
    assert admission["candidate_issue_numbers"] == [90]
    assert admission["population_membership_proven"] is True
    assert admission["execution_authorized"] is False
    assert admission["side_effects_performed"] is False
    assert record["population_receipt"]["population_issue_numbers"] == list(range(1, 102))
    assert record["population_receipt"]["scan_page_count"] == 2
    # The record names the canonical criterion actually applied (no CLI flag
    # carries it) and every excluded population member.
    criterion = f"canonical-request:{admission['request_constraint_identity']}"
    assert record["candidate_population"] == {
        "candidate_issue_numbers": [90],
        "narrowing_criterion": criterion,
    }
    assert [item["issue_number"] for item in record["excluded_candidates"]] == [
        n for n in range(1, 102) if n != 90
    ]
    # The existing selector seam is reached; candidate evidence for the one
    # admitted issue then fails closed on the named lifecycle gap: the #3441
    # acquirer found no verified PR lineage, so no stage is established.
    selector = record["deterministic_selector_result"]
    assert selector["status"] == "no-selection"
    assert "shadow-selection.candidate-evidence-incomplete" in selector["reason_codes"]
    assert selector["execution_authorized"] is False
    zero = record["zero_mutation_verification"]
    assert zero["http_write_requests"] == 0
    assert zero["github_mutations"] == 0
    (client,) = _FakeLiveClient.instances
    assert client.write_requests == 0
    # #3441: the lifecycle acquirer is the only per-issue reader on this path.
    # It reads the single admitted candidate and the all-state PR listing.
    assert [p for p in client.paths if "/issues/" in p] == [f"/repos/{_REPO}/issues/90"]
    assert [p for p in client.paths if "/pulls" in p] == [
        f"/repos/{_REPO}/pulls?state=all&per_page=100&page=1"
    ]
    assert record["stale_or_ambiguous_evidence"] == [
        "candidate-evidence-unavailable:candidate-evidence.no-canonical-lifecycle-stage"
    ]
    (acquisition,) = record["lifecycle_stage_acquisition"]["candidates"]
    assert acquisition["issue_number"] == 90
    assert acquisition["reason_codes"] == ["lifecycle-acquisition.no-verified-pr-lineage"]
    assert record["lifecycle_stage_acquisition"]["population"]["complete"] is True


def test_cli_repository_request_over_capacity_fails_closed(monkeypatch, tmp_path) -> None:
    request = _request_file(tmp_path, kind="repository", resource_id=None)
    code, record = _run_cli(monkeypatch, tmp_path, "--request-interpretation", str(request))

    assert code == 0
    admission = record["cohort_admission"]
    assert admission["status"] == "fail-closed"
    assert admission["fail_closed_reason"] == "cohort-admission.candidate-population-too-broad"
    assert admission["candidate_issue_numbers"] == list(range(1, 102))
    selector = record["deterministic_selector_result"]
    assert selector["status"] == "no-selection"
    assert "shadow-selection.cohort-admission-failed" in selector["reason_codes"]
    assert record["manual_review_cases"]
    (client,) = _FakeLiveClient.instances
    assert not [p for p in client.paths if "/issues/" in p]
    assert client.write_requests == 0


def test_cli_ledger_digest_binds_canonical_request(monkeypatch, tmp_path) -> None:
    digests = []
    for target in ("90", "91"):
        request = _request_file(tmp_path, kind="issue", resource_id=target)
        code, record = _run_cli(
            monkeypatch, tmp_path, "--request-interpretation", str(request),
            "--mission-id", "mission-3328",
        )
        assert code == 0
        (entry,) = record["evidence_ledger"]
        digests.append(entry["inputs_digest"])
    assert digests[0] != digests[1]


def test_cli_rejects_request_mixed_with_manual_candidates(monkeypatch, tmp_path) -> None:
    request = _request_file(tmp_path, kind="issue", resource_id="90")
    code, record = _run_cli(
        monkeypatch,
        tmp_path,
        "--request-interpretation",
        str(request),
        "--candidates",
        "90",
        "--narrowing-criterion",
        "explicit-request:x",
    )
    assert code == 2
    assert record is None
    assert _FakeLiveClient.instances == []


def test_cli_rejects_non_canonical_request_record(monkeypatch, tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"target": "issue 90"}), encoding="utf-8")
    code, record = _run_cli(monkeypatch, tmp_path, "--request-interpretation", str(bad))
    assert code == 2
    assert record is None
    assert _FakeLiveClient.instances == []


def test_cli_has_one_scan_path_and_one_selection_authority() -> None:
    """#3328 boundary: the CLI composes; it never admits, ranks, or selects."""
    import ast

    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    calls = [
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    ]
    assert calls.count("select_shadow_issue") == 1
    assert calls.count("LivePageReader") == 1
    assert calls.count("GitHubReadClient") == 1
    # #3441: one lifecycle source, one pull-request listing reader.
    assert calls.count("PrLineageAcquirer") == 1
    assert calls.count("LivePullRequestPageReader") == 1
    # Scanning, cohort admission, and lane selection stay inside the
    # select_shadow_issue seam; the CLI never calls them a second time.
    for forbidden in (
        "admit_request_cohort",
        "select_executable_lanes",
        "scan_connected_issues",
        "scan_issues",
        "scan_open_issues",
    ):
        assert forbidden not in calls


# #3441 D-A1: declared-non-closing-v1 is the CLI default since the owner's
# 2026-10-21 default-activation authorization; closing-directive-v1 remains
# available as an explicit opt-in (back-compat).
def test_association_policy_cli_default_is_declared_non_closing() -> None:
    default = cli._parse_args(["--campaign-id", "default-policy"])
    assert default.association_policy == "declared-non-closing-v1"
    opted = cli._parse_args([
        "--campaign-id", "opted",
        "--association-policy", "declared-non-closing-v1",
    ])
    assert opted.association_policy == "declared-non-closing-v1"
    legacy = cli._parse_args([
        "--campaign-id", "legacy",
        "--association-policy", "closing-directive-v1",
    ])
    assert legacy.association_policy == "closing-directive-v1"
    with pytest.raises(SystemExit):
        cli._parse_args([
            "--campaign-id", "invalid", "--association-policy", "automatic",
        ])


# #3690 CR-4: the library has no default, so the CLI is the only place a
# policy is chosen. Pin that the parsed value (default or explicit) is the
# exact value the one PrLineageAcquirer construction receives.
@pytest.mark.parametrize(
    "flag,expected",
    [
        ((), "declared-non-closing-v1"),
        (("--association-policy", "declared-non-closing-v1"), "declared-non-closing-v1"),
        (("--association-policy", "closing-directive-v1"), "closing-directive-v1"),
    ],
)
def test_cli_forwards_the_parsed_association_policy_to_the_acquirer(
    monkeypatch, tmp_path, flag, expected
) -> None:
    seen = []
    real = cli.PrLineageAcquirer

    def recording(*args, **kwargs):
        seen.append(kwargs.get("association_policy"))
        return real(*args, **kwargs)

    monkeypatch.setattr(cli, "PrLineageAcquirer", recording)
    request = _request_file(tmp_path, kind="issue", resource_id="90")
    code, record = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request), *flag
    )
    assert code == 0
    assert record is not None
    assert seen == [expected]


# ---------------------------------------------------------------------------
# #3429 record-only scanner advisory: producer JSON -> shadow record section.
# Fixtures replicate the exact producer schemas (verified against real
# jscpd/pyan3 outputs regenerated on main d32c9b71: jscpd ok/35 clones,
# pyan ok/126 candidates with candidates_truncated true); the live
# producer-to-CLI run is proven separately in the PR/QA evidence, not by
# making this focused suite depend on npx/pip downloads.
# ---------------------------------------------------------------------------


def _jscpd_artifact(*, head_sha: str, clones: list) -> dict:
    return {
        "schema": "agent-os-jscpd-advisory/1",
        "status": "ok",
        "head_sha": head_sha,
        "tool": "jscpd",
        "version": "4.0.5",
        "scope": [
            "scripts/agent_os_issue_acceptance",
            "08_Tooling/agent-os-execution-service/src",
        ],
        "candidate_count": len(clones),
        "candidates": clones,
        "truncated": False,
    }


def _jscpd_clone() -> dict:
    return {
        "firstFile": {
            "name": "scripts/agent_os_issue_acceptance/merge_admission_actions.py",
            "start": 10,
            "end": 25,
        },
        "secondFile": {
            "name": "scripts/agent_os_issue_acceptance/merge_applicability.py",
            "start": 40,
            "end": 55,
        },
        "format": "python",
        "lines": 16,
        "tokens": 60,
    }


def _pyan_artifact(*, head_sha: str, candidates: list, truncated: bool) -> dict:
    return {
        "schema": "agent-os-pyan3-advisory/1",
        "status": "ok",
        "head_sha": head_sha,
        "tool": "pyan3",
        "version": "2.9.0",
        "scope": [
            "scripts/agent_os_issue_acceptance",
            "08_Tooling/agent-os-execution-service/src",
        ],
        "candidate_count": len(candidates),
        "candidates": candidates,
        "candidates_truncated": truncated,
    }


def _pyan_candidate() -> dict:
    return {
        "id": "scripts.agent_os_issue_acceptance.merge_producer.produce_merge_authorization",
        "kind": "function",
        "file": "scripts/agent_os_issue_acceptance/merge_producer.py",
        "line": 12,
    }


def _write_artifact(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cli_scanner_advisory_section_consumes_producer_output_without_changing_selection(
    monkeypatch, tmp_path
) -> None:
    """#3429 acceptance: scanner findings reach the record; selection is identical.

    Real producer output (regenerated on main, see PR evidence) has the
    same schema, provenance fields, and truncation semantics as these
    fixtures; the fixtures exist so this suite never depends on npx/pip.
    """
    jscpd = _write_artifact(
        tmp_path, "jscpd-advisory.json",
        _jscpd_artifact(head_sha=_SHA, clones=[_jscpd_clone()]),
    )
    pyan = _write_artifact(
        tmp_path, "pyan3-advisory.json",
        _pyan_artifact(head_sha=_SHA, candidates=[_pyan_candidate()], truncated=True),
    )
    request = _request_file(tmp_path, kind="issue", resource_id="90")
    code, record = _run_cli(
        monkeypatch, tmp_path,
        "--request-interpretation", str(request),
        "--scanner-evidence", str(jscpd),
        "--scanner-evidence", str(pyan),
    )
    assert code == 0
    section = record["scanner_advisory"]
    assert section["execution_authorized"] is False
    assert section["side_effects_performed"] is False
    (jscpd_source, pyan_source) = section["sources"]
    # Assert the exact typed provenance contract for both producers.
    for source, expected in (
        (jscpd_source, {
            "tool": "jscpd", "schema": "agent-os-jscpd-advisory/1",
            "version": "4.0.5", "head_sha": _SHA,
            "candidate_count": 1, "truncated": False, "state": "ok",
        }),
        (pyan_source, {
            "tool": "pyan3", "schema": "agent-os-pyan3-advisory/1",
            "version": "2.9.0", "head_sha": _SHA,
            "truncated": True, "state": "ok",
        }),
    ):
        for key, value in expected.items():
            assert type(source[key]) is type(value) and source[key] == value, key
    # Findings intact with original file/line, never selection input.
    (clone,) = jscpd_source["findings"]
    assert clone["kind"] == "textual-clone"
    assert clone["first_file"] == "scripts/agent_os_issue_acceptance/merge_admission_actions.py"
    assert clone["first_start_line"] == 10
    assert clone["second_file"] == "scripts/agent_os_issue_acceptance/merge_applicability.py"
    assert clone["lines"] == 16
    assert clone["selection_input"] is False
    assert "not semantic equivalence" in clone["note"]
    (candidate,) = pyan_source["findings"]
    assert candidate["kind"] == "potentially-disconnected"
    assert candidate["function"] == "scripts.agent_os_issue_acceptance.merge_producer.produce_merge_authorization"
    assert candidate["file"] == "scripts/agent_os_issue_acceptance/merge_producer.py"
    assert candidate["line"] == 12
    assert candidate["selection_input"] is False
    assert "not proof of runtime unreachability" in candidate["note"]
    # Selection is identical to a control run without --scanner-evidence:
    # still fail-closed on the missing primary-claim/approval inputs, no
    # SELECTED, and the ledger inputs digest is unchanged (the section is
    # not a ledger input).
    _, control = _run_cli(monkeypatch, tmp_path, "--request-interpretation", str(request))
    assert record["deterministic_selector_result"] == control["deterministic_selector_result"]
    assert record["deterministic_selector_result"]["status"] == "no-selection"
    assert "shadow-selection.candidate-evidence-incomplete" in record["deterministic_selector_result"]["reason_codes"]
    assert record["candidate_population"] == control["candidate_population"]
    _assert_ledgers_equal_except_recording_time(
        record["evidence_ledger"], control["evidence_ledger"]
    )
    assert record["lifecycle_stage_acquisition"] == control["lifecycle_stage_acquisition"]
    zero = record["zero_mutation_verification"]
    assert zero["http_write_requests"] == 0
    assert zero["github_mutations"] == 0
    (client,) = _FakeLiveClient.instances
    assert client.write_requests == 0
    # No flag means the section is None, exactly like §13's convention.
    assert control["scanner_advisory"] is None


def test_cli_evidence_ledger_comparison_survives_recording_second_boundary(
    monkeypatch, tmp_path
) -> None:
    """#3738 regression: ledger comparison survives different recording seconds.

    Forces the two runs onto different wall-clock seconds via a controlled
    clock, so the old full-equality assertion deterministically fails
    (recorded_at and its derived entry_digest differ) while the repaired
    comparison passes: inputs_digest unchanged, every other field equal,
    and each entry's digest independently valid.
    """
    import datetime as _real_datetime

    class _ControlledDateTime(_real_datetime.datetime):
        current = _real_datetime.datetime(
            2026, 10, 27, 12, 0, 0, tzinfo=_real_datetime.timezone.utc
        )

        @classmethod
        def now(cls, tz=None):
            return cls.current

    class _FakeDatetimeModule:
        datetime = _ControlledDateTime
        timezone = _real_datetime.timezone

    monkeypatch.setattr(cli, "_datetime", _FakeDatetimeModule)
    jscpd = _write_artifact(
        tmp_path,
        "jscpd-advisory.json",
        _jscpd_artifact(head_sha=_SHA, clones=[_jscpd_clone()]),
    )
    pyan = _write_artifact(
        tmp_path,
        "pyan3-advisory.json",
        _pyan_artifact(head_sha=_SHA, candidates=[_pyan_candidate()], truncated=True),
    )
    request = _request_file(tmp_path, kind="issue", resource_id="90")
    args = (
        "--request-interpretation",
        str(request),
        "--scanner-evidence",
        str(jscpd),
        "--scanner-evidence",
        str(pyan),
    )
    _ControlledDateTime.current = _real_datetime.datetime(
        2026, 10, 27, 12, 0, 0, tzinfo=_real_datetime.timezone.utc
    )
    code, record = _run_cli(monkeypatch, tmp_path, *args)
    assert code == 0
    _ControlledDateTime.current = _real_datetime.datetime(
        2026, 10, 27, 12, 0, 1, tzinfo=_real_datetime.timezone.utc
    )
    _, control = _run_cli(monkeypatch, tmp_path, "--request-interpretation", str(request))
    # The boundary was actually exercised: these two fields differ.
    (entry,) = record["evidence_ledger"]
    (control_entry,) = control["evidence_ledger"]
    assert entry["recorded_at"] != control_entry["recorded_at"]
    assert entry["entry_digest"] != control_entry["entry_digest"]
    # Old assertion fails deterministically under the forced boundary.
    assert record["evidence_ledger"] != control["evidence_ledger"]
    # Repaired comparison passes without weakening the ledger contract.
    _assert_ledgers_equal_except_recording_time(
        record["evidence_ledger"], control["evidence_ledger"]
    )
    assert record["deterministic_selector_result"] == control["deterministic_selector_result"]



def test_cli_scanner_review_groups_are_deterministic_and_non_authorizing(
    monkeypatch, tmp_path
) -> None:
    """Same-line overlap groups review pointers, never source findings or selection."""
    clone = _jscpd_clone()
    matching = {
        "id": "example.registered_entrypoint",
        "kind": "function",
        "file": "scripts/agent_os_issue_acceptance/merge_admission_actions.py",
        "line": 12,
    }
    unrelated = {
        "id": "example.unrelated_public_api",
        "kind": "function",
        "file": "scripts/agent_os_issue_acceptance/merge_admission_actions.py",
        "line": 200,
    }
    jscpd = _write_artifact(
        tmp_path, "review-jscpd.json",
        _jscpd_artifact(head_sha=_SHA, clones=[clone, clone]),
    )
    pyan = _write_artifact(
        tmp_path, "review-pyan.json",
        _pyan_artifact(head_sha=_SHA, candidates=[matching, unrelated], truncated=False),
    )
    request = _request_file(tmp_path, kind="issue", resource_id="90")
    args = (
        "--request-interpretation", str(request),
        "--scanner-evidence", str(jscpd),
        "--scanner-evidence", str(pyan),
    )
    code, record = _run_cli(monkeypatch, tmp_path, *args)
    assert code == 0
    advisory = record["scanner_advisory"]
    assert [len(s["findings"]) for s in advisory["sources"]] == [2, 2]
    groups = advisory["review_groups"]
    assert len(groups) == 2
    overlap = next(g for g in groups if len(g["finding_refs"]) == 3)
    assert overlap["finding_refs"] == [
        {"source_index": 0, "finding_index": 0},
        {"source_index": 0, "finding_index": 1},
        {"source_index": 1, "finding_index": 0},
    ]
    for group in groups:
        assert group["issue_linkage"] == {
            "status": "unlinked",
            "issue_number": None,
            "reason": "scanner-findings-do-not-prove-canonical-issue-identity",
        }
        assert group["engineering_review"] == "manual-review"
        assert group["selection_input"] is False
        assert group["execution_authorized"] is False
        assert group["side_effects_performed"] is False
    _, repeat = _run_cli(monkeypatch, tmp_path, *args)
    assert repeat["scanner_advisory"]["review_groups"] == groups
    _, control = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request)
    )
    assert record["deterministic_selector_result"] == control["deterministic_selector_result"]
    _assert_ledgers_equal_except_recording_time(
        record["evidence_ledger"], control["evidence_ledger"]
    )
    assert record["candidate_population"] == control["candidate_population"]
    assert record["zero_mutation_verification"]["github_mutations"] == 0


def test_cli_scanner_review_groups_do_not_merge_stale_with_current(
    monkeypatch, tmp_path
) -> None:
    """Identical spans from different revisions cannot become one current claim."""
    clone = _jscpd_clone()
    stale = _write_artifact(
        tmp_path, "review-stale.json",
        _jscpd_artifact(head_sha="a" * 40, clones=[clone]),
    )
    current = _write_artifact(
        tmp_path, "review-current.json",
        _jscpd_artifact(head_sha=_SHA, clones=[clone]),
    )
    request = _request_file(tmp_path, kind="issue", resource_id="90")
    code, record = _run_cli(
        monkeypatch, tmp_path,
        "--request-interpretation", str(request),
        "--scanner-evidence", str(stale),
        "--scanner-evidence", str(current),
    )
    assert code == 0
    groups = record["scanner_advisory"]["review_groups"]
    assert len(groups) == 2
    assert sorted(g["states"] for g in groups) == [["ok"], ["stale"]]
    assert all(len(g["finding_refs"]) == 1 for g in groups)


def test_cli_scanner_advisory_stale_error_unavailable_and_zero_states(
    monkeypatch, tmp_path
) -> None:
    request = _request_file(tmp_path, kind="issue", resource_id="90")

    stale = _write_artifact(
        tmp_path, "stale.json",
        _jscpd_artifact(head_sha="a" * 40, clones=[_jscpd_clone()]),
    )
    code, record = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request),
        "--scanner-evidence", str(stale),
    )
    assert code == 0
    (source,) = record["scanner_advisory"]["sources"]
    assert source["state"] == "stale"
    assert source["head_sha"] == "a" * 40
    assert len(source["findings"]) == 1  # kept, marked stale, never current
    assert record["deterministic_selector_result"]["status"] == "no-selection"

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "unknown/9", "tool": "jscpd"}), encoding="utf-8")
    code, record = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request),
        "--scanner-evidence", str(bad),
    )
    assert code == 0
    (source,) = record["scanner_advisory"]["sources"]
    assert source["state"] == "scanner-error"
    assert source["findings"] == []
    assert record["deterministic_selector_result"]["status"] == "no-selection"

    code, record = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request),
        "--scanner-evidence", str(tmp_path / "missing.json"),
    )
    assert code == 0
    (source,) = record["scanner_advisory"]["sources"]
    assert source["state"] == "unavailable"
    assert source["findings"] == []
    assert record["deterministic_selector_result"]["status"] == "no-selection"

    empty = _write_artifact(
        tmp_path, "empty.json", _pyan_artifact(head_sha=_SHA, candidates=[], truncated=False),
    )
    code, record = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request),
        "--scanner-evidence", str(empty),
    )
    assert code == 0
    (source,) = record["scanner_advisory"]["sources"]
    assert source["state"] == "ok-zero-findings"  # distinct from unavailable/error


def test_cli_scanner_advisory_out_of_scope_findings_are_annotated_not_hidden(
    monkeypatch, tmp_path
) -> None:
    """#3736 guard: Notion files are outside producer scope, so a finding
    there must read as out-of-scope, never as 'no findings' for that package."""
    pyan = _write_artifact(
        tmp_path, "pyan3-advisory.json",
        _pyan_artifact(
            head_sha=_SHA,
            candidates=[{
                "id": "scripts.agent_os_notion_read_request.binding_verification.inspect",
                "kind": "function",
                "file": "scripts/agent_os_notion_read_request/binding_verification.py",
                "line": 100,
            }],
            truncated=False,
        ),
    )
    request = _request_file(tmp_path, kind="issue", resource_id="90")
    code, record = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request),
        "--scanner-evidence", str(pyan),
    )
    assert code == 0
    (source,) = record["scanner_advisory"]["sources"]
    assert source["state"] == "ok"
    (finding,) = source["findings"]
    assert finding["out_of_scope"] is True
    assert source["out_of_scope_findings"] == 1



def test_cli_scanner_producer_error_is_nonfatal_and_non_authorizing(monkeypatch, tmp_path) -> None:
    artifact = _jscpd_artifact(head_sha=_SHA, clones=[_jscpd_clone()])
    artifact["status"] = "scanner-error"
    path = _write_artifact(tmp_path, "producer-error.json", artifact)
    request = _request_file(tmp_path, kind="issue", resource_id="90")
    code, record = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request),
        "--scanner-evidence", str(path),
    )
    assert code == 0
    (source,) = record["scanner_advisory"]["sources"]
    assert source["status"] == "scanner-error"
    assert source["state"] == "scanner-error"
    assert source["findings"] == []
    assert source["selection_input"] is False
    assert source["execution_authorized"] is False
    assert record["deterministic_selector_result"]["status"] == "no-selection"


def test_cli_scanner_bad_json_and_io_errors_preserve_failure_detail(
    monkeypatch, tmp_path
) -> None:
    request = _request_file(tmp_path, kind="issue", resource_id="90")
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    denied = tmp_path / "denied.json"
    denied.write_text("{}", encoding="utf-8")
    original_read_bytes = Path.read_bytes

    def read_bytes_with_denial(path, *args, **kwargs):
        if path == denied:
            raise OSError("simulated advisory read error")
        return original_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_bytes_with_denial)
    code, record = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request),
        "--scanner-evidence", str(malformed),
        "--scanner-evidence", str(denied),
    )
    assert code == 0
    bad_json, io_error = record["scanner_advisory"]["sources"]
    for source in (bad_json, io_error):
        assert source["state"] == source["status"] == "scanner-error"
        assert source["findings"] == []
        assert source["failure_detail"]
    assert "JSONDecodeError" in bad_json["failure_detail"]
    assert "OSError: simulated advisory read error" in io_error["failure_detail"]
    _, control = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request)
    )
    assert record["deterministic_selector_result"] == control["deterministic_selector_result"]
    _assert_ledgers_equal_except_recording_time(
        record["evidence_ledger"], control["evidence_ledger"]
    )
    assert record["zero_mutation_verification"]["http_write_requests"] == 0
    assert record["zero_mutation_verification"]["github_mutations"] == 0


def test_shadow_workflow_supplies_same_checkout_scanners_and_shows_advisories() -> None:
    """Structural wiring guard; live Actions consumption is verified separately."""
    import yaml

    flow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/agent-os-shadow-navigation.yml").read_text()
    )
    steps = flow["jobs"]["shadow-navigation"]["steps"]
    produce = next(i for i, step in enumerate(steps)
                   if step.get("name") == "Generate same-revision scanner advisories")
    consume = next(i for i, step in enumerate(steps)
                   if step.get("name") == "Run Agent OS shadow navigation")
    assert produce < consume
    producer = steps[produce]["run"]
    assert 'git rev-parse HEAD' in producer
    assert 'scripts.jscpd_advisory' in producer
    assert 'scripts.pyan3_advisory' in producer
    assert '--sha "$source_sha"' in producer
    with_args = steps[consume]["with"]
    action = yaml.safe_load(
        (REPO_ROOT / ".github/actions/agent-os-shadow-navigation/action.yml").read_text()
    )
    for name in ("scanner_evidence_jscpd", "scanner_evidence_pyan3"):
        assert name in with_args
        assert name in action["inputs"]
        assert "--scanner-evidence" in action["runs"]["steps"][0]["run"]
    summary = next(step for step in steps
                   if step.get("name") == "Publish shadow-navigation summary")
    assert 'report.get("scanner_advisory")' in summary["run"]
    assert 'source["state"]' in summary["run"]


def test_scanner_advisory_loader_rejects_unsupported_schema() -> None:
    with pytest.raises(ValueError, match="unsupported schema/tool"):
        cli._normalize_scanner_advisory(
            {"schema": "agent-os-jscpd-advisory/9", "tool": "jscpd"},
            source_revision=_SHA,
        )


def test_cli_scanner_adversarial_values_are_excluded_or_sanitized() -> None:
    """#3429 repair: untrusted artifact values can never reach a record.

    Numeric scope entries are dropped (previously they crashed the
    workflow summary join); absolute, traversal, and drive paths are
    excluded from findings (not merely annotated); credential-like and
    control-character content in display fields is redacted/flattened;
    non-integer line values become None instead of published verbatim.
    """
    artifact = _pyan_artifact(
        head_sha=_SHA,
        candidates=[
            _pyan_candidate(),
            {"id": "abs.fn", "kind": "function",
             "file": "/home/runner/.ssh/id_rsa", "line": 1},
            {"id": "esc.fn", "kind": "function",
             "file": "../escape.py", "line": 2},
            {"id": "win.fn", "kind": "function",
             "file": "C:\\Users\\runner\\secret.py", "line": 3},
            {"id": "badline.fn", "kind": "function",
             "file": "scripts/agent_os_issue_acceptance/a.py", "line": "12; x"},
        ],
        truncated=False,
    )
    artifact["scope"] = [123, "scripts/agent_os_issue_acceptance", "/etc", "../escape"]
    artifact["version"] = "2.9.0\r\n| token=abc123secret"
    source = cli._normalize_scanner_advisory(artifact, source_revision=_SHA)
    assert source["scope"] == ["scripts/agent_os_issue_acceptance"]
    assert ", ".join(source["scope"]) == "scripts/agent_os_issue_acceptance"
    assert [f["file"] for f in source["findings"]] == [
        "scripts/agent_os_issue_acceptance/merge_producer.py",
        "scripts/agent_os_issue_acceptance/a.py",
    ]
    assert source["excluded_findings"] == 3
    assert source["state"] == "ok"
    assert "\r" not in source["version"] and "\n" not in source["version"]
    assert "abc123secret" not in source["version"]
    assert source["findings"][1]["line"] is None
    assert source["selection_input"] is False
    assert source["execution_authorized"] is False
    assert source["side_effects_performed"] is False

    clone_artifact = _jscpd_artifact(head_sha=_SHA, clones=[_jscpd_clone()])
    clone_artifact["candidates"][0]["firstFile"]["name"] = "/tmp/host.py"
    clone_source = cli._normalize_scanner_advisory(
        clone_artifact, source_revision=_SHA
    )
    assert clone_source["findings"] == []
    assert clone_source["excluded_findings"] == 1


def test_cli_scanner_oversized_input_and_candidate_truncation_are_bounded(
    monkeypatch, tmp_path
) -> None:
    """#3429 repair: oversized artifacts fail advisory-only; candidate
    lists truncate deterministically to the configured limit while the
    original count and truncation state stay truthful."""
    many = [
        {"id": f"mod.fn{i}", "kind": "function",
         "file": "scripts/agent_os_issue_acceptance/a.py", "line": i}
        for i in range(150)
    ]
    source = cli._normalize_scanner_advisory(
        _pyan_artifact(head_sha=_SHA, candidates=many, truncated=False),
        source_revision=_SHA,
    )
    assert len(source["findings"]) == cli.SCANNER_ADVISORY_MAX_FINDINGS
    assert source["truncated"] is True
    assert source["candidate_count"] == 150

    lying = _pyan_artifact(head_sha=_SHA, candidates=many[:2], truncated=False)
    lying["candidate_count"] = 999999
    lying_source = cli._normalize_scanner_advisory(lying, source_revision=_SHA)
    assert lying_source["truncated"] is True
    assert lying_source["candidate_count"] == 999999

    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * (cli.SCANNER_ADVISORY_MAX_BYTES + 10), encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds size limit"):
        cli._load_scanner_advisory(str(oversized), source_revision=_SHA)

    request = _request_file(tmp_path, kind="issue", resource_id="90")
    code, record = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request),
        "--scanner-evidence", str(oversized),
    )
    assert code == 0
    (oversized_source,) = record["scanner_advisory"]["sources"]
    assert oversized_source["state"] == oversized_source["status"] == "scanner-error"
    assert oversized_source["findings"] == []
    assert record["deterministic_selector_result"]["status"] == "no-selection"


def test_cli_scanner_failure_details_exclude_host_paths_and_secrets(
    monkeypatch, tmp_path
) -> None:
    """#3429 repair: failure details carry type + redacted detail only;
    absolute host paths and credential-like fragments never publish."""
    detail = cli._safe_failure_detail(
        OSError(13, "Permission denied", "/home/runner/token.json")
    )
    assert "/home/runner" not in detail
    assert "[path]" in detail
    secret_detail = cli._safe_failure_detail(
        ValueError("token=abc123secret and ghp_1234567890abcdefghij")
    )
    assert "abc123secret" not in secret_detail
    assert "ghp_1234567890abcdefghij" not in secret_detail

    request = _request_file(tmp_path, kind="issue", resource_id="90")
    denied = tmp_path / "denied.json"
    denied.write_text("{}", encoding="utf-8")
    original_read_bytes = Path.read_bytes

    def read_bytes_with_denial(path, *args, **kwargs):
        if path == denied:
            raise OSError(13, "Permission denied", "/home/runner/secret.json")
        return original_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_bytes_with_denial)
    code, record = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request),
        "--scanner-evidence", str(denied),
    )
    assert code == 0
    (source,) = record["scanner_advisory"]["sources"]
    assert source["state"] == "scanner-error"
    assert "/home/runner" not in source["failure_detail"]
    assert source["selection_input"] is False


def test_shadow_summary_renders_adversarial_advisory_safely(monkeypatch, tmp_path) -> None:
    """#3429 repair: the published summary renders loader-sanitized
    advisory evidence safely, under either the current or the hardened
    summary cell.

    The adversarial values below pass through the production loader
    first (the production path); the summary then renders them. This
    deliberately does NOT feed a raw unsanitized record to the snippet:
    the hardened cell (defense in depth for raw records) lives in the
    workflow file, which the GitHub App cannot publish via API, so it
    is pending owner publication and is not asserted here.
    """
    import subprocess
    import sys

    import yaml

    flow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/agent-os-shadow-navigation.yml").read_text()
    )
    steps = flow["jobs"]["shadow-navigation"]["steps"]
    summary = next(step for step in steps
                   if step.get("name") == "Publish shadow-navigation summary")
    run = summary["run"]
    script = run[run.index("python - <<'PY'") + len("python - <<'PY'\n"):]
    script = script[: script.rfind("\nPY")]
    hostile = _pyan_artifact(head_sha=_SHA, candidates=[], truncated=False)
    hostile["scope"] = [123, "scripts/agent_os_issue_acceptance"]
    hostile["version"] = "1.0\r## injected heading"
    source = cli._normalize_scanner_advisory(hostile, source_revision=_SHA)
    source["status"] = "scanner-error"
    source["state"] = "scanner-error"
    source["failure_detail"] = cli._safe_failure_detail(
        OSError(13, "Permission denied", "/home/runner/token.json")
    )
    source["failure_detail"] += " token=abc123secret"
    # The loader-sanitized detail above is re-sanitized exactly as the
    # production path does before publication:
    source["failure_detail"] = cli._safe_failure_detail(
        ValueError(source["failure_detail"])
    )
    report = {
        "repository": "Blummer92/agent-os",
        "campaign_id": "test",
        "population_receipt": {"scan_complete": True, "scan_item_count": 1,
                               "scan_page_count": 1},
        "candidate_population": {"candidate_issue_numbers": []},
        "deterministic_selector_result": {"status": "no-selection",
                                          "selected_issue_number": None,
                                          "reason_codes": []},
        "manual_review_cases": [],
        "zero_mutation_verification": {"http_write_requests": 0,
                                       "github_mutations": 0},
        "scanner_advisory": {"sources": [source]},
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    summary_path = tmp_path / "summary.md"
    summary_path.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "SHADOW_REPORT": str(report_path),
        "GITHUB_STEP_SUMMARY": str(summary_path),
        "SHADOW_RUN_URL": "https://example.invalid/runs/1",
        "PYTHONPATH": str(REPO_ROOT),
    })
    script_path = tmp_path / "summary_snippet.py"
    script_path.write_text(script, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(script_path)], env=env,
                          capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, proc.stderr
    rendered = summary_path.read_text(encoding="utf-8")
    assert "\r" not in rendered
    assert "/home/runner" not in rendered
    assert "abc123secret" not in rendered
    assert "scripts/agent_os_issue_acceptance" in rendered
    assert not any(line.startswith("## injected") for line in rendered.splitlines())
    assert "### Scanner advisory" in rendered


def test_cli_scanner_hostile_status_cannot_forge_summary_lines(tmp_path) -> None:
    """QA catch: `status` used to publish verbatim into the record and
    the workflow summary, so a crafted status carrying CR could forge
    markdown lines. Status now gets the same display sanitization as
    version/head_sha, and a sanitized non-ok status renders
    scanner-error, never ok."""
    artifact = _pyan_artifact(head_sha=_SHA, candidates=[], truncated=False)
    artifact["status"] = "scanner-error\r## FORGED LINE | x"
    source = cli._normalize_scanner_advisory(artifact, source_revision=_SHA)
    assert "\r" not in source["status"] and "\n" not in source["status"]
    assert source["status"].startswith("scanner-error")
    assert source["status"] == "scanner-error ## FORGED LINE | x"
    assert source["state"] == "scanner-error"

    clean = _pyan_artifact(head_sha=_SHA, candidates=[], truncated=False)
    clean["status"] = "ok"
    assert cli._normalize_scanner_advisory(
        clean, source_revision=_SHA
    )["state"] == "ok-zero-findings"

    # Snippet-level proof: render the loader-produced hostile-status
    # record through the live workflow snippet and inspect raw bytes,
    # since text-mode reads translate CR away and would mask the defect.
    import subprocess
    import sys

    import yaml

    flow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/agent-os-shadow-navigation.yml").read_text()
    )
    steps = flow["jobs"]["shadow-navigation"]["steps"]
    summary = next(step for step in steps
                   if step.get("name") == "Publish shadow-navigation summary")
    run = summary["run"]
    script = run[run.index("python - <<'PY'") + len("python - <<'PY'\n"):]
    script = script[: script.rfind("\nPY")]
    report = {
        "repository": "Blummer92/agent-os",
        "campaign_id": "test",
        "population_receipt": {"scan_complete": True, "scan_item_count": 1,
                               "scan_page_count": 1},
        "candidate_population": {"candidate_issue_numbers": []},
        "deterministic_selector_result": {"status": "no-selection",
                                          "selected_issue_number": None,
                                          "reason_codes": []},
        "manual_review_cases": [],
        "zero_mutation_verification": {"http_write_requests": 0,
                                       "github_mutations": 0},
        "scanner_advisory": {"sources": [source]},
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    summary_path = tmp_path / "summary.md"
    summary_path.write_bytes(b"")
    env = dict(os.environ)
    env.update({
        "SHADOW_REPORT": str(report_path),
        "GITHUB_STEP_SUMMARY": str(summary_path),
        "SHADOW_RUN_URL": "https://example.invalid/runs/1",
        "PYTHONPATH": str(REPO_ROOT),
    })
    script_path = tmp_path / "summary_snippet.py"
    script_path.write_text(script, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(script_path)], env=env,
                          capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, proc.stderr
    raw = summary_path.read_bytes()
    assert b"\r" not in raw
    assert not any(
        line.startswith(b"## FORGED")
        for line in raw.split(b"\n")
    )


def test_cli_scanner_deeply_nested_json_is_scanner_error(
    monkeypatch, tmp_path
) -> None:
    """D8: a deeply nested artifact under the byte cap must not escape
    advisory handling. The JSON parser raises RecursionError on it;
    _load converts that to the existing ValueError mechanism, so main()
    records scanner-error and the run still succeeds with selection,
    ledger, and zero-mutation outputs unchanged."""
    request = _request_file(tmp_path, kind="issue", resource_id="90")
    nested = tmp_path / "nested.json"
    nested.write_text("[" * 12000 + "]" * 12000, encoding="utf-8")
    assert nested.stat().st_size < cli.SCANNER_ADVISORY_MAX_BYTES
    with pytest.raises(ValueError, match="nesting limit"):
        cli._load_scanner_advisory(str(nested), source_revision=_SHA)
    code, record = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request),
        "--scanner-evidence", str(nested),
    )
    assert code == 0
    (source,) = record["scanner_advisory"]["sources"]
    assert source["state"] == source["status"] == "scanner-error"
    assert source["findings"] == []
    assert "ValueError" in source["failure_detail"]
    _, control = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request)
    )
    assert record["deterministic_selector_result"] == control["deterministic_selector_result"]
    _assert_ledgers_equal_except_recording_time(
        record["evidence_ledger"], control["evidence_ledger"]
    )
    assert record["zero_mutation_verification"]["http_write_requests"] == 0
    assert record["zero_mutation_verification"]["github_mutations"] == 0


def test_cli_scanner_provenance_paths_cannot_be_published(
    monkeypatch, tmp_path
) -> None:
    """D9: head_sha is validated against the producer SHA contract
    (full lowercase 40-hex, or the producers' "unavailable" fallback);
    free-text provenance fields redact absolute host paths instead of
    publishing them. Verified in the normalized JSON and through the
    actual published workflow-summary renderer."""
    # Valid provenance passes unchanged, including the producers'
    # "unavailable" fallback (which can never equal a live revision,
    # so it renders stale, never current).
    valid = cli._normalize_scanner_advisory(
        _pyan_artifact(head_sha=_SHA, candidates=[], truncated=False),
        source_revision=_SHA,
    )
    assert valid["head_sha"] == _SHA
    assert valid["state"] == "ok-zero-findings"
    fallback = cli._normalize_scanner_advisory(
        _pyan_artifact(head_sha="unavailable", candidates=[], truncated=False),
        source_revision=_SHA,
    )
    assert fallback["head_sha"] == "unavailable"
    assert fallback["state"] == "stale"
    # Invalid SHAs carrying host paths are rejected, not published.
    for bad_sha in (
        "/home/runner/private-tenant/config.json",
        "C:\\Users\\tenant\\config.json",
    ):
        with pytest.raises(ValueError, match="invalid head SHA"):
            cli._normalize_scanner_advisory(
                _pyan_artifact(head_sha=bad_sha, candidates=[], truncated=False),
                source_revision=_SHA,
            )
    # Versions carrying host paths are redacted to a placeholder;
    # normal producer versions pass through untouched.
    for hostile_version in (
        "/home/runner/private-tenant/config.json",
        "C:\\Users\\tenant\\config.json",
    ):
        source = cli._normalize_scanner_advisory(
            _pyan_artifact(
                head_sha=_SHA, candidates=[], truncated=False,
            ) | {"version": hostile_version},
            source_revision=_SHA,
        )
        assert source["version"] == "[path]"
        assert "/home/runner" not in json.dumps(source)
        assert "private-tenant" not in json.dumps(source)
        assert "C:\\Users" not in json.dumps(source)
    assert cli._normalize_scanner_advisory(
        _jscpd_artifact(head_sha=_SHA, clones=[]), source_revision=_SHA
    )["version"] == "4.0.5"
    assert cli._normalize_scanner_advisory(
        _pyan_artifact(head_sha=_SHA, candidates=[], truncated=False),
        source_revision=_SHA,
    )["version"] == "2.9.0"

    # Published-summary proof: render the redacted record through the
    # live workflow snippet and inspect raw bytes.
    import subprocess
    import sys

    import yaml

    flow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/agent-os-shadow-navigation.yml").read_text()
    )
    steps = flow["jobs"]["shadow-navigation"]["steps"]
    summary = next(step for step in steps
                   if step.get("name") == "Publish shadow-navigation summary")
    run = summary["run"]
    script = run[run.index("python - <<'PY'") + len("python - <<'PY'\n"):]
    script = script[: script.rfind("\nPY")]
    hostile_source = cli._normalize_scanner_advisory(
        _pyan_artifact(head_sha=_SHA, candidates=[], truncated=False)
        | {"version": "/home/runner/private-tenant/config.json"},
        source_revision=_SHA,
    )
    report = {
        "repository": "Blummer92/agent-os",
        "campaign_id": "test",
        "population_receipt": {"scan_complete": True, "scan_item_count": 1,
                               "scan_page_count": 1},
        "candidate_population": {"candidate_issue_numbers": []},
        "deterministic_selector_result": {"status": "no-selection",
                                          "selected_issue_number": None,
                                          "reason_codes": []},
        "manual_review_cases": [],
        "zero_mutation_verification": {"http_write_requests": 0,
                                       "github_mutations": 0},
        "scanner_advisory": {"sources": [hostile_source]},
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    summary_path = tmp_path / "summary.md"
    summary_path.write_bytes(b"")
    env = dict(os.environ)
    env.update({
        "SHADOW_REPORT": str(report_path),
        "GITHUB_STEP_SUMMARY": str(summary_path),
        "SHADOW_RUN_URL": "https://example.invalid/runs/1",
        "PYTHONPATH": str(REPO_ROOT),
    })
    script_path = tmp_path / "summary_snippet.py"
    script_path.write_text(script, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(script_path)], env=env,
                          capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, proc.stderr
    raw = summary_path.read_bytes()
    assert b"/home/runner" not in raw
    assert b"private-tenant" not in raw


def test_cli_scanner_oversized_scope_entries_are_bounded() -> None:
    """Long-scope hardening: a single repository-relative scope entry
    far beyond any legitimate repo path is dropped, while legitimate
    entries (including one exactly at the cap) still pass, so the
    published summary join cannot be inflated by one entry."""
    legit = "scripts/agent_os_issue_acceptance"
    at_cap = "d/" + "a" * 510
    over_cap = "d/" + "a" * 511
    assert len(at_cap) == 512 and len(over_cap) == 513
    source = cli._normalize_scanner_advisory(
        _pyan_artifact(head_sha=_SHA, candidates=[], truncated=False)
        | {"scope": [legit, "x" * 70000, at_cap, over_cap]},
        source_revision=_SHA,
    )
    assert source["scope"] == [legit, at_cap]
    assert len(", ".join(source["scope"])) < 1000


def _review_source(*, head_sha: str | None, state: str | None, findings: list) -> dict:
    return {
        "head_sha": head_sha,
        "state": state,
        "truncated": False,
        "findings": findings,
    }


def _pyan_finding(*, file: str | None, line, out_of_scope: bool = False) -> dict:
    return {
        "kind": "potentially-disconnected",
        "file": file,
        "line": line,
        "out_of_scope": out_of_scope,
    }


def test_cli_scanner_review_groups_geometry_is_exact() -> None:
    """Grouping geometry, pinned at the unit level so each rule has
    exactly one witness: overlap groups, adjacency does not,
    boundary-touching does, transitive chains collapse, and file,
    SHA, and state boundaries are never crossed."""
    sha_a, sha_b = "a" * 40, "b" * 40

    def groups_for(*sources: dict) -> list:
        return cli._scanner_review_groups(list(sources))

    def span(start: int, end: int) -> dict:
        return {
            "kind": "textual-clone",
            "first_file": "a.py", "first_start_line": start, "first_end_line": end,
            "second_file": "a.py", "second_start_line": start, "second_end_line": end,
        }

    assert len(groups_for(_review_source(
        head_sha=sha_a, state="ok",
        findings=[span(10, 20), span(15, 25)],
    ))) == 1
    assert len(groups_for(_review_source(
        head_sha=sha_a, state="ok",
        findings=[span(10, 20), span(21, 30)],
    ))) == 2
    assert len(groups_for(_review_source(
        head_sha=sha_a, state="ok",
        findings=[span(10, 20), span(20, 30)],
    ))) == 1
    transitive = groups_for(_review_source(
        head_sha=sha_a, state="ok",
        findings=[span(10, 20), span(18, 28), span(26, 36)],
    ))
    assert len(transitive) == 1
    assert len(transitive[0]["finding_refs"]) == 3
    assert len(groups_for(_review_source(
        head_sha=sha_a, state="ok",
        findings=[span(10, 20),
                  {**span(10, 20), "first_file": "b.py",
                   "second_file": "b.py"}],
    ))) == 2
    assert len(groups_for(
        _review_source(head_sha=sha_a, state="ok",
                       findings=[span(10, 20)]),
        _review_source(head_sha=sha_b, state="ok",
                       findings=[span(10, 20)]),
    )) == 2
    assert len(groups_for(
        _review_source(head_sha=sha_a, state="stale",
                       findings=[span(10, 20)]),
        _review_source(head_sha=sha_a, state="ok",
                       findings=[span(10, 20)]),
    )) == 2
    # Determinism: the same input regroups byte-identically.
    repeated = _review_source(
        head_sha=sha_a, state="ok",
        findings=[span(10, 20), span(18, 28), span(26, 36)],
    )
    assert groups_for(repeated) == groups_for(repeated)


def test_cli_scanner_review_groups_keep_unlocatable_findings_separate() -> None:
    """Invalid or missing locations never invent an overlap: each
    unlocatable finding is its own review group, explicitly unlinked
    and manual-review, and a locatable finding never absorbs one."""
    source = _review_source(
        head_sha="a" * 40, state="ok",
        findings=[
            _pyan_finding(file=None, line=5),
            _pyan_finding(file="a.py", line="not-a-line"),
            {"kind": "unknown", "file": "a.py", "line": 5},
            {"kind": "textual-clone",
             "first_file": "a.py", "first_start_line": 20, "first_end_line": 10,
             "second_file": "a.py", "second_start_line": 20, "second_end_line": 10},
            _pyan_finding(file="a.py", line=0),
            _pyan_finding(file="a.py", line=12),
        ],
    )
    groups = cli._scanner_review_groups([source])
    assert len(groups) == 6
    unlocatable = [g for g in groups if g["locations"] == []]
    assert len(unlocatable) == 5
    assert all(len(g["finding_refs"]) == 1 for g in unlocatable)
    for group in groups:
        assert group["issue_linkage"]["status"] == "unlinked"
        assert group["engineering_review"] == "manual-review"
        assert group["selection_input"] is False


def test_cli_scanner_review_groups_ignore_failed_sources_but_keep_entrypoint_manual(
    monkeypatch, tmp_path
) -> None:
    """Scanner failures, missing artifacts, and truncation states stay
    distinguishable in sources while contributing no review groups;
    a dynamic/public entrypoint in a valid source is grouped only as a
    manual-review pointer, never as safe to delete."""
    valid = _write_artifact(
        tmp_path, "review-valid.json",
        _pyan_artifact(head_sha=_SHA, candidates=[
            {"id": "example.registered_entrypoint", "kind": "function",
             "file": "scripts/agent_os_issue_acceptance/merge_admission_actions.py",
             "line": 12},
        ], truncated=True),
    )
    bad = tmp_path / "review-bad.json"
    bad.write_text(json.dumps({"schema": "unknown/9", "tool": "pyan3"}), encoding="utf-8")
    missing = tmp_path / "review-missing.json"
    request = _request_file(tmp_path, kind="issue", resource_id="90")
    code, record = _run_cli(
        monkeypatch, tmp_path, "--request-interpretation", str(request),
        "--scanner-evidence", str(valid),
        "--scanner-evidence", str(bad),
        "--scanner-evidence", str(missing),
    )
    assert code == 0
    sources = record["scanner_advisory"]["sources"]
    assert [s["state"] for s in sources] == ["ok", "scanner-error", "unavailable"]
    groups = record["scanner_advisory"]["review_groups"]
    assert len(groups) == 1
    assert groups[0]["finding_refs"] == [{"source_index": 0, "finding_index": 0}]
    assert groups[0]["truncated"] is True
    assert groups[0]["engineering_review"] == "manual-review"
    assert groups[0]["retirement_review_owner"] == "#1729"
    assert groups[0]["selection_input"] is False
    assert groups[0]["execution_authorized"] is False
    assert groups[0]["side_effects_performed"] is False
    assert "safe" not in json.dumps(groups)
    assert "delet" not in json.dumps(groups).lower()
