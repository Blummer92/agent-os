"""Tests for the #3489 production GitHub closure adapter.

All GitHub I/O goes through a stateful fake transport: no network, no
live repository, no real issue is ever closed by these tests.
"""

import hashlib
import json

import pytest

from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    ClosureWriteUncertain,
)
from scripts.agent_os_issue_acceptance.github_closure_dispatch import (
    GitHubClosureReader,
    GitHubClosureWriter,
    load_closure_manifest,
    main,
    run_closure_dispatch,
)

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


def request_dict(issue: int, **overrides):
    data = {
        "repository": REPO,
        "issue_number": issue,
        "authorizer_id": "repository-owner",
        "decision_id": f"owner-decision-{issue}",
        "decision_recorded": True,
        "evaluator_id": "independent-qa",
        "evidence_id": f"qa-evidence-{issue}",
        "verdict": "pass",
    }
    data.update(overrides)
    return data


def manifest(*requests):
    return {"requests": list(requests)}


class FakeGitHub:
    """Stateful fake GitHub API: GET reads, PATCH closes, nothing else."""

    def __init__(self):
        self.issues: dict[int, dict] = {}
        self.patch_calls: list[tuple[str, str, dict]] = []
        self.get_counts: dict[int, int] = {}
        self.patch_behavior: dict[int, object] = {}
        self.get_fail_from: dict[int, int] = {}
        self.drift_on_first_read: set[int] = set()

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
            "state": data["state"],
            "body": data["body"],
            "labels": [{"name": label} for label in data["labels"]],
            "repository_url": f"https://api.github.com/repos/{REPO}",
            "state_reason": data["state_reason"],
        }
        if data["pr"]:
            payload["pull_request"] = {"url": "https://api.github.com/repos/x/y/pulls/1"}
        return payload

    def __call__(self, method, path, body):
        parts = path.strip("/").split("/")
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
    return run_closure_dispatch(manifest(*requests), fake)


def test_fully_satisfied_issue_closes_verified_with_exact_payload():
    fake = FakeGitHub()
    fake.add(100)
    outcomes = dispatch(
        fake, request_dict(100, satisfaction=satisfaction(100, complete=True))
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
        fake, request_dict(101, satisfaction=satisfaction(101, complete=False))
    )
    assert outcomes[0]["status"] == "blocked"
    assert "closure.satisfaction-incomplete" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_unrecorded_decision_blocks_without_write():
    fake = FakeGitHub()
    fake.add(102)
    outcomes = dispatch(fake, request_dict(102, decision_recorded=False))
    assert outcomes[0]["status"] == "blocked"
    assert "closure.authorization-not-recorded" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_wrong_repository_blocks_without_write():
    fake = FakeGitHub()
    fake.add(103)
    outcomes = dispatch(
        fake, request_dict(103, repository="Other/repo")
    )
    assert outcomes[0]["status"] == "blocked"
    assert fake.patch_calls == []


def test_wrong_issue_number_in_payload_blocks_without_write():
    fake = FakeGitHub()
    fake.add(104, wrong_number=True)
    outcomes = dispatch(fake, request_dict(104))
    assert outcomes[0]["status"] == "blocked"
    assert fake.patch_calls == []


def test_self_acceptance_blocks_without_write():
    fake = FakeGitHub()
    fake.add(105)
    outcomes = dispatch(
        fake, request_dict(105, evaluator_id="repository-owner")
    )
    assert outcomes[0]["status"] == "blocked"
    assert "closure.acceptance-not-independent" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_failed_acceptance_blocks_without_write():
    fake = FakeGitHub()
    fake.add(106)
    outcomes = dispatch(fake, request_dict(106, verdict="fail"))
    assert outcomes[0]["status"] == "blocked"
    assert "closure.acceptance-not-passed" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_acceptance_issue_mismatch_blocks_without_write():
    fake = FakeGitHub()
    fake.add(107)
    outcomes = dispatch(
        fake, request_dict(107, acceptance_issue_number=999)
    )
    assert outcomes[0]["status"] == "blocked"
    assert "closure.acceptance-issue-mismatch" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_acceptance_head_mismatch_blocks_without_write():
    fake = FakeGitHub()
    fake.add(108)
    outcomes = dispatch(
        fake,
        request_dict(108, acceptance_validated_head_sha="f" * 40),
    )
    assert outcomes[0]["status"] == "blocked"
    assert fake.patch_calls == []


def test_pull_request_payload_blocks_without_write():
    fake = FakeGitHub()
    fake.add(109, pr=True)
    outcomes = dispatch(fake, request_dict(109))
    assert outcomes[0]["status"] == "blocked"
    assert fake.patch_calls == []


def test_revision_change_between_reads_blocks_without_write():
    fake = FakeGitHub()
    fake.add(110)
    fake.drift_on_first_read.add(110)
    outcomes = dispatch(fake, request_dict(110))
    assert outcomes[0]["status"] == "blocked"
    assert outcomes[0]["reason_codes"] == [
        "closure.verification-failed-stale-or-drifted"
    ]
    assert fake.patch_calls == []


def test_already_closed_completed_is_already_closed_without_write():
    fake = FakeGitHub()
    fake.add(111, state="closed", state_reason="completed")
    outcomes = dispatch(fake, request_dict(111))
    assert outcomes[0]["status"] == "already-closed"
    assert outcomes[0]["readback_verified"] is True
    assert fake.patch_calls == []


def test_already_closed_wrong_reason_is_not_verified():
    fake = FakeGitHub()
    fake.add(112, state="closed", state_reason="not_planned")
    outcomes = dispatch(fake, request_dict(112))
    assert outcomes[0]["status"] == "closed-reason-mismatch"
    assert outcomes[0]["readback_verified"] is False
    assert fake.patch_calls == []


