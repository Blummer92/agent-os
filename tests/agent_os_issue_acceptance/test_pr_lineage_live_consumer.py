"""#3441 production-consumer coverage for the PR-lineage reader.

Proves the reader is reached by the real consumers, not hand-fed to the
evaluator: ``LiveCandidateEvidenceReader`` (per-issue acquisition, revalidation
at the consumer boundary) and ``scripts/agent-os-shadow-run.py`` ``main()``
(live-shaped GET-only client -> population -> acquirer -> evaluator -> record).
Everything is offline fixture evidence; it is not a live-GitHub verification.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from scripts.agent_os_candidate_packet.stage_models import (
    DependencyEvidence,
    EvidenceStatus,
    ValidationEvidence,
)
from scripts.agent_os_candidate_packet_live_input import (
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)
from scripts.agent_os_issue_acceptance.approval_records import ApprovalApplicabilityResult
from scripts.agent_os_issue_acceptance.github_issue_source import GitHubIssuePageResponse
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    FreshnessState,
    LifecycleStage,
)
from scripts.agent_os_issue_acceptance.lifecycle_stage_acquisition import (
    ASSOCIATION_POLICY_CLOSING_DIRECTIVE_V1,
    LifecycleAcquisitionOutcome,
)
from scripts.agent_os_issue_acceptance.live_candidate_evidence_reader import (
    REASON_COMPOSITION_CONTRACT_VIOLATION,
    REASON_LIFECYCLE_STAGE_STALE,
    REASON_MISSING_LIFECYCLE_STAGE,
    REASON_MISSING_PRIMARY_CLAIMS,
    LiveCandidateEvidence,
    LiveCandidateEvidenceReader,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    EnvironmentCapabilityEvidence,
    EnvironmentCapabilityState,
)
from scripts.agent_os_issue_acceptance.pr_lineage_reader import (
    LifecycleStageAcquisitionAttempt,
    PrLineageAcquirer,
    PullRequestDetailOutcome,
    PullRequestDetailResult,
)

REPO = "Blummer92/agent-os"
ISSUE = 3441
SHA = "a" * 40
OTHER_SHA = "d" * 40
OBSERVED = "2026-10-13T20:00:00Z"
REPO_ID = 4242


# --------------------------------------------------------------------------
# shared fixtures
# --------------------------------------------------------------------------
def head(n: int) -> str:
    return f"{n:040x}"


def pr_rest(number, *, state="open", draft=False, merged=False, body=None, sha=None):
    return {
        "number": number,
        "state": state,
        "draft": draft,
        "merged_at": "2026-10-12T10:00:00Z" if merged else None,
        "title": f"PR {number}",
        "body": f"Closes #{ISSUE}\n" if body is None else body,
        "head": {"sha": sha or head(number), "ref": f"agent/{number}-work"},
        "base": {"repo": {"full_name": REPO}},
    }


def issue_rest(number=ISSUE, *, body="body", state="open"):
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "body": body,
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "created_at": "2026-10-08T16:13:39Z",
        "updated_at": "2026-10-11T15:56:33Z",
        "closed_at": None if state == "open" else "2026-10-12T00:00:00Z",
        "state_reason": None if state == "open" else "completed",
        "labels": [{"name": "agent-os"}],
    }


class ListPages:
    def __init__(self, items, per_page=100):
        self.items, self.per_page, self.calls = list(items), per_page, []

    def read_pull_request_page(self, repository, *, page, per_page, state):
        self.calls.append(page)
        chunk = self.items[(page - 1) * self.per_page : page * self.per_page]
        more = page * self.per_page < len(self.items)
        return GitHubIssuePageResponse(
            items=tuple(copy.deepcopy(chunk)),
            next_page=page + 1 if more else None,
            complete=True,
            terminal_page_proven=not more,
            page=page,
        )


class Details:
    def __init__(self, items):
        self.items = {item["number"]: item for item in items}

    def read_pull_request(self, repository, number):
        return PullRequestDetailResult(
            PullRequestDetailOutcome.OK, copy.deepcopy(self.items[number])
        )


@dataclass
class SequencedIssues:
    """Issue transport whose body can change between reads (revision drift)."""

    bodies: list[str] = field(default_factory=lambda: ["body"])
    state: str = "open"
    calls: int = 0

    def get_issue(self, repository, issue_number):
        body = self.bodies[min(self.calls, len(self.bodies) - 1)]
        self.calls += 1
        return SingleIssueTransportResult(
            outcome=SingleIssueTransportOutcome.OK,
            item=issue_rest(issue_number, body=body, state=self.state),
        )


class Main:
    def __init__(self, *shas):
        self.shas, self.calls = list(shas), 0

    def __call__(self):
        value = self.shas[min(self.calls, len(self.shas) - 1)]
        self.calls += 1
        return value


def blocked_approval():
    return ApprovalApplicabilityResult(
        status="blocked", approval_id=None, approval_revision=None,
        current_proposal_id=None, reason_codes=(), changed_bindings=(),
        approval_applicable=False, details=("approval-record:absent",),
    )


class ClearEvidence:
    def read_dependency_evidence(self, repository, issue_number):
        return DependencyEvidence(status=EvidenceStatus.RESOLVED_CLEAR)

    def read_validation_evidence(self, repository, issue_number):
        return ValidationEvidence(status=EvidenceStatus.RESOLVED_CLEAR)


def make_pair(prs, *, issues=None, main=None, bundle_overrides=None):
    issues = issues or SequencedIssues()
    acquirer = PrLineageAcquirer(
        repository=REPO,
        issue_transport=issues,
        page_reader=ListPages(prs),
        detail_reader=Details(prs),
        source_revision_reader=main or Main(SHA),
        observed_at=OBSERVED,
        association_policy=ASSOCIATION_POLICY_CLOSING_DIRECTIVE_V1,
    )
    kwargs = dict(
        repository=REPO,
        issue_transport=issues,
        observed_at=OBSERVED,
        source_revision=SHA,
        lifecycle_stage=None,
        lifecycle_stage_acquirer=acquirer,
        primary_claims=(),
        approval_applicability=blocked_approval(),
        freshness_state=FreshnessState.CURRENT,
        requested_mode="planning",
        environment=EnvironmentCapabilityEvidence(
            local_execution_state=EnvironmentCapabilityState.NOT_VERIFIED,
            push_state=EnvironmentCapabilityState.NOT_VERIFIED,
        ),
        dependency_depth=0,
        substitutable=False,
        dependency_reader=ClearEvidence(),
    )
    kwargs.update(bundle_overrides or {})
    return LiveCandidateEvidenceReader(LiveCandidateEvidence(**kwargs)), acquirer, issues


# --------------------------------------------------------------------------
# reader-level: LiveCandidateEvidenceReader consumes the acquirer
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("pr", "stage"),
    [
        (pr_rest(20, draft=True), LifecycleStage.DRAFT_PR),
        (pr_rest(20), LifecycleStage.REVIEW),
        (pr_rest(20, state="closed", merged=True), LifecycleStage.MERGED),
    ],
)
def test_reader_composes_evidence_with_the_acquired_stage(pr, stage) -> None:
    reader, acquirer, issues = make_pair([pr])
    outcome = reader.read_candidate_evidence_detailed(REPO, ISSUE)
    assert outcome.failure_reason is None, outcome
    state = outcome.evidence.operational_state
    assert state.lifecycle_stage is stage
    assert state.source_revision == SHA
    # One read for the acquisition, one fresh snapshot read for the revalidation.
    assert issues.calls == 2
    (observation,) = acquirer.observations
    assert observation["lifecycle_stage"] == stage.value
    assert observation["issue_source_revision"] in state.evidence_ids


def test_reader_acquires_a_closed_issue_stage_without_lineage_reads() -> None:
    issues = SequencedIssues(state="closed")
    reader, acquirer, _ = make_pair([pr_rest(20)], issues=issues)
    outcome = reader.read_candidate_evidence_detailed(REPO, ISSUE)
    assert outcome.evidence.operational_state.lifecycle_stage is LifecycleStage.CLOSED
    assert acquirer.population_summary is None


@pytest.mark.parametrize(
    ("prs", "expected_detail"),
    [
        ([], "lifecycle-acquisition.no-verified-pr-lineage"),
        ([pr_rest(20), pr_rest(21)], "lifecycle-acquisition.conflicting-pr-claims"),
        ([pr_rest(20), pr_rest(21, body=f"Refs #{ISSUE}")],
         "lifecycle-acquisition.pr-linkage-unverifiable"),
        ([pr_rest(20, state="closed")], "lifecycle-acquisition.closed-unmerged-pr"),
    ],
)
def test_unestablished_stage_fails_closed_with_the_named_reason_and_detail(
    prs, expected_detail
) -> None:
    reader, _, _ = make_pair(prs)
    outcome = reader.read_candidate_evidence_detailed(REPO, ISSUE)
    assert outcome.evidence is None
    assert outcome.failure_reason == REASON_MISSING_LIFECYCLE_STAGE
    assert expected_detail in outcome.failure_detail
    assert reader.read_candidate_evidence(REPO, ISSUE) is None


def test_acquirer_failure_is_surfaced_in_the_detail() -> None:
    issues = SequencedIssues()
    issues.get_issue = lambda repository, number: SingleIssueTransportResult(
        outcome=SingleIssueTransportOutcome.NOT_FOUND
    )
    reader, _, _ = make_pair([], issues=issues)
    outcome = reader.read_candidate_evidence_detailed(REPO, ISSUE)
    assert outcome.failure_reason == REASON_MISSING_LIFECYCLE_STAGE
    assert "pr-lineage.issue-read-failed" in outcome.failure_detail


def test_issue_revision_drift_between_acquisition_and_snapshot_fails_closed() -> None:
    issues = SequencedIssues(bodies=["body at acquisition", "body edited since"])
    reader, _, _ = make_pair([pr_rest(20)], issues=issues)
    outcome = reader.read_candidate_evidence_detailed(REPO, ISSUE)
    assert outcome.evidence is None
    assert outcome.failure_reason == REASON_LIFECYCLE_STAGE_STALE
    assert "issue revision" in outcome.failure_detail


def test_repository_sha_drift_between_acquisition_and_reader_fails_closed() -> None:
    reader, _, _ = make_pair([pr_rest(20)], main=Main(OTHER_SHA))
    outcome = reader.read_candidate_evidence_detailed(REPO, ISSUE)
    assert outcome.failure_reason == REASON_LIFECYCLE_STAGE_STALE


def test_stage_alone_never_completes_evidence_when_claims_remain_unresolved() -> None:
    reader, acquirer, issues = make_pair([pr_rest(20)], bundle_overrides={"primary_claims": None})
    outcome = reader.read_candidate_evidence_detailed(REPO, ISSUE)
    assert outcome.evidence is None
    assert outcome.failure_reason == REASON_MISSING_PRIMARY_CLAIMS
    # The acquisition ran (canonical order) and is visible, but selected nothing.
    assert issues.calls == 1
    assert acquirer.observations[0]["outcome"] == LifecycleAcquisitionOutcome.ACQUIRED.value


def test_approval_applicability_remains_a_separate_unresolved_gate() -> None:
    reader, _, _ = make_pair(
        [pr_rest(20)], bundle_overrides={"approval_applicability": None}
    )
    outcome = reader.read_candidate_evidence_detailed(REPO, ISSUE)
    assert outcome.failure_reason == "candidate-evidence.no-canonical-approval-applicability"


def test_acquirer_and_static_stage_are_mutually_exclusive() -> None:
    with pytest.raises(TypeError, match="mutually exclusive"):
        make_pair([], bundle_overrides={"lifecycle_stage": LifecycleStage.IMPLEMENTATION})


def test_acquirer_must_provide_the_acquisition_method() -> None:
    with pytest.raises(TypeError, match="acquire_lifecycle_stage"):
        make_pair([], bundle_overrides={"lifecycle_stage_acquirer": object()})


def test_wrong_acquirer_return_type_is_a_contract_violation() -> None:
    class Bad:
        def acquire_lifecycle_stage(self, repository, issue_number):
            return "stage"

    reader, _, _ = make_pair([], bundle_overrides={"lifecycle_stage_acquirer": Bad()})
    outcome = reader.read_candidate_evidence_detailed(REPO, ISSUE)
    assert outcome.failure_reason == REASON_COMPOSITION_CONTRACT_VIOLATION


def test_acquirer_value_error_is_a_contract_violation_not_a_crash() -> None:
    class Raises:
        def acquire_lifecycle_stage(self, repository, issue_number):
            raise ValueError("bad evidence")

    reader, _, _ = make_pair([], bundle_overrides={"lifecycle_stage_acquirer": Raises()})
    outcome = reader.read_candidate_evidence_detailed(REPO, ISSUE)
    assert outcome.failure_reason == REASON_COMPOSITION_CONTRACT_VIOLATION
    assert "bad evidence" in outcome.failure_detail


def test_acquisition_for_a_different_issue_is_rejected_at_the_consumer_boundary() -> None:
    reader, acquirer, _ = make_pair([pr_rest(20)])
    genuine = acquirer.acquire_lifecycle_stage(REPO, ISSUE)

    class Wrong:
        def acquire_lifecycle_stage(self, repository, issue_number):
            return LifecycleStageAcquisitionAttempt(result=genuine.result)

    reader, _, _ = make_pair([pr_rest(20)], bundle_overrides={"lifecycle_stage_acquirer": Wrong()})
    outcome = reader.read_candidate_evidence_detailed(REPO, 9999)
    assert outcome.evidence is None
    assert outcome.failure_reason == REASON_COMPOSITION_CONTRACT_VIOLATION
    assert "identity" in outcome.failure_detail


def test_static_stage_path_is_unchanged_and_never_touches_an_acquirer() -> None:
    reader, _, issues = make_pair(
        [], bundle_overrides={
            "lifecycle_stage": LifecycleStage.IMPLEMENTATION,
            "lifecycle_stage_acquirer": None,
        },
    )
    outcome = reader.read_candidate_evidence_detailed(REPO, ISSUE)
    assert outcome.evidence is not None
    assert issues.calls == 1


# --------------------------------------------------------------------------
# CLI-level: scripts/agent-os-shadow-run.py main() reaches the acquirer
# --------------------------------------------------------------------------
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "agent-os-shadow-run.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("agent_os_shadow_run_3441", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_os_shadow_run_3441"] = module
    spec.loader.exec_module(module)
    return module


cli = _load_cli()


class ScenarioClient:
    """GET-only stand-in for ``GitHubReadClient`` serving a live-shaped repository."""

    def __init__(self, *, prs=(), open_issues=(ISSUE,), branch_shas=(SHA,), page_size=100,
                 fail_pr_page=None, link_override=None, rate_limit_page=None):
        self.prs = list(prs)
        self.open_issues = list(open_issues)
        self.branch_shas = list(branch_shas)
        self.page_size = page_size
        self.fail_pr_page = fail_pr_page
        self.link_override = link_override
        self.rate_limit_page = rate_limit_page
        self.get_requests = 0
        self.write_requests = 0
        self.paths: list[str] = []
        self._branch_reads = 0

    def get(self, path):
        self.get_requests += 1
        self.paths.append(path)
        base = f"/repos/{REPO}"
        if path == base:
            return 200, {}, json.dumps({"default_branch": "main", "id": REPO_ID}).encode()
        if path == f"{base}/branches/main":
            sha = self.branch_shas[min(self._branch_reads, len(self.branch_shas) - 1)]
            self._branch_reads += 1
            return 200, {}, json.dumps({"commit": {"sha": sha}}).encode()
        if path == f"{base}/issues?state=open&per_page=100&page=1":
            return 200, {}, json.dumps([issue_rest(n) for n in self.open_issues]).encode()
        if path.startswith(f"{base}/issues/"):
            number = int(path.rsplit("/", 1)[1])
            return 200, {}, json.dumps(issue_rest(number)).encode()
        if path.startswith(f"{base}/pulls?"):
            page = int(path.rsplit("page=", 1)[1])
            if page == self.rate_limit_page:
                return 403, {"x-ratelimit-remaining": "0"}, b"{}"
            if page == self.fail_pr_page:
                return 500, {}, b"{}"
            chunk = self.prs[(page - 1) * self.page_size : page * self.page_size]
            headers = {}
            links = []
            if page * self.page_size < len(self.prs):
                links.append(
                    f'<https://api.github.com/repositories/{REPO_ID}/pulls?state=all'
                    f'&per_page={self.page_size}&page={page + 1}>; rel="next"'
                )
            if page > 1:
                links.append(
                    f'<https://api.github.com/repositories/{REPO_ID}/pulls?state=all'
                    f'&per_page={self.page_size}&page=1>; rel="first"'
                )
            if self.link_override is not None and page == 1:
                links = [self.link_override]
            if links:
                headers["link"] = ", ".join(links)
            return 200, headers, json.dumps(chunk).encode()
        if path.startswith(f"{base}/pulls/"):
            number = int(path.rsplit("/", 1)[1])
            for item in self.prs:
                if item["number"] == number:
                    return 200, {}, json.dumps(item).encode()
            return 404, {}, b"{}"
        raise AssertionError(f"unexpected GET {path}")


def run_cli(monkeypatch, tmp_path, client, *extra):
    monkeypatch.setattr(cli, "GitHubReadClient", lambda: client)
    output = tmp_path / "record.json"
    code = cli.main(
        [
            "--repository", REPO,
            "--campaign-id", "campaign-3441",
            "--retrieved-at", OBSERVED,
            "--candidates", str(ISSUE),
            "--narrowing-criterion", "explicit-request:test-3441",
            "--output", str(output),
            *extra,
        ]
    )
    return code, json.loads(output.read_text())


def lifecycle(record):
    return record["lifecycle_stage_acquisition"]


def assert_read_only_and_non_selecting(client, record):
    assert client.write_requests == 0
    zero = record["zero_mutation_verification"]
    assert zero["http_write_requests"] == 0 and zero["github_mutations"] == 0
    selector = record["deterministic_selector_result"]
    assert selector["status"] == "no-selection"
    assert selector["execution_authorized"] is False
    assert selector["side_effects_performed"] is False
    assert lifecycle(record)["execution_authorized"] is False
    assert lifecycle(record)["side_effects_performed"] is False


def test_cli_invokes_the_real_acquisition_path_and_records_the_acquired_stage(
    monkeypatch, tmp_path
) -> None:
    client = ScenarioClient(prs=[pr_rest(20, draft=True), pr_rest(21, body="Closes #4000")])
    code, record = run_cli(monkeypatch, tmp_path, client)

    assert code == 0
    (candidate,) = lifecycle(record)["candidates"]
    assert candidate["issue_number"] == ISSUE
    assert candidate["outcome"] == "acquired"
    assert candidate["lifecycle_stage"] == "draft-pr"
    assert candidate["verified_claims"] == [20]
    assert candidate["lineage"]["claims"] == [20]
    population = lifecycle(record)["population"]
    assert population["complete"] is True and population["page_count"] == 1
    # The reads that happened are exactly the governed ones: the candidate issue,
    # the all-state listing, and the exact re-read of the one referencing PR.
    assert [p for p in client.paths if "/pulls" in p] == [
        f"/repos/{REPO}/pulls?state=all&per_page=100&page=1",
        f"/repos/{REPO}/pulls/20",
    ]
    assert [p for p in client.paths if "/issues/" in p] == [f"/repos/{REPO}/issues/{ISSUE}"]
    # A stage alone selects nothing: primary claims and approval stay unresolved.
    assert record["stale_or_ambiguous_evidence"] == [
        "candidate-evidence-unavailable:candidate-evidence.no-canonical-primary-claims"
    ]
    assert "unresolved" in lifecycle(record)["primary_claims"]
    assert "unresolved" in lifecycle(record)["approval_applicability"]
    assert_read_only_and_non_selecting(client, record)


def test_cli_candidate_without_pr_lineage_stays_unavailable(monkeypatch, tmp_path) -> None:
    client = ScenarioClient(prs=[pr_rest(21, body="Closes #4000")])
    code, record = run_cli(monkeypatch, tmp_path, client)
    assert code == 0
    (candidate,) = lifecycle(record)["candidates"]
    assert candidate["outcome"] == "unavailable"
    assert candidate["reason_codes"] == ["lifecycle-acquisition.no-verified-pr-lineage"]
    assert record["stale_or_ambiguous_evidence"] == [
        "candidate-evidence-unavailable:candidate-evidence.no-canonical-lifecycle-stage"
    ]
    assert_read_only_and_non_selecting(client, record)


def test_cli_conflicting_claims_are_manual_review_not_a_unique_primary(
    monkeypatch, tmp_path
) -> None:
    client = ScenarioClient(prs=[pr_rest(20), pr_rest(21)])
    _, record = run_cli(monkeypatch, tmp_path, client)
    (candidate,) = lifecycle(record)["candidates"]
    assert candidate["outcome"] == "manual-review"
    assert candidate["reason_codes"] == ["lifecycle-acquisition.conflicting-pr-claims"]
    assert candidate["verified_claims"] == [20, 21]
    assert_read_only_and_non_selecting(client, record)


def test_cli_multi_page_population_with_numeric_repository_links_is_proven(
    monkeypatch, tmp_path
) -> None:
    prs = [pr_rest(n, body=f"Closes #{n + 5000}") for n in range(1, 251)]
    prs.append(pr_rest(300, draft=True))
    client = ScenarioClient(prs=prs, page_size=100)
    # per_page is fixed at 100 by the CLI; 251 PRs therefore span three pages.
    _, record = run_cli(monkeypatch, tmp_path, client)
    population = lifecycle(record)["population"]
    assert population["complete"] is True
    assert population["page_count"] == 3 and population["pull_request_count"] == 251
    assert population["pages"][-1]["terminal_page_proven"] is True
    assert population["pages"][0]["link_next_url"].startswith("https://api.github.com/repositories/")
    assert lifecycle(record)["candidates"][0]["lifecycle_stage"] == "draft-pr"


def test_cli_failed_pull_request_page_fails_closed(monkeypatch, tmp_path) -> None:
    prs = [pr_rest(n, body=f"Closes #{n + 5000}") for n in range(1, 151)]
    client = ScenarioClient(prs=prs, fail_pr_page=2)
    code, record = run_cli(monkeypatch, tmp_path, client)
    assert code == 0
    population = lifecycle(record)["population"]
    assert population["complete"] is False
    assert population["reason_codes"] == ["pr-lineage.page-read-failed"]
    (candidate,) = lifecycle(record)["candidates"]
    assert candidate["reason_codes"] == ["lifecycle-acquisition.incomplete-enumeration"]
    assert candidate["lifecycle_stage"] is None
    assert_read_only_and_non_selecting(client, record)


def test_cli_rate_limited_page_fails_closed(monkeypatch, tmp_path) -> None:
    client = ScenarioClient(prs=[pr_rest(20)], rate_limit_page=1)
    _, record = run_cli(monkeypatch, tmp_path, client)
    population = lifecycle(record)["population"]
    assert population["complete"] is False
    assert "rate-limited" in population["note"]
    assert_read_only_and_non_selecting(client, record)


_TRUSTED_NEXT = (
    f'<https://api.github.com/repositories/{REPO_ID}/pulls?state=all&per_page=100&page=2>; rel="next"'
)


def test_cli_trusted_continuation_link_on_page_one_is_accepted(monkeypatch, tmp_path) -> None:
    # Control for the rejections below: the same page-1 override, well formed,
    # is followed to an empty terminal page 2 and proves the population.
    client = ScenarioClient(prs=[pr_rest(20, draft=True)], link_override=_TRUSTED_NEXT)
    _, record = run_cli(monkeypatch, tmp_path, client)
    population = lifecycle(record)["population"]
    assert population["complete"] is True and population["page_count"] == 2
    assert lifecycle(record)["candidates"][0]["lifecycle_stage"] == "draft-pr"


@pytest.mark.parametrize(
    "link, kind",
    [
        # continuation that changes the endpoint, repository, host, or page arithmetic
        (_TRUSTED_NEXT.replace("/pulls?", "/issues?"), "pagination:next-path"),
        (_TRUSTED_NEXT.replace(f"/repositories/{REPO_ID}/", "/repositories/999/"), "pagination:next-path"),
        (_TRUSTED_NEXT.replace("https://api.github.com", "https://evil.example"), "pagination:next-host"),
        (_TRUSTED_NEXT.replace("&page=2>", "&page=5>"), "pagination:next-page-non-contiguous"),
    ],
    ids=["wrong-endpoint", "other-repository-id", "other-host", "non-contiguous"],
)
def test_cli_untrusted_continuation_link_fails_closed(monkeypatch, tmp_path, link, kind) -> None:
    client = ScenarioClient(prs=[pr_rest(20)], link_override=link)
    _, record = run_cli(monkeypatch, tmp_path, client)
    population = lifecycle(record)["population"]
    assert population["complete"] is False
    assert population["reason_codes"] == ["pr-lineage.page-read-failed"]
    assert population["note"] == f"page 1: malformed-response (pull-request page 1: {kind})"
    assert lifecycle(record)["candidates"][0]["lifecycle_stage"] is None
    assert_read_only_and_non_selecting(client, record)


@pytest.mark.parametrize(
    "link, proven",
    [
        (f'<https://api.github.com/repositories/{REPO_ID}/pulls?state=all&per_page=100&page=5>; rel="last"', False),
        (f'<https://api.github.com/repositories/{REPO_ID}/pulls?state=all&per_page=100&page=x>; rel="last"', False),
        (f'<https://api.github.com/repositories/{REPO_ID}/pulls?state=all&per_page=100>; rel="last"', False),
        (f'<https://api.github.com/repositories/{REPO_ID}/pulls?state=all&per_page=100&page=1>; rel="last"', True),
        (f'<https://api.github.com/repositories/{REPO_ID}/pulls?state=all&per_page=100&page=1>; rel="first"', True),
    ],
    ids=["last-beyond", "last-unreadable", "last-without-page", "last-is-this-page", "no-last"],
)
def test_cli_a_last_relation_naming_another_page_is_not_terminal_proof(
    monkeypatch, tmp_path, link, proven
) -> None:
    client = ScenarioClient(prs=[pr_rest(20, draft=True)], link_override=link)
    _, record = run_cli(monkeypatch, tmp_path, client)
    population = lifecycle(record)["population"]
    assert population["pages"][0]["terminal_page_proven"] is proven
    assert population["complete"] is proven
    if not proven:
        assert population["reason_codes"] == ["pr-lineage.pagination-unproven"]
        assert lifecycle(record)["candidates"][0]["lifecycle_stage"] is None
    assert_read_only_and_non_selecting(client, record)


def test_cli_record_says_the_consumer_boundary_revalidation_was_not_reached(
    monkeypatch, tmp_path
) -> None:
    _, record = run_cli(monkeypatch, tmp_path, ScenarioClient(prs=[pr_rest(20, draft=True)]))
    assert lifecycle(record)["consumer_boundary_revalidation"].startswith("not-reached:")
    assert record["stale_or_ambiguous_evidence"] == [
        "candidate-evidence-unavailable:candidate-evidence.no-canonical-primary-claims"
    ]


def test_cli_default_branch_moving_during_the_run_fails_closed(monkeypatch, tmp_path) -> None:
    # start-of-run read, acquirer read, post-listing read: main moves before the last.
    client = ScenarioClient(prs=[pr_rest(20)], branch_shas=(SHA, SHA, OTHER_SHA))
    _, record = run_cli(monkeypatch, tmp_path, client)
    population = lifecycle(record)["population"]
    assert population["complete"] is False
    assert population["reason_codes"] == ["pr-lineage.default-branch-moved"]
    assert lifecycle(record)["candidates"][0]["lifecycle_stage"] is None
    assert_read_only_and_non_selecting(client, record)


def test_cli_pull_request_changed_between_listing_and_exact_read_fails_closed(
    monkeypatch, tmp_path
) -> None:
    client = ScenarioClient(prs=[pr_rest(20, draft=True)])
    original_get = client.get

    def drifting_get(path):
        status, headers, body = original_get(path)
        if path == f"/repos/{REPO}/pulls/20":
            item = json.loads(body)
            item["head"]["sha"] = head(777)
            body = json.dumps(item).encode()
        return status, headers, body

    client.get = drifting_get
    _, record = run_cli(monkeypatch, tmp_path, client)
    (candidate,) = lifecycle(record)["candidates"]
    assert candidate["reason_codes"] == ["lifecycle-acquisition.incomplete-enumeration"]
    assert "list-detail-disagreement" in candidate["lineage"]["enumeration_note"]
    assert_read_only_and_non_selecting(client, record)


def test_cli_ledger_digest_binds_the_lifecycle_acquisition(monkeypatch, tmp_path) -> None:
    digests = []
    for prs in ([pr_rest(20, draft=True)], [pr_rest(20)]):
        _, record = run_cli(
            monkeypatch, tmp_path, ScenarioClient(prs=prs), "--mission-id", "mission-3441"
        )
        (entry,) = record["evidence_ledger"]
        digests.append(entry["inputs_digest"])
    assert digests[0] != digests[1]


def test_cli_wiring_keeps_unresolved_owners_none_and_builds_one_acquirer() -> None:
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    names = [node.func.id for node in calls]
    assert names.count("PrLineageAcquirer") == 1
    assert names.count("LivePullRequestPageReader") == 1
    assert names.count("select_shadow_issue") == 1
    (bundle,) = [node for node in calls if node.func.id == "LiveCandidateEvidence"]
    keywords = {kw.arg: kw.value for kw in bundle.keywords}
    for unresolved in ("lifecycle_stage", "primary_claims", "approval_applicability"):
        assert isinstance(keywords[unresolved], ast.Constant) and keywords[unresolved].value is None
    assert isinstance(keywords["lifecycle_stage_acquirer"], ast.Name)


def test_cli_pull_request_readers_expose_no_write_method() -> None:
    for reader in (cli.LivePullRequestPageReader(ScenarioClient()),
                   cli.LivePullRequestDetailReader(ScenarioClient())):
        for name in ("post", "put", "patch", "delete", "request", "write"):
            assert not hasattr(reader, name)


# --------------------------------------------------------------------------
# Record-only lineage for candidates the selector never reached (#3441)
# --------------------------------------------------------------------------
OTHER = 4000


def run_two_candidates(monkeypatch, tmp_path, client):
    monkeypatch.setattr(cli, "GitHubReadClient", lambda: client)
    output = tmp_path / "record.json"
    code = cli.main(
        [
            "--repository", REPO,
            "--campaign-id", "campaign-3441",
            "--retrieved-at", OBSERVED,
            "--candidates", f"{OTHER},{ISSUE}",
            "--narrowing-criterion", "explicit-request:test-3441",
            "--output", str(output),
        ]
    )
    return code, json.loads(output.read_text())


def test_cli_records_lineage_for_candidates_after_the_selector_stopped(monkeypatch, tmp_path) -> None:
    # ISSUE has conflicting claims, so the selector stops there; OTHER has one
    # clean claim and is evaluated afterwards for the record only.
    client = ScenarioClient(
        prs=[pr_rest(20), pr_rest(21), pr_rest(22, body=f"Closes #{OTHER}\n")],
        open_issues=(ISSUE, OTHER),
    )
    code, record = run_two_candidates(monkeypatch, tmp_path, client)
    assert code == 0
    (first,) = lifecycle(record)["candidates"]
    assert first["issue_number"] == ISSUE and first["outcome"] == "manual-review"
    (later,) = lifecycle(record)["record_only_candidates"]
    assert later["issue_number"] == OTHER
    assert later["outcome"] == "acquired" and later["lifecycle_stage"] == "review"
    assert later["selection_input"] is False
    assert "selection_input" not in first
    assert lifecycle(record)["record_only_truncated"] is False
    # The selector result is unchanged: the later stage never reached it.
    assert record["deterministic_selector_result"]["selected_issue_number"] is None
    assert "shadow-selection.candidate-evidence-incomplete" in (
        record["deterministic_selector_result"]["reason_codes"]
    )
    # One population listing serves both candidates.
    assert [p for p in client.paths if "/pulls?" in p] == [
        f"/repos/{REPO}/pulls?state=all&per_page=100&page=1"
    ]
    assert_read_only_and_non_selecting(client, record)


def test_cli_record_only_list_is_empty_when_every_candidate_was_read(monkeypatch, tmp_path) -> None:
    client = ScenarioClient(prs=[pr_rest(20, draft=True)])
    _, record = run_cli(monkeypatch, tmp_path, client)
    assert lifecycle(record)["record_only_candidates"] == []
    assert lifecycle(record)["record_only_truncated"] is False


def test_record_only_lineage_is_bounded_and_survives_acquirer_errors() -> None:
    class Acquirer:
        def __init__(self):
            self.observations = ()
            self.calls = []

        def acquire_lifecycle_stage(self, repository, issue_number):
            self.calls.append(issue_number)
            if issue_number == 3:
                raise RuntimeError("transport failure")
            if issue_number == 4:
                raise KeyError("unexpected")
            self.observations = (*self.observations, {"issue_number": issue_number, "outcome": "unavailable"})

    acquirer = Acquirer()
    # Nothing is read when the selector itself read no candidate.
    assert cli._record_only_lineage(acquirer, REPO, (1, 2)) == {"candidates": [], "truncated": False}
    assert acquirer.calls == []
    acquirer.observations = ({"issue_number": 0, "outcome": "unavailable"},)
    numbers = tuple(range(1, cli.RECORD_ONLY_LINEAGE_LIMIT + 5))
    outcome = cli._record_only_lineage(acquirer, REPO, numbers)
    assert acquirer.calls == list(numbers[: cli.RECORD_ONLY_LINEAGE_LIMIT])
    assert outcome["truncated"] is True
    by_number = {entry["issue_number"]: entry for entry in outcome["candidates"]}
    assert by_number[3]["reason_codes"] == ["record-only.acquisition-error"]
    assert "RuntimeError" in by_number[3]["failure_detail"]
    assert "KeyError" in by_number[4]["failure_detail"]
    assert by_number[3]["contract_version"] == cli.PR_LINEAGE_READER_CONTRACT_VERSION
    assert all(entry["selection_input"] is False for entry in outcome["candidates"])
    assert len(outcome["candidates"]) == cli.RECORD_ONLY_LINEAGE_LIMIT
    assert [entry["issue_number"] for entry in outcome["candidates"]] == sorted(by_number)
