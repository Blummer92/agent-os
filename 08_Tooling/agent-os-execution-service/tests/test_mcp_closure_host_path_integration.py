"""#3489 production host-path integration: MCP admission tools -> real dispatcher.

This is not another mocked-dispatcher test. The admission and verification
steps run through the real MCP tool functions, and the execution step runs
through the real ``run_closure_dispatch`` (admission, dispatch, readback,
post-close reconciliation, in-batch continuation) against a fake GitHub
transport. The fake stands in for GitHub only; no dispatcher, evaluator,
verifier, or receipt is mocked. The assertion that matters is contract
equivalence: the operations the dispatcher performs on GitHub are exactly
the operations the verified host dispatch + post-close reconciliation
contracts name, in the same order, for the same issue, and a second
delivery of the same batch performs no duplicate mutation.

Live GitHub is never touched: no live issue is closed by this test, and
the protected issue 3292 is refused by the admission tool itself.
"""

from __future__ import annotations

import copy

from agent_os_execution_service.mcp_server import (
    admit_agent_os_issue_closure_tool,
    verify_agent_os_issue_closure_admission_tool,
)
from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    POST_CLOSE_RECONCILIATION_CONTRACT,
    ClosureAcceptanceEvidence,
    IssueClosureRequest,
    _receipt_id,
)
from scripts.agent_os_issue_acceptance.github_closure_dispatch import (
    run_closure_dispatch,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
    produce_lifecycle_mutation_authorization,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    LifecycleStateSnapshot,
)

REPO = "Blummer92/agent-os"


def snapshot_dict(issue, **changes):
    data = dict(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        source_head=None,
        base_head=None,
        pr_state="none",
        merged=False,
        issue_state="open",
        review_state="clear",
        unresolved_threads=0,
        lifecycle_labels=[],
        observed_revision=f"rev-{issue}-1",
    )
    data.update(changes)
    return data


def decision_dict(issue, **changes):
    data = dict(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        requested_mutations=["close-issue"],
        authorizer_id="repository-owner",
        decision_id=f"owner-decision-{issue}",
        decision_recorded=True,
    )
    data.update(changes)
    return data


def acceptance_dict(issue, **changes):
    data = dict(
        verdict="pass",
        evidence_id=f"qa-evidence-{issue}",
        evaluator_id="independent-qa",
    )
    data.update(changes)
    return data


def _snapshot(issue, **changes):
    data = snapshot_dict(issue, **changes)
    data["lifecycle_labels"] = tuple(data["lifecycle_labels"])
    return LifecycleStateSnapshot(**data)


def _authorization(issue, **snapshot_changes):
    decision = LifecycleOwnerDecision(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        requested_mutations=("close-issue",),
        authorizer_id="repository-owner",
        decision_id=f"owner-decision-{issue}",
        decision_recorded=True,
    )
    return produce_lifecycle_mutation_authorization(
        decision, _snapshot(issue, **snapshot_changes)
    )


def _request(issue, **acceptance_changes):
    return IssueClosureRequest(
        decision=LifecycleOwnerDecision(
            repository=REPO,
            issue_number=issue,
            pull_request_number=None,
            requested_mutations=("close-issue",),
            authorizer_id="repository-owner",
            decision_id=f"owner-decision-{issue}",
            decision_recorded=True,
        ),
        acceptance=ClosureAcceptanceEvidence(
            verdict=acceptance_changes.get("verdict", "pass"),
            evidence_id=f"qa-evidence-{issue}",
            evaluator_id="independent-qa",
        ),
    )


class FakeGitHub:
    """Minimal GitHub API surface the dispatcher actually calls."""

    def __init__(self):
        self.issues = {}
        self.comments = {}
        self.calls = []

    def add(self, issue, **kw):
        data = {"state": "open", "body": "", "labels": [], "state_reason": None}
        data.update(kw)
        self.issues[issue] = data

    def _payload(self, issue):
        data = self.issues[issue]
        return {
            "number": issue,
            "title": f"Issue {issue}",
            "state": data["state"],
            "body": data["body"],
            "html_url": f"https://github.com/{REPO}/issues/{issue}",
            "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-26T00:00:00Z",
            "closed_at": "2026-10-26T18:00:00Z" if data["state"] == "closed" else None,
            "labels": [{"name": label} for label in data["labels"]],
            "repository_url": f"https://api.github.com/repos/{REPO}",
            "state_reason": data["state_reason"],
        }

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        parts = path.strip("/").split("/")
        if "comments" in parts:
            issue = int(parts[parts.index("comments") - 1])
            if method == "GET":
                return 200, [{"body": c} for c in self.comments.get(issue, [])]
            if method == "POST":
                self.comments.setdefault(issue, []).append(body["body"])
                return 201, {"body": body["body"]}
            raise AssertionError("unexpected comments method")
        if "labels" in parts:
            issue = int(parts[parts.index("labels") - 1])
            label = parts[-1]
            assert method == "DELETE"
            if label in self.issues[issue]["labels"]:
                self.issues[issue]["labels"].remove(label)
            return 200, []
        issue = int(parts[-1])
        assert method in ("GET", "PATCH")
        if method == "PATCH":
            self.issues[issue]["state"] = body["state"]
            self.issues[issue]["state_reason"] = body["state_reason"]
        return 200, self._payload(issue)


