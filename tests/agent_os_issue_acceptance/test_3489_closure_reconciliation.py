"""Tests for #3489 requirement 3 reconciliation in the dispatch module.

Post-close phase only, for items this batch freshly closed and verified:
remove exactly ``status:ready`` when the verified readback still carries
it, post one deterministic evidence comment, and re-read to verify both.
No network, no live issue, no closing keyword in any comment body.
Already-closed, blocked, and failed items are never reconciled, because
their batch path carries no admission receipt for this run.
"""

import hashlib

from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    ClosureAcceptanceEvidence,
    IssueClosureRequest,
)
from scripts.agent_os_issue_acceptance.github_closure_dispatch import (
    run_closure_dispatch,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
)
from scripts.agent_os_github_issue_provider.revision import issue_source_revision

REPO = "Blummer92/agent-os"
EMPTY_BODY_DIGEST = hashlib.sha256(b"").hexdigest()


def satisfaction(issue, *, complete=True):
    criteria = [{
        "index": 1, "identity": "criterion-1",
        "disposition": "satisfied" if complete else "unsatisfied",
        "reason_code": "ok" if complete else "not-done",
        "evidence": ["evidence-1"],
    }]
    return {
        "repository": REPO, "issue_number": issue,
        "issue_body_digest": EMPTY_BODY_DIGEST,
        "status": "complete" if complete else "incomplete",
        "criteria": criteria,
    }


def request_obj(issue):
    return IssueClosureRequest(
        decision=LifecycleOwnerDecision(
            repository=REPO, issue_number=issue, pull_request_number=None,
            requested_mutations=("close-issue",),
            authorizer_id="repository-owner",
            decision_id=f"owner-decision-{issue}", decision_recorded=True,
        ),
        acceptance=ClosureAcceptanceEvidence(
            verdict="pass", evidence_id=f"qa-evidence-{issue}",
            evaluator_id="independent-qa",
        ),
        satisfaction=satisfaction(issue),
    )


class FakeGitHub:
    def __init__(self):
        self.issues = {}
        self.comments = {}
        self.delete_calls = []
        self.post_calls = []
        self.delete_behavior = {}
        self.post_behavior = {}
        self.label_persists = set()

    def add(self, issue, **kw):
        data = {"state": "open", "body": "", "labels": [], "state_reason": None}
        data.update(kw)
        self.issues[issue] = data

    def _payload(self, issue):
        data = self.issues[issue]
        return {
            "number": issue, "title": f"Issue {issue}", "state": data["state"],
            "body": data["body"],
            "html_url": f"https://github.com/{REPO}/issues/{issue}",
            "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-26T00:00:00Z",
            "closed_at": "2026-10-26T18:00:00Z" if data["state"] == "closed" else None,
            "labels": [{"name": l} for l in data["labels"]],
            "repository_url": f"https://api.github.com/repos/{REPO}",
            "state_reason": data["state_reason"],
        }

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
            raise AssertionError("unexpected comments method")
        if "labels" in parts:
            issue = int(parts[parts.index("labels") - 1])
            label = parts[-1]
            assert method == "DELETE"
            self.delete_calls.append((method, path))
            behavior = self.delete_behavior.get(issue)
            if behavior == "timeout":
                raise TimeoutError("connection timed out")
            if type(behavior) is int:
                return behavior, {}
            if issue not in self.label_persists and label in self.issues[issue]["labels"]:
                self.issues[issue]["labels"].remove(label)
            return 200, []
        issue = int(parts[-1])
        assert method in ("GET", "PATCH")
        if method == "GET":
            return 200, self._payload(issue)
        self.issues[issue]["state"] = "closed"
        self.issues[issue]["state_reason"] = "completed"
        return 200, self._payload(issue)


def dispatch(fake, *requests):
    return run_closure_dispatch(tuple(requests), fake)


