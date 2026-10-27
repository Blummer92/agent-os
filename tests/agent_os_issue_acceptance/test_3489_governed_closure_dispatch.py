"""Tests for the #3489 production GitHub closure adapter (corrected revision).

All GitHub I/O goes through a stateful fake transport: no network, no
live repository, no real issue is ever closed by these tests.

The corrected adapter takes ``IssueClosureRequest`` objects from a trusted
host caller. There is no manifest format and no CLI in the production
module (see its trust-boundary note): a caller-authored manifest must never
become an authority source, so these tests build request objects directly
and assert the manifest/CLI surface is gone.
"""

import hashlib

import pytest

from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    ClosureAcceptanceEvidence,
    ClosureWriteUncertain,
    IssueClosureRequest,
)
from scripts.agent_os_issue_acceptance.github_closure_dispatch import (
    GitHubClosureReader,
    GitHubClosureWriter,
    run_closure_dispatch,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
)
from scripts.agent_os_github_issue_provider.revision import issue_source_revision

REPO = "Blummer92/agent-os"
EMPTY_BODY_DIGEST = hashlib.sha256(b"").hexdigest()


def body_digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def satisfaction(issue: int, *, complete: bool, digest: str = EMPTY_BODY_DIGEST):
    if complete:
        criteria = [
            {
                "index": 1,
                "identity": "criterion-1",
                "disposition": "satisfied",
                "reason_code": "ok",
                "evidence": ["evidence-1"],
            }
        ]
        status = "complete"
    else:
        criteria = [
            {
                "index": 1,
                "identity": "criterion-1",
                "disposition": "unsatisfied",
                "reason_code": "not-done",
                "evidence": ["evidence-1"],
            }
        ]
        status = "incomplete"
    return {
        "repository": REPO,
        "issue_number": issue,
        "issue_body_digest": digest,
        "status": status,
        "criteria": criteria,
    }


def request_obj(issue: int, **overrides):
    """Build a trusted-caller request object (not a manifest dict).

    Keyword overrides mirror the old manifest fields so the negative cases
    stay readable: repository, authorizer_id, decision_id,
    decision_recorded, evaluator_id, evidence_id, verdict,
    acceptance_issue_number, acceptance_validated_head_sha, satisfaction.
    """
    data = {
        "repository": REPO,
        "authorizer_id": "repository-owner",
        "decision_id": f"owner-decision-{issue}",
        "decision_recorded": True,
        "evaluator_id": "independent-qa",
        "evidence_id": f"qa-evidence-{issue}",
        "verdict": "pass",
        "acceptance_issue_number": None,
        "acceptance_validated_head_sha": None,
        "satisfaction": None,
    }
    data.update(overrides)
    # A satisfaction mapping naming another issue is rejected by the
    # request constructor itself; tests pass the issue explicitly.
    return IssueClosureRequest(
        decision=LifecycleOwnerDecision(
            repository=data["repository"],
            issue_number=issue,
            pull_request_number=None,
            requested_mutations=("close-issue",),
            authorizer_id=data["authorizer_id"],
            decision_id=data["decision_id"],
            decision_recorded=data["decision_recorded"],
        ),
        acceptance=ClosureAcceptanceEvidence(
            verdict=data["verdict"],
            evidence_id=data["evidence_id"],
            evaluator_id=data["evaluator_id"],
            issue_number=data["acceptance_issue_number"],
            validated_head_sha=data["acceptance_validated_head_sha"],
        ),
        satisfaction=data["satisfaction"],
    )