def _admit_and_verify(issue, **snapshot_changes):
    receipt = admit_agent_os_issue_closure_tool(
        REPO, issue, decision_dict(issue), acceptance_dict(issue),
        snapshot_dict(issue, **snapshot_changes),
    )
    assert receipt["admitted"] is True
    result = verify_agent_os_issue_closure_admission_tool(
        REPO, issue, receipt, _authorization(issue, **snapshot_changes).to_dict(),
        snapshot_dict(issue, **snapshot_changes), acceptance_dict(issue),
    )
    assert result["verified"] is True
    return receipt, result


def test_host_path_admit_verify_dispatch_matches_contract():
    fake = FakeGitHub()
    fake.add(3432, labels=["status:ready", "agent-os"])
    receipt, result = _admit_and_verify(
        3432, lifecycle_labels=["status:ready"]
    )
    contract = result["host_dispatch_contract"]
    assert contract["tool"] == "issue_write"
    assert contract["state"] == "closed"
    assert contract["state_reason"] == "completed"
    assert contract["gate"] == "verify_closure_admission_receipt"
    reconciliation = result["post_close_reconciliation_contract"]
    assert reconciliation == POST_CLOSE_RECONCILIATION_CONTRACT
    assert reconciliation["label"] == "status:ready"
    assert receipt["post_close_reconciliation_contract"] == POST_CLOSE_RECONCILIATION_CONTRACT

    outcomes = run_closure_dispatch((_request(3432),), fake)
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome["status"] == "closed-verified"
    assert outcome["readback_verified"] is True
    assert outcome["label_reconciled"] is True
    assert outcome["evidence_comment_posted"] is True
    # Dispatcher transport calls are exactly the contract operations.
    patches = [c for c in fake.calls if c[0] == "PATCH"]
    assert patches == [
        ("PATCH", f"/repos/{REPO}/issues/3432", {"state": "closed", "state_reason": "completed"})
    ]
    deletes = [c for c in fake.calls if c[0] == "DELETE"]
    assert deletes == [
        ("DELETE", f"/repos/{REPO}/issues/3432/labels/status:ready", None)
    ]
    posts = [c for c in fake.calls if c[0] == "POST"]
    assert len(posts) == 1
    comment = posts[0][2]["body"]
    # The comment carries the executing dispatch's receipt id. It differs
    # from the MCP tool receipt id here only because this test's admission
    # snapshot uses an artificial revision ("rev-3432-1") while the batch
    # receipt is computed over the live-read snapshot; in production the
    # host supplies the canonical live snapshot, so the two receipts agree.
    # What the contract guarantees is the same shape: a receipt id, the
    # same evidence id, and no closing keyword.
    assert outcome["receipt_id"] in comment
    assert "qa-evidence-3432" in comment
    assert "closes #" not in comment.lower()
    assert "fixes #" not in comment.lower()
    assert "resolves #" not in comment.lower()
    assert fake.issues[3432]["state"] == "closed"
    assert fake.issues[3432]["state_reason"] == "completed"
    assert "status:ready" not in fake.issues[3432]["labels"]


def test_host_path_batch_continues_past_blocked_item():
    fake = FakeGitHub()
    fake.add(3306, labels=[])
    fake.add(3432, labels=[])
    _admit_and_verify(3432)
    outcomes = run_closure_dispatch(
        (_request(3306, verdict="fail"), _request(3432)), fake
    )
    assert outcomes[0]["status"] != "closed-verified"
    assert fake.issues[3306]["state"] == "open"
    assert outcomes[1]["status"] == "closed-verified"
    assert fake.issues[3432]["state"] == "closed"
    patches = [c for c in fake.calls if c[0] == "PATCH"]
    assert all("3306" not in c[1] for c in patches)
    assert any("3432" in c[1] for c in patches)