def test_uncertain_write_applied_reconciles_via_readback():
    fake = FakeGitHub()
    fake.add(113)
    fake.patch_behavior[113] = "uncertain-applied"
    outcomes = dispatch(fake, request_dict(113))
    assert outcomes[0]["status"] == "closed-verified-after-uncertain-write"
    assert outcomes[0]["readback_verified"] is True
    assert len(fake.patch_calls) == 1


def test_uncertain_write_not_applied_is_not_closed():
    fake = FakeGitHub()
    fake.add(114)
    fake.patch_behavior[114] = "timeout"
    outcomes = dispatch(fake, request_dict(114))
    assert outcomes[0]["status"] == "uncertain-write-not-closed"
    assert outcomes[0]["readback_verified"] is False


def test_ambiguous_write_response_is_uncertain_not_success():
    fake = FakeGitHub()
    fake.add(115)
    fake.patch_behavior[115] = "ambiguous"
    outcomes = dispatch(fake, request_dict(115))
    assert outcomes[0]["status"] == "uncertain-write-not-closed"
    assert outcomes[0]["readback_verified"] is False


def test_write_readback_failure_is_readback_unavailable():
    fake = FakeGitHub()
    fake.add(116)
    # Initial readback + fresh snapshot succeed; the post-write read fails.
    fake.get_fail_from[116] = 3
    outcomes = dispatch(fake, request_dict(116))
    assert outcomes[0]["status"] == "readback-unavailable"
    assert len(fake.patch_calls) == 1


def test_forbidden_write_status_is_write_failed():
    fake = FakeGitHub()
    fake.add(117)
    fake.patch_behavior[117] = 403
    outcomes = dispatch(fake, request_dict(117))
    assert outcomes[0]["status"] == "write-failed"
    assert outcomes[0]["reason_codes"] == ["closure.write-failed:RuntimeError"]


def test_duplicate_delivery_second_run_is_already_closed():
    fake = FakeGitHub()
    fake.add(118)
    first = dispatch(fake, request_dict(118))
    assert first[0]["status"] == "closed-verified"
    second = dispatch(fake, request_dict(118))
    assert second[0]["status"] == "already-closed"
    assert len(fake.patch_calls) == 1


def test_batch_continues_past_blocked_item():
    fake = FakeGitHub()
    fake.add(119)
    fake.add(120)
    fake.add(121)
    outcomes = dispatch(
        fake,
        request_dict(119),
        request_dict(120, satisfaction=satisfaction(120, complete=False)),
        request_dict(121),
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
    outcomes = dispatch(fake, request_dict(3292))
    assert outcomes[0]["status"] == "blocked"
    assert "closure.protected-target" in outcomes[0]["reason_codes"]
    assert fake.patch_calls == []


def test_malformed_label_blocks_without_silent_drop():
    fake = FakeGitHub()
    fake.add(122, labels=["Bad Label!"])
    outcomes = dispatch(fake, request_dict(122))
    assert outcomes[0]["status"] == "blocked"
    assert fake.patch_calls == []


def test_manifest_rejects_extra_keys_duplicates_and_bool_ints():
    base = request_dict(130)
    with pytest.raises(ValueError):
        load_closure_manifest({"requests": [base], "extra": []})
    with pytest.raises(ValueError):
        load_closure_manifest(manifest({**base, "surprise": 1}))
    with pytest.raises(ValueError):
        load_closure_manifest(manifest(base, request_dict(130)))
    with pytest.raises(TypeError):
        load_closure_manifest(manifest(request_dict(131, issue_number=True)))
    with pytest.raises(TypeError):
        load_closure_manifest(manifest(request_dict(131, decision_recorded=1)))
    with pytest.raises(ValueError):
        load_closure_manifest({"requests": []})


def test_dry_run_never_writes_even_for_admitted_issue(tmp_path, capsys):
    fake = FakeGitHub()
    fake.add(140)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest(request_dict(140))), encoding="utf-8"
    )
    assert main(["--manifest", str(manifest_path)], transport=fake) == 0
    captured = capsys.readouterr()
    printed = json.loads(captured.out)
    assert printed["live"] is False
    assert printed["outcomes"][0]["status"] == "would-close"
    assert fake.patch_calls == []
    # Exactly one JSON object on stdout, nothing else.
    assert captured.out.strip().count("\n") == 0


def test_dry_run_reports_blocked_issue(tmp_path, capsys):
    fake = FakeGitHub()
    fake.add(141)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            manifest(
                request_dict(
                    141, satisfaction=satisfaction(141, complete=False)
                )
            )
        ),
        encoding="utf-8",
    )
    assert main(["--manifest", str(manifest_path)], transport=fake) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["outcomes"][0]["status"] == "blocked"
    assert fake.patch_calls == []


def test_live_without_token_exits_2_before_any_call(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest(request_dict(142))), encoding="utf-8"
    )
    assert main(["--manifest", str(manifest_path), "--live"]) == 2


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

def test_dry_run_preserves_stale_ready_label_reconciliation(tmp_path, capsys):
    """An already-closed issue with a stale Ready label is not fully reconciled."""
    fake = FakeGitHub()
    fake.add(152, state="closed", state_reason="completed", labels=["status:ready"])
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest(request_dict(152))), encoding="utf-8"
    )
    assert main(["--manifest", str(manifest_path)], transport=fake) == 0
    outcome = json.loads(capsys.readouterr().out)["outcomes"][0]
    assert outcome["status"] == "closed-verified-label-reconciliation-required"
    assert outcome["readback_verified"] is True
    assert "closure.stale-ready-label-present" in outcome["reason_codes"]
    assert fake.patch_calls == []

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