class FakeGitHub:
    """Stateful fake GitHub API: GET reads, PATCH closes, DELETE labels,
    POST comments, and GET comments for requirement 3 reconciliation."""

    def __init__(self):
        self.issues: dict[int, dict] = {}
        self.comments: dict[int, list[str]] = {}
        self.patch_calls: list[tuple[str, str, dict]] = []
        self.delete_calls: list[tuple[str, str]] = []
        self.post_calls: list[tuple[str, str, dict]] = []
        self.get_counts: dict[int, int] = {}
        self.patch_behavior: dict[int, object] = {}
        self.get_fail_from: dict[int, int] = {}
        self.drift_on_first_read: set[int] = set()
        self.delete_behavior: dict[int, object] = {}
        self.post_behavior: dict[int, object] = {}

    def add(self, issue: int, **kw):
        data = {
            "state": "open",
            "body": "",
            "labels": [],
            "state_reason": None,
            "pr": False,
            "wrong_number": False,
        }
        data.update(kw)
        self.issues[issue] = data

    def _payload(self, issue: int) -> dict:
        data = self.issues[issue]
        payload: dict = {
            "number": issue + 1000 if data["wrong_number"] else issue,
            "title": f"Issue {issue}",
            "state": data["state"],
            "body": data["body"],
            "html_url": f"https://github.com/{REPO}/issues/{issue}",
            "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-26T00:00:00Z",
            "closed_at": (
                "2026-10-26T18:00:00Z" if data["state"] == "closed" else None
            ),
            "labels": [{"name": label} for label in data["labels"]],
            "repository_url": f"https://api.github.com/repos/{REPO}",
            "state_reason": data["state_reason"],
        }
        if data["pr"]:
            payload["pull_request"] = {"url": "https://api.github.com/repos/x/y/pulls/1"}
        return payload

    def __call__(self, method, path, body):
        parts = path.strip("/").split("/")
        if "comments" in parts:
            issue = int(parts[parts.index("comments") - 1])
            if method == "GET":
                return 200, [{"body": c} for c in self.comments.get(issue, [])]
            if method == "POST":
                self.post_calls.append((method, path, body))
                behavior = self.post_behavior.get(issue)
                if behavior == "timeout":
                    raise TimeoutError("connection timed out")
                if type(behavior) is int:
                    return behavior, {}
                self.comments.setdefault(issue, []).append(body["body"])
                return 201, {"body": body["body"]}
            raise AssertionError(f"unexpected method {method} for comments")
        if "labels" in parts:
            issue = int(parts[parts.index("labels") - 1])
            label = parts[-1]
            if method == "DELETE":
                self.delete_calls.append((method, path))
                behavior = self.delete_behavior.get(issue)
                if behavior == "timeout":
                    raise TimeoutError("connection timed out")
                if type(behavior) is int:
                    return behavior, {}
                if issue in self.issues and label in self.issues[issue]["labels"]:
                    self.issues[issue]["labels"].remove(label)
                return 200, [{"name": l} for l in self.issues.get(issue, {}).get("labels", [])]
            raise AssertionError(f"unexpected method {method} for labels")
        issue = int(parts[-1])
        if method == "GET":
            count = self.get_counts.get(issue, 0) + 1
            self.get_counts[issue] = count
            if issue in self.get_fail_from and count >= self.get_fail_from[issue]:
                return 503, {}
            if issue not in self.issues:
                return 404, {}
            payload = self._payload(issue)
            if issue in self.drift_on_first_read and count == 1:
                # Body changes between the initial readback and the fresh
                # pre-dispatch read, so the verification gate must fail.
                self.issues[issue]["body"] = "edited after evaluation"
            return 200, payload
        if method == "PATCH":
            self.patch_calls.append((method, path, body))
            if issue not in self.issues:
                return 404, {}
            behavior = self.patch_behavior.get(issue)
            if behavior == "timeout":
                raise TimeoutError("connection timed out")
            if behavior == "connection":
                raise ConnectionError("connection reset")
            if behavior == "uncertain-applied":
                self.issues[issue]["state"] = "closed"
                self.issues[issue]["state_reason"] = "completed"
                raise TimeoutError("response lost after write")
            if behavior == "ambiguous":
                return 200, self._payload(issue)
            if type(behavior) is int:
                return behavior, {}
            self.issues[issue]["state"] = "closed"
            self.issues[issue]["state_reason"] = "completed"
            return 200, self._payload(issue)
        raise AssertionError(f"unexpected method {method}")


def dispatch(fake, *requests):
    return run_closure_dispatch(tuple(requests), fake)


def test_fully_satisfied_issue_closes_verified_with_exact_payload():
    fake = FakeGitHub()
    fake.add(100)
    outcomes = dispatch(
        fake, request_obj(100, satisfaction=satisfaction(100, complete=True))
    )
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome["issue_number"] == 100
    assert outcome["status"] == "closed-verified"
    assert outcome["readback_verified"] is True
    assert outcome["receipt_id"] is not None
    assert len(fake.patch_calls) == 1
    method, path, body = fake.patch_calls[0]
    assert method == "PATCH"
    assert path == "/repos/Blummer92/agent-os/issues/100"
    assert body == {"state": "closed", "state_reason": "completed"}
    assert fake.issues[100]["state"] == "closed"
    assert fake.issues[100]["state_reason"] == "completed"