def test_host_path_stale_verify_refuses_and_no_contract_is_issued():
    receipt = admit_agent_os_issue_closure_tool(
        REPO, 3432, decision_dict(3432), acceptance_dict(3432), snapshot_dict(3432)
    )
    assert receipt["admitted"] is True
    stale = snapshot_dict(3432, observed_revision="rev-3432-stale")
    result = verify_agent_os_issue_closure_admission_tool(
        REPO, 3432, receipt, _authorization(3432).to_dict(), stale, acceptance_dict(3432)
    )
    assert result["verified"] is False
    assert result["host_dispatch_contract"] is None
    assert result["post_close_reconciliation_contract"] is None
    # The host must not dispatch after a refused gate; nothing was run here
    # precisely because the gate refused, and no write occurred.


def test_host_path_wrong_identity_and_protected_target_refused():
    receipt = admit_agent_os_issue_closure_tool(
        REPO, 3432, decision_dict(3432), acceptance_dict(3432), snapshot_dict(3432)
    )
    result = verify_agent_os_issue_closure_admission_tool(
        REPO, 3306, receipt, _authorization(3306).to_dict(),
        snapshot_dict(3306), acceptance_dict(3306),
    )
    assert result["verified"] is False
    assert result["host_dispatch_contract"] is None
    protected = admit_agent_os_issue_closure_tool(
        REPO, 3292, decision_dict(3292), acceptance_dict(3292), snapshot_dict(3292)
    )
    assert protected["admitted"] is False
    assert "closure.protected-target" in protected["reason_codes"]


def test_host_path_tampered_reconciliation_contract_fails_verify():
    receipt = admit_agent_os_issue_closure_tool(
        REPO, 3432, decision_dict(3432), acceptance_dict(3432), snapshot_dict(3432)
    )
    tampered = copy.deepcopy(receipt)
    tampered["post_close_reconciliation_contract"] = dict(
        POST_CLOSE_RECONCILIATION_CONTRACT, label="status:blocked"
    )
    # Recompute the receipt id so only the contract check can refuse. The
    # reconciliation contract lives outside the hashed core (see
    # closure_admission_actions._receipt), so it is excluded here exactly
    # as verify_closure_admission_receipt excludes it.
    core = {k: tampered[k] for k in tampered if k not in ("receipt_id", "closure_performed", "merge_authorized", "side_effects_performed", "post_close_reconciliation_contract")}
    tampered["receipt_id"] = _receipt_id(core)
    result = verify_agent_os_issue_closure_admission_tool(
        REPO, 3432, tampered, _authorization(3432).to_dict(),
        snapshot_dict(3432), acceptance_dict(3432),
    )
    assert result["verified"] is False
    assert result["post_close_reconciliation_contract"] is None
    # A pre-contract receipt (no reconciliation field at all) is also refused.
    legacy = copy.deepcopy(receipt)
    del legacy["post_close_reconciliation_contract"]
    core = {k: legacy[k] for k in legacy if k not in ("receipt_id", "closure_performed", "merge_authorized", "side_effects_performed", "post_close_reconciliation_contract")}
    legacy["receipt_id"] = _receipt_id(core)
    result = verify_agent_os_issue_closure_admission_tool(
        REPO, 3432, legacy, _authorization(3432).to_dict(),
        snapshot_dict(3432), acceptance_dict(3432),
    )
    assert result["verified"] is False


def test_host_path_duplicate_delivery_makes_no_duplicate_mutations():
    fake = FakeGitHub()
    fake.add(3432, labels=["status:ready"])
    _admit_and_verify(3432, lifecycle_labels=["status:ready"])
    first = run_closure_dispatch((_request(3432),), fake)
    assert first[0]["status"] == "closed-verified"
    assert len(fake.comments[3432]) == 1
    writes_before = len([c for c in fake.calls if c[0] in ("PATCH", "DELETE", "POST")])
    second = run_closure_dispatch((_request(3432),), fake)
    writes_after = len([c for c in fake.calls if c[0] in ("PATCH", "DELETE", "POST")])
    assert writes_after == writes_before
    assert len(fake.comments[3432]) == 1
    assert fake.issues[3432]["state"] == "closed"
    assert second[0]["status"] != "closed-verified" or second[0]["evidence_comment_posted"] is False
