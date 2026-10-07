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
            return 200, {}, json.dumps({"default_branch": "main"}).encode()
        if path == f"/repos/{_REPO}/branches/main":
            return 200, {}, json.dumps({"commit": {"sha": _SHA}}).encode()
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
    # admitted issue then fails closed on #3329's named lifecycle gap.
    selector = record["deterministic_selector_result"]
    assert selector["status"] == "no-selection"
    assert "shadow-selection.candidate-evidence-incomplete" in selector["reason_codes"]
    assert selector["execution_authorized"] is False
    zero = record["zero_mutation_verification"]
    assert zero["http_write_requests"] == 0
    assert zero["github_mutations"] == 0
    (client,) = _FakeLiveClient.instances
    assert client.write_requests == 0
    # #3329's lifecycle fail-closed precedes any per-issue read.
    assert not [p for p in client.paths if "/issues/" in p]
    assert record["stale_or_ambiguous_evidence"] == [
        "candidate-evidence-unavailable:candidate-evidence.no-canonical-lifecycle-stage"
    ]


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