def test_incomplete_satisfaction_blocks_without_write():
    fake = FakeGitHub()
    fake.add(101)
    outcomes = dispatch(
        fake, request_obj(101, satisfaction=satisfaction(101, complete=False))
    )
    assert outcomes[0]["status"] == "blocked"
    assert "closure.satisfaction-incomplete" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_unrecorded_decision_blocks_without_write():
    fake = FakeGitHub()
    fake.add(102)
    outcomes = dispatch(fake, request_obj(102, decision_recorded=False))
    assert outcomes[0]["status"] == "blocked"
    assert "closure.authorization-not-recorded" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_wrong_repository_blocks_without_write():
    fake = FakeGitHub()
    fake.add(103)
    outcomes = dispatch(
        fake, request_obj(103, repository="Other/repo")
    )
    assert outcomes[0]["status"] == "blocked"
    assert fake.patch_calls == []


def test_wrong_issue_number_in_payload_blocks_without_write():
    fake = FakeGitHub()
    fake.add(104, wrong_number=True)
    outcomes = dispatch(fake, request_obj(104))
    assert outcomes[0]["status"] == "blocked"
    assert fake.patch_calls == []


def test_self_acceptance_blocks_without_write():
    fake = FakeGitHub()
    fake.add(105)
    outcomes = dispatch(fake, request_obj(105, evaluator_id="repository-owner"))
    assert outcomes[0]["status"] == "blocked"
    assert "closure.acceptance-not-independent" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_failed_acceptance_blocks_without_write():
    fake = FakeGitHub()
    fake.add(106)
    outcomes = dispatch(fake, request_obj(106, verdict="fail"))
    assert outcomes[0]["status"] == "blocked"
    assert "closure.acceptance-not-passed" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_acceptance_issue_mismatch_blocks_without_write():
    fake = FakeGitHub()
    fake.add(107)
    outcomes = dispatch(
        fake, request_obj(107, acceptance_issue_number=999)
    )
    assert outcomes[0]["status"] == "blocked"
    assert "closure.acceptance-issue-mismatch" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_acceptance_head_mismatch_blocks_without_write():
    # The issue-only reader carries no PR head, so a head-bound QA record
    # fails closed by the canonical ADV-2 rule instead of being honoured
    # against a caller-supplied head.
    fake = FakeGitHub()
    fake.add(108)
    outcomes = dispatch(
        fake,
        request_obj(108, acceptance_validated_head_sha="f" * 40),
    )
    assert outcomes[0]["status"] == "blocked"
    assert "closure.acceptance-head-unverifiable" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_pull_request_payload_blocks_without_write():
    fake = FakeGitHub()
    fake.add(109, pr=True)
    outcomes = dispatch(fake, request_obj(109))
    assert outcomes[0]["status"] == "blocked"
    assert fake.patch_calls == []


def test_revision_change_between_reads_blocks_without_write():
    fake = FakeGitHub()
    fake.add(110)
    fake.drift_on_first_read.add(110)
    outcomes = dispatch(fake, request_obj(110))
    assert outcomes[0]["status"] == "blocked"
    assert fake.patch_calls == []


def test_already_closed_completed_is_already_closed_without_write():
    fake = FakeGitHub()
    fake.add(111, state="closed", state_reason="completed")
    outcomes = dispatch(fake, request_obj(111))
    assert outcomes[0]["status"] == "already-closed"
    assert outcomes[0]["readback_verified"] is True
    assert fake.patch_calls == []


def test_already_closed_wrong_reason_is_not_verified():
    fake = FakeGitHub()
    fake.add(112, state="closed", state_reason="not_planned")
    outcomes = dispatch(fake, request_obj(112))
    assert outcomes[0]["readback_verified"] is False
    assert fake.patch_calls == []


def test_already_closed_stale_ready_is_flagged_not_edited():
    # #3489 req 3, label leg: the batch flags stale Ready on a closed issue
    # and never edits labels through the close writer.
    fake = FakeGitHub()
    fake.add(152, state="closed", state_reason="completed", labels=["status:ready"])
    outcomes = dispatch(fake, request_obj(152))
    # The batch's already-closed short-circuit reports "already-closed"
    # (the raw classifier's "closed-verified-label-reconciliation-required"
    # is the underlying classification); the stale-ready reason must survive
    # in the outcome, and no label edit may occur.
    assert outcomes[0]["status"] == "already-closed"
    assert outcomes[0]["readback_verified"] is True
    assert "closure.stale-ready-label-present" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_uncertain_write_applied_reconciles_via_readback():
    fake = FakeGitHub()
    fake.add(113)
    fake.patch_behavior[113] = "uncertain-applied"
    outcomes = dispatch(fake, request_obj(113))
    assert outcomes[0]["status"] == "closed-verified-after-uncertain-write"
    assert outcomes[0]["readback_verified"] is True
    assert len(fake.patch_calls) == 1