def test_fresh_close_with_stale_ready_removes_label_and_posts_comment():
    fake = FakeGitHub()
    fake.add(100, labels=["status:ready", "agent-os"])
    outcomes = dispatch(fake, request_obj(100))
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome["status"] == "closed-verified"
    assert outcome["readback_verified"] is True
    assert outcome["label_reconciled"] is True
    assert outcome["evidence_comment_posted"] is True
    assert "closure.label-reconciled" in outcome["reason_codes"]
    assert "closure.evidence-comment-posted" in outcome["reason_codes"]
    assert fake.delete_calls == [("DELETE", "/repos/Blummer92/agent-os/issues/100/labels/status:ready")]
    assert fake.issues[100]["labels"] == ["agent-os"]
    assert len(fake.post_calls) == 1
    comment = fake.post_calls[0][2]["body"]
    assert "Governed closure verified" in comment
    assert outcome["receipt_id"] in comment
    assert "qa-evidence-100" in comment
    assert "closes #" not in comment.lower()
    assert "fixes #" not in comment.lower()
    assert "resolves #" not in comment.lower()


def test_fresh_close_without_stale_label_still_posts_comment_no_label_delete():
    fake = FakeGitHub()
    fake.add(101, labels=["agent-os"])
    outcomes = dispatch(fake, request_obj(101))
    outcome = outcomes[0]
    assert outcome["status"] == "closed-verified"
    assert outcome["label_reconciled"] is False
    assert outcome["evidence_comment_posted"] is True
    assert fake.delete_calls == []
    assert fake.issues[101]["labels"] == ["agent-os"]


def test_label_removal_failure_keeps_closure_verified_and_continues():
    fake = FakeGitHub()
    fake.add(102, labels=["status:ready"])
    fake.add(103, labels=[])
    fake.delete_behavior[102] = 403
    outcomes = dispatch(fake, request_obj(102), request_obj(103))
    assert outcomes[0]["status"] == "closed-verified-reconciliation-failed"
    assert outcomes[0]["readback_verified"] is True
    assert fake.issues[102]["state"] == "closed"
    assert "status:ready" in fake.issues[102]["labels"]
    # Second item continues and reconciles normally.
    assert outcomes[1]["status"] == "closed-verified"
    assert outcomes[1]["evidence_comment_posted"] is True


def test_comment_failure_keeps_closure_verified_and_label_removal_stands():
    fake = FakeGitHub()
    fake.add(104, labels=["status:ready"])
    fake.post_behavior[104] = 500
    outcomes = dispatch(fake, request_obj(104))
    outcome = outcomes[0]
    assert outcome["status"] == "closed-verified-reconciliation-failed"
    assert outcome["readback_verified"] is True
    assert fake.issues[104]["labels"] == []
    assert outcome["evidence_comment_posted"] is False


def test_label_persisting_after_removal_is_reconciliation_failed():
    fake = FakeGitHub()
    fake.add(105, labels=["status:ready"])
    fake.label_persists.add(105)
    outcomes = dispatch(fake, request_obj(105))
    assert outcomes[0]["status"] == "closed-verified-reconciliation-failed"
    assert outcomes[0]["readback_verified"] is True


def test_already_closed_item_is_never_reconciled():
    fake = FakeGitHub()
    fake.add(106, state="closed", state_reason="completed", labels=["status:ready"])
    outcomes = dispatch(fake, request_obj(106))
    outcome = outcomes[0]
    assert outcome["status"] == "already-closed"
    assert fake.delete_calls == []
    assert fake.post_calls == []
    assert fake.issues[106]["labels"] == ["status:ready"]


def test_blocked_item_is_never_reconciled_and_next_item_continues():
    fake = FakeGitHub()
    fake.add(107, labels=[])
    fake.add(108, labels=[])
    blocked = request_obj(107)
    # Make the second request's satisfaction incomplete by rebuilding it.
    from scripts.agent_os_issue_acceptance.closure_admission_actions import (
        ClosureAcceptanceEvidence as CAE,
    )
    blocked_req = IssueClosureRequest(
        decision=blocked.decision,
        acceptance=blocked.acceptance,
        satisfaction=satisfaction(107, complete=False),
    )
    outcomes = dispatch(fake, blocked_req, request_obj(108))
    assert outcomes[0]["status"] == "blocked"
    assert fake.post_calls == [] or all("/108/" in p[1] for p in fake.post_calls)
    assert outcomes[1]["status"] == "closed-verified"
    assert outcomes[1]["evidence_comment_posted"] is True
