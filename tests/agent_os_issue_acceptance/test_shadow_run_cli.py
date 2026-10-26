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
    assert record["evidence_ledger"] == control["evidence_ledger"]
    assert record["lifecycle_stage_acquisition"] == control["lifecycle_stage_acquisition"]
    zero = record["zero_mutation_verification"]
    assert zero["http_write_requests"] == 0
    assert zero["github_mutations"] == 0
    (client,) = _FakeLiveClient.instances
    assert client.write_requests == 0
    # No flag means the section is None, exactly like §13's convention.
    assert control["scanner_advisory"] is None


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
    original_read_text = Path.read_text

    def read_text_with_denial(path, *args, **kwargs):
        if path == denied:
            raise OSError("simulated advisory read error")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text_with_denial)
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
    assert record["evidence_ledger"] == control["evidence_ledger"]
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