def test_uncertain_write_not_applied_is_not_closed():
    fake = FakeGitHub()
    fake.add(114)
    fake.patch_behavior[114] = "timeout"
    outcomes = dispatch(fake, request_obj(114))
    assert outcomes[0]["status"] == "uncertain-write-not-closed"
    assert outcomes[0]["readback_verified"] is False


def test_ambiguous_write_response_is_uncertain_not_success():
    fake = FakeGitHub()
    fake.add(115)
    fake.patch_behavior[115] = "ambiguous"
    outcomes = dispatch(fake, request_obj(115))
    assert outcomes[0]["status"] == "uncertain-write-not-closed"
    assert outcomes[0]["readback_verified"] is False


def test_write_readback_failure_is_readback_unavailable():
    fake = FakeGitHub()
    fake.add(116)
    # Initial readback + fresh snapshot succeed; the post-write read fails.
    fake.get_fail_from[116] = 3
    outcomes = dispatch(fake, request_obj(116))
    assert outcomes[0]["status"] == "readback-unavailable"
    assert len(fake.patch_calls) == 1


def test_forbidden_write_status_is_write_failed():
    fake = FakeGitHub()
    fake.add(117)
    fake.patch_behavior[117] = 403
    outcomes = dispatch(fake, request_obj(117))
    assert outcomes[0]["status"] == "write-failed"
    assert outcomes[0]["reason_codes"] == ["closure.write-failed:RuntimeError"]


def test_duplicate_delivery_second_run_is_already_closed():
    fake = FakeGitHub()
    fake.add(118)
    first = dispatch(fake, request_obj(118))
    assert first[0]["status"] == "closed-verified"
    second = dispatch(fake, request_obj(118))
    assert second[0]["status"] == "already-closed"
    assert len(fake.patch_calls) == 1


def test_batch_continues_past_blocked_item():
    fake = FakeGitHub()
    fake.add(119)
    fake.add(120)
    fake.add(121)
    outcomes = dispatch(
        fake,
        request_obj(119),
        request_obj(120, satisfaction=satisfaction(120, complete=False)),
        request_obj(121),
    )
    assert [o["status"] for o in outcomes] == [
        "closed-verified",
        "blocked",
        "closed-verified",
    ]
    assert len(fake.patch_calls) == 2


def test_protected_issue_3292_blocks_without_write():
    fake = FakeGitHub()
    fake.add(3292)
    outcomes = dispatch(fake, request_obj(3292))
    assert outcomes[0]["status"] == "blocked"
    assert "closure.protected-target" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_malformed_label_blocks_without_silent_drop():
    fake = FakeGitHub()
    fake.add(122, labels=["Bad Label!"])
    outcomes = dispatch(fake, request_obj(122))
    assert outcomes[0]["status"] == "blocked"
    assert fake.patch_calls == []


def test_no_manifest_or_cli_surface_exists():
    """The deleted authority surface must stay deleted."""
    from scripts.agent_os_issue_acceptance import github_closure_dispatch as module

    assert not hasattr(module, "load_closure_manifest")
    assert not hasattr(module, "main")
    assert not hasattr(module, "_load_merge_observation")
    assert not hasattr(module, "_dry_run_outcomes")
    fake = FakeGitHub()
    fake.add(130)
    with pytest.raises(TypeError):
        run_closure_dispatch({"requests": [request_obj(130)]}, fake)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        run_closure_dispatch([request_obj(130)], fake)  # type: ignore[arg-type]
    assert fake.patch_calls == []


def test_reader_uses_canonical_issue_revision():
    fake = FakeGitHub()
    fake.add(160, body="hello")
    reader = GitHubClosureReader(fake)
    snapshot = reader.read_issue_snapshot(REPO, 160)
    expected = issue_source_revision(fake._payload(160))
    assert snapshot.observed_revision == expected
    assert snapshot.observed_revision.startswith("github-issue-v1:")
    # A title change moves the canonical revision (the deleted adapter-local
    # scheme omitted title and timestamps).
    payload = fake._payload(160)
    payload["title"] = "Different title"
    assert issue_source_revision(payload) != expected


def test_reader_snapshot_is_issue_only_and_review_unknown():
    fake = FakeGitHub()
    fake.add(161)
    snapshot = GitHubClosureReader(fake).read_issue_snapshot(REPO, 161)
    assert snapshot.pull_request_number is None
    assert snapshot.source_head is None
    assert snapshot.base_head is None
    assert snapshot.pr_state == "none"
    assert snapshot.merged is False
    # An issue-only read must not claim a clear review state.
    assert snapshot.review_state == "unknown"


def test_writer_transport_mapping():
    fake = FakeGitHub()
    fake.add(150)
    writer = GitHubClosureWriter(fake)
    fake.patch_behavior[150] = 503
    with pytest.raises(ClosureWriteUncertain):
        writer.close_issue(REPO, 150, state_reason="completed")
    fake.patch_behavior[150] = "timeout"
    with pytest.raises(ClosureWriteUncertain):
        writer.close_issue(REPO, 150, state_reason="completed")
    fake.patch_behavior[150] = 403
    with pytest.raises(RuntimeError, match="403"):
        writer.close_issue(REPO, 150, state_reason="completed")
    with pytest.raises(ValueError):
        writer.close_issue(REPO, 150, state_reason="not_planned")


def test_reader_rejects_pull_request_payload_directly():
    fake = FakeGitHub()
    fake.add(151, pr=True)
    reader = GitHubClosureReader(fake)
    with pytest.raises(ValueError):
        reader.read_issue_readback(REPO, 151)


def test_canonical_github_transport_reuses_shared_client_and_request(monkeypatch):
    """No private HTTP stack: one canonical request with no write retry."""
    from scripts.agent_os_issue_acceptance import github_closure_dispatch as module

    seen = []

    def fake_client(environment, *, user_agent):
        seen.append(("client", dict(environment), user_agent))
        return object()

    def fake_request(client, method, path, **kwargs):
        seen.append(("request", method, path, kwargs))
        return type("Result", (), {"payload": {"state": "closed"}})()

    monkeypatch.setattr(module, "build_token_client", fake_client)
    monkeypatch.setattr(module, "request_json", fake_request)
    request = module.github_api_transport("example-token")
    status, payload = request(
        "PATCH",
        "/repos/Blummer92/agent-os/issues/200",
        {"state": "closed", "state_reason": "completed"},
    )
    assert (status, payload) == (200, {"state": "closed"})
    assert seen[0] == (
        "client",
        {"GITHUB_TOKEN": "example-token"},
        "agent-os-closure-dispatch",
    )
    assert seen[1][1:3] == (
        "PATCH",
        "/repos/Blummer92/agent-os/issues/200",
    )
    assert seen[1][3]["max_attempts"] == 1
    assert seen[1][3]["input_payload"] == {
        "state": "closed",
        "state_reason": "completed",
    }


def test_canonical_github_transport_preserves_error_classification(monkeypatch):
    from scripts.agent_os_issue_acceptance import github_closure_dispatch as module
    from scripts.agent_os_github_issue_provider.request import (
        GitHubRequestAttempt,
        GitHubRequestError,
    )

    monkeypatch.setattr(module, "build_token_client", lambda *args, **kwargs: object())
    request = module.github_api_transport("example-token")

    def fail(kind, status):
        def perform(*args, **kwargs):
            raise GitHubRequestError(
                kind,
                status=status,
                attempts=(GitHubRequestAttempt(1, kind),),
            )
        monkeypatch.setattr(module, "request_json", perform)

    fail("http-error", 403)
    assert request("GET", "/repos/Blummer92/agent-os/issues/200", None) == (403, {})
    fail("http-error", 503)
    with pytest.raises(ClosureWriteUncertain):
        GitHubClosureWriter(request).close_issue(
            REPO, 200, state_reason="completed"
        )
    fail("transport-unavailable", None)
    with pytest.raises(ClosureWriteUncertain):
        GitHubClosureWriter(request).close_issue(
            REPO, 200, state_reason="completed"
        )
    fail("internal-error", None)
    with pytest.raises(RuntimeError, match="github-transport-failed:internal-error"):
        request("GET", "/repos/Blummer92/agent-os/issues/200", None)


def merge_observation(issue=200):
    from scripts.agent_os_issue_acceptance.merge_authorization import (
        MERGE_EXECUTION_OBSERVATION_SCHEMA_VERSION,
        MergeExecutionObservation,
    )
    return MergeExecutionObservation(
        schema_version=MERGE_EXECUTION_OBSERVATION_SCHEMA_VERSION,
        observation_id="",
        authorization_id="merge-authorization:" + "a" * 64,
        authorization_revision="merge-authorization-revision:" + "b" * 64,
        repository=REPO,
        pull_request_number=500,
        observed_head_sha="c" * 40,
        observed_base_identity="d" * 40,
        observed_merge_method="squash",
        observed_merge_commit_sha="e" * 40,
        observed_actor_id="repository-owner",
        observed_at="2026-10-26T18:00:00Z",
        audit_location="https://github.com/Blummer92/agent-os/pull/500",
        linked_issue_closure_observed=False,
    )


def post_merge_fake(issue=200, *, merged=True, body=None, head=None):
    fake = FakeGitHub()
    fake.add(issue)
    observation = merge_observation(issue)
    original = fake.__call__

    def transport(method, path, payload):
        if method == "GET" and path == f"/repos/{REPO}/pulls/500":
            return 200, {
                "number": 500,
                "state": "closed" if merged else "open",
                "draft": False,
                "merged": merged,
                "merged_at": "2026-10-26T18:00:00Z" if merged else None,
                "merge_commit_sha": "e" * 40,
                "head": {"sha": head or "c" * 40},
                "base": {"ref": "main", "repo": {"full_name": REPO}},
                "title": "Closure integration",
                "body": body if body is not None else f"Fixes #{issue}",
            }
        return original(method, path, payload)

    return fake, observation, transport


def test_verified_merge_observation_consumed_by_existing_closure_batch():
    from scripts.agent_os_issue_acceptance.github_closure_dispatch import (
        run_post_merge_closure_dispatch,
    )
    fake, observation, transport = post_merge_fake()
    result = run_post_merge_closure_dispatch(
        observation, (request_obj(200),), transport
    )
    assert result[0]["status"] == "closed-verified"
    assert result[0]["merge_observation_id"] == observation.observation_id
    assert result[0]["merge_commit_sha"] == observation.observed_merge_commit_sha
    assert len(fake.patch_calls) == 1


@pytest.mark.parametrize(
    ("merged", "body", "head"),
    [
        (False, None, None),
        (True, "Fixes #201", None),
        (True, "Unlinked pull request", None),
        (True, None, "f" * 40),
        (True, "Fixes #200 and #201", None),
    ],
)
def test_post_merge_refuses_unverified_merge_or_lineage(merged, body, head):
    from scripts.agent_os_issue_acceptance.github_closure_dispatch import (
        run_post_merge_closure_dispatch,
    )
    fake, observation, transport = post_merge_fake(
        merged=merged, body=body, head=head
    )
    with pytest.raises(ValueError, match="merge-observation"):
        run_post_merge_closure_dispatch(
            observation, (request_obj(200),), transport
        )
    assert fake.patch_calls == []


def test_verified_merge_does_not_bypass_independent_closure_admission():
    from scripts.agent_os_issue_acceptance.github_closure_dispatch import (
        run_post_merge_closure_dispatch,
    )
    fake, observation, transport = post_merge_fake()
    outcomes = run_post_merge_closure_dispatch(
        observation,
        (request_obj(200, decision_recorded=False),),
        transport,
    )
    assert outcomes[0]["status"] == "blocked"
    assert fake.patch_calls == []


def test_nonclosing_declared_linkage_requires_exact_issue():
    from scripts.agent_os_issue_acceptance.github_closure_dispatch import (
        run_post_merge_closure_dispatch,
    )
    fake, observation, transport = post_merge_fake(
        body="Part of #200\n\nNon-closing: #200"
    )
    result = run_post_merge_closure_dispatch(
        observation, (request_obj(200),), transport
    )
    assert result[0]["status"] == "closed-verified"
    assert len(fake.patch_calls) == 1


def test_post_merge_observation_rejects_wrong_issue_manifest():
    from scripts.agent_os_issue_acceptance.github_closure_dispatch import (
        run_post_merge_closure_dispatch,
    )
    fake, observation, transport = post_merge_fake()
    with pytest.raises(ValueError, match="merge-observation.pr-linkage-ambiguous"):
        run_post_merge_closure_dispatch(
            observation, (request_obj(201),), transport
        )
    assert fake.patch_calls == []


def test_post_merge_rejects_non_tuple_requests():
    from scripts.agent_os_issue_acceptance.github_closure_dispatch import (
        run_post_merge_closure_dispatch,
    )
    fake, observation, transport = post_merge_fake()
    with pytest.raises(TypeError):
        run_post_merge_closure_dispatch(
            observation, [request_obj(200)], transport  # type: ignore[arg-type]
        )
    assert fake.patch_calls == []
