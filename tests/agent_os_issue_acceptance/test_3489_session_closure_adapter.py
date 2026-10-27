"""Production-caller acceptance for the #3489 session closure adapter.

The adapter adds no evaluation logic: admission is canonical
``evaluate_issue_closure`` and the pre-write gate is canonical
``verify_closure_admission_receipt``. These tests prove the transfer
discipline instead: the exact operation sequence, the refusal cases with
zero unauthorized mutations, the no-blind-retry rules, and the MCP
manifest mapping. All GitHub interaction is through a fake transport;
no live issue, PR, or credential is touched. Issue 3292 appears only as
a synthetic fixture.
"""

import hashlib
import json
import subprocess
import sys

import pytest

from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    ClosureAcceptanceEvidence,
    IssueClosureRequest,
    evaluate_issue_closure,
)
from scripts.agent_os_issue_acceptance.github_closure_dispatch import (
    _completion_comment,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    LifecycleStateSnapshot,
)
from scripts.agent_os_issue_acceptance.session_closure_adapter import (
    FreshRead,
    QaEvidence,
    TransportUnavailable,
    TransportUncertain,
    build_plan,
    execute_batch,
    execute_plan,
    mcp_manifest,
    render_evidence_comment,
    verify_qa_evidence,
)

REPO = "Blummer92/agent-os"
BODY = "Synthetic issue body for offline proof only."
DIGEST = hashlib.sha256(BODY.encode()).hexdigest()
TRIGGER = "/agent-os close-admit 9876"
TRIGGER_HASH = hashlib.sha256(TRIGGER.encode()).hexdigest()
HEAD = "a" * 40


def snapshot(issue=9876, **changes):
    data = dict(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        source_head=None,
        base_head=None,
        pr_state="none",
        merged=False,
        issue_state="open",
        review_state="unknown",
        unresolved_threads=0,
        lifecycle_labels=("status:ready",),
        observed_revision=f"github-issue-v1:rev-{issue}-1",
    )
    data.update(changes)
    return LifecycleStateSnapshot(**data)


def decision(issue=9876, **changes):
    data = dict(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        requested_mutations=("close-issue",),
        authorizer_id="Blummer92",
        decision_id=f"owner-decision-{issue}",
        decision_recorded=True,
    )
    data.update(changes)
    return LifecycleOwnerDecision(**data)


def qa(issue=9876, **changes):
    data = dict(
        verdict="pass",
        evidence_id=f"qa-evidence-{issue}",
        evaluator_id="qa-test-agent",
        issue_number=issue,
        validated_head_sha=None,
        issue_body_digest=DIGEST,
        provenance="runtime_handoff",
        qa_session_ref="qa-session-synthetic",
        delivery_ref="qa-delivery-synthetic",
    )
    data.update(changes)
    return QaEvidence(**data)


def make_plan(issue=9876, **overrides):
    plan_kwargs = dict(
        decision=decision(issue),
        qa=qa(issue),
        snapshot=snapshot(issue),
        body_digest=DIGEST,
        delivery_id=f"delivery-{issue}",
        trigger_id=f"trigger-{issue}",
        trigger_body_hash=TRIGGER_HASH,
    )
    plan_kwargs.update(overrides)
    plan, reasons = build_plan(**plan_kwargs)
    assert plan is not None, reasons
    return plan


class FakeTransport:
    """Fake GitHub with an operation log and failure injection.

    ``read_overrides`` maps a 1-based fresh_read call index to field
    overrides (state, digest, revision, trigger, labels, comments).
    ``unavailable_reads`` maps call indexes that raise TransportUnavailable.
    """

    def __init__(self, issue=9876, **flags):
        self.issue = issue
        self.state = "open"
        self.state_reason = None
        self.labels = ["status:ready"]
        self.comments: list[str] = []
        self.trigger_body = TRIGGER
        self.digest = DIGEST
        self.revision = f"github-issue-v1:rev-{issue}-1"
        self.ops: list[tuple] = []
        self.read_count = 0
        self.read_overrides = flags.get("read_overrides", {})
        self.unavailable_reads = set(flags.get("unavailable_reads", ()))
        self.close_mode = flags.get("close_mode", "ok")  # ok|uncertain-landed|uncertain-open
        self.comment_mode = flags.get("comment_mode", "ok")
        self.label_mode = flags.get("label_mode", "ok")
        self.extra_label_at_final = flags.get("extra_label_at_final", False)

    def _snapshot(self):
        return snapshot(
            self.issue,
            issue_state=self.state,
            lifecycle_labels=tuple(self.labels),
            observed_revision=self.revision,
        )

    def fresh_read(self):
        self.read_count += 1
        self.ops.append(("read", self.read_count))
        if self.read_count in self.unavailable_reads:
            raise TransportUnavailable("injected")
        over = self.read_overrides.get(self.read_count, {})
        state = over.get("state", self.state)
        labels = list(over.get("labels", self.labels))
        if self.extra_label_at_final and self.read_count >= 3 and "extra:label" not in labels:
            labels.append("extra:label")
        return FreshRead(
            snapshot=snapshot(
                self.issue,
                issue_state=state,
                lifecycle_labels=tuple(labels),
                observed_revision=over.get("revision", self.revision),
            ),
            body_digest=over.get("digest", self.digest),
            trigger_body=over.get("trigger", self.trigger_body),
            labels=tuple(labels),
            comment_bodies=tuple(over.get("comments", self.comments)),
            state_reason=over.get(
                "state_reason",
                self.state_reason if self.state_reason is not None
                else ("completed" if state == "closed" else None),
            ),
        )

    def close(self):
        self.ops.append(("close", {"state": "closed", "state_reason": "completed"}))
        if self.close_mode == "uncertain-landed":
            self.state, self.state_reason = "closed", "completed"
            raise TransportUncertain("injected")
        if self.close_mode == "uncertain-open":
            raise TransportUncertain("injected")
        self.state, self.state_reason = "closed", "completed"

    def remove_label(self, label):
        self.ops.append(("remove_label", label))
        assert label == "status:ready"
        if self.label_mode == "uncertain-landed":
            self.labels = [item for item in self.labels if item != label]
            raise TransportUncertain("injected")
        if self.label_mode == "uncertain-present":
            raise TransportUncertain("injected")
        self.labels = [item for item in self.labels if item != label]

    def list_comments(self):
        self.ops.append(("list_comments",))
        return tuple(self.comments)

    def post_comment(self, body):
        self.ops.append(("post_comment", body))
        if self.comment_mode == "uncertain-landed":
            self.comments.append(body)
            raise TransportUncertain("injected")
        if self.comment_mode == "uncertain-absent":
            raise TransportUncertain("injected")
        self.comments.append(body)

    def write_ops(self):
        return [op for op in self.ops if op[0] in ("close", "remove_label", "post_comment")]


# --- Plan / QA gates -------------------------------------------------------

def test_plan_admitted_and_receipt_matches_canonical_evaluation():
    plan = make_plan()
    direct = evaluate_issue_closure(
        IssueClosureRequest(
            decision=decision(),
            acceptance=ClosureAcceptanceEvidence(
                verdict="pass", evidence_id="qa-evidence-9876", evaluator_id="qa-test-agent",
                issue_number=9876, validated_head_sha=None,
            ),
        ),
        snapshot(),
        current_issue_body_digest=DIGEST,
    )
    assert plan.receipt == direct
    assert plan.receipt_id == direct["receipt_id"]


def test_comment_body_matches_dispatcher_oracle():
    plan = make_plan()
    assert plan.comment_body == _completion_comment(
        repository=REPO, issue_number=9876, evidence_id="qa-evidence-9876",
        evaluator_id="qa-test-agent", receipt_id=plan.receipt_id,
    )
    assert render_evidence_comment(
        repository=REPO, issue_number=9876, evidence_id="qa-evidence-9876",
        evaluator_id="qa-test-agent", receipt_id=plan.receipt_id,
    ) == plan.comment_body


@pytest.mark.parametrize("provenance", ["caller-string", "file", "artifact", "check-run", "status", ""])
def test_non_handoff_qa_provenance_refused(provenance):
    plan, reasons = build_plan(
        decision=decision(), qa=qa(provenance=provenance), snapshot=snapshot(),
        body_digest=DIGEST, delivery_id="d", trigger_id="t", trigger_body_hash=TRIGGER_HASH,
    )
    assert plan is None
    assert "session-closure.qa-provenance-untrusted" in reasons


def test_qa_handoff_without_session_reference_refused():
    plan, reasons = build_plan(
        decision=decision(), qa=qa(qa_session_ref=""), snapshot=snapshot(),
        body_digest=DIGEST, delivery_id="d", trigger_id="t", trigger_body_hash=TRIGGER_HASH,
    )
    assert plan is None
    assert "session-closure.qa-handoff-unreferenced" in reasons


def test_owner_impersonation_refused():
    plan, reasons = build_plan(
        decision=decision(), qa=qa(evaluator_id="Blummer92"), snapshot=snapshot(),
        body_digest=DIGEST, delivery_id="d", trigger_id="t", trigger_body_hash=TRIGGER_HASH,
    )
    assert plan is None
    assert "session-closure.qa-not-independent" in reasons


def test_aggregate_substituted_for_qa_refused():
    plan, reasons = build_plan(
        decision=decision(), qa=qa(evaluator_id="agent-os/authoritative-aggregate"),
        snapshot=snapshot(), body_digest=DIGEST, delivery_id="d",
        trigger_id="t", trigger_body_hash=TRIGGER_HASH,
    )
    assert plan is None
    assert "session-closure.qa-evaluator-not-qa" in reasons


@pytest.mark.parametrize("verdict", ["fail", "missing"])
def test_non_pass_qa_refused(verdict):
    plan, reasons = build_plan(
        decision=decision(), qa=qa(verdict=verdict), snapshot=snapshot(),
        body_digest=DIGEST, delivery_id="d", trigger_id="t", trigger_body_hash=TRIGGER_HASH,
    )
    assert plan is None
    assert "session-closure.qa-not-passed" in reasons


def test_conflicting_qa_record_refused():
    conflict = qa(verdict="fail")
    plan, reasons = build_plan(
        decision=decision(), qa=qa(), snapshot=snapshot(), body_digest=DIGEST,
        delivery_id="d", trigger_id="t", trigger_body_hash=TRIGGER_HASH,
        other_qa_records=(conflict,),
    )
    assert plan is None
    assert "session-closure.qa-conflict" in reasons


def test_wrong_issue_refused():
    plan, _ = build_plan(
        decision=decision(), qa=qa(issue_number=1111), snapshot=snapshot(),
        body_digest=DIGEST, delivery_id="d", trigger_id="t", trigger_body_hash=TRIGGER_HASH,
    )
    assert plan is None


def test_wrong_head_refused():
    plan, _ = build_plan(
        decision=decision(), qa=qa(validated_head_sha=HEAD),
        snapshot=snapshot(source_head="b" * 40), body_digest=DIGEST,
        delivery_id="d", trigger_id="t", trigger_body_hash=TRIGGER_HASH,
    )
    assert plan is None


def test_wrong_body_digest_refused():
    plan, _ = build_plan(
        decision=decision(), qa=qa(issue_body_digest="0" * 64), snapshot=snapshot(),
        body_digest=DIGEST, delivery_id="d", trigger_id="t", trigger_body_hash=TRIGGER_HASH,
    )
    assert plan is None


def test_protected_target_fixture_refused():
    plan, reasons = build_plan(
        decision=decision(3292), qa=qa(3292), snapshot=snapshot(3292),
        body_digest=DIGEST, delivery_id="d", trigger_id="t", trigger_body_hash=TRIGGER_HASH,
    )
    assert plan is None
    assert "closure.protected-target" in reasons


def test_missing_trigger_refused():
    plan, reasons = build_plan(
        decision=decision(), qa=qa(), snapshot=snapshot(), body_digest=DIGEST,
        delivery_id="d", trigger_id="", trigger_body_hash="",
    )
    assert plan is None
    assert "session-closure.trigger-missing" in reasons


def test_stale_satisfaction_refused_at_plan():
    stale = {
        "repository": REPO, "issue_number": 9876, "issue_body_digest": "0" * 64,
        "status": "complete",
        "criteria": [{"index": 1, "identity": "c1", "disposition": "satisfied",
                      "reason_code": "qa-pass", "evidence": ["qa-evidence-9876"]}],
    }
    plan, reasons = build_plan(
        decision=decision(), qa=qa(), snapshot=snapshot(), body_digest=DIGEST,
        satisfaction=stale, delivery_id="d", trigger_id="t", trigger_body_hash=TRIGGER_HASH,
    )
    assert plan is None
    assert "closure.satisfaction-stale" in reasons


# --- Executor: exact sequence and refusal handling -------------------------

def test_full_sequence_exact_ops_and_outcome():
    plan = make_plan()
    fake = FakeTransport()
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "closed-verified"
    assert [op[0] for op in fake.ops] == [
        "read", "close", "read", "remove_label", "list_comments", "post_comment", "read",
    ]
    close_ops = [op for op in fake.ops if op[0] == "close"]
    assert close_ops == [("close", {"state": "closed", "state_reason": "completed"})]
    assert fake.state == "closed" and fake.labels == [] and len(fake.comments) == 1
    assert plan.receipt_id in fake.comments[0]
    assert "closes #" not in fake.comments[0].lower()


def test_duplicate_delivery_with_comment_and_no_label_zero_writes():
    plan = make_plan()
    fake = FakeTransport(read_overrides={1: {"state": "closed", "labels": [], "comments": [plan.comment_body]}})
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "already-closed-verified"
    assert fake.write_ops() == []


def test_duplicate_delivery_with_comment_completes_leftover_label():
    plan = make_plan()
    fake = FakeTransport()
    fake.state, fake.state_reason = "closed", "completed"
    fake.comments = [plan.comment_body]
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "already-closed-verified"
    assert [op[0] for op in fake.ops] == ["read", "remove_label", "read"]
    assert fake.labels == []


def test_duplicate_delivery_with_comment_and_stuck_label_flagged():
    plan = make_plan()
    fake = FakeTransport(label_mode="uncertain-present")
    fake.state, fake.state_reason = "closed", "completed"
    fake.comments = [plan.comment_body]
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "already-closed-verified-label-reconciliation-required"


def test_duplicate_delivery_without_comment_completes_label_and_comment():
    plan = make_plan()
    fake = FakeTransport()
    fake.state, fake.state_reason = "closed", "completed"
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "already-closed-comment-completed"
    assert [op[0] for op in fake.write_ops()] == ["remove_label", "post_comment"]


def test_repository_not_pinned_refused():
    plan, reasons = build_plan(
        decision=decision(repository="Other/repo"),
        qa=qa(),
        snapshot=snapshot(repository="Other/repo"),
        body_digest=DIGEST, delivery_id="d", trigger_id="t", trigger_body_hash=TRIGGER_HASH,
    )
    assert plan is None
    assert "session-closure.repository-not-pinned" in reasons


@pytest.mark.parametrize(
    "override,reason",
    [
        ({"digest": "0" * 64}, "session-closure.body-digest-drift"),
        ({"revision": "github-issue-v1:rev-other"}, "session-closure.revision-drift"),
        ({"trigger": "/agent-os close-admit 9876 (edited)"}, "session-closure.trigger-mismatch"),
    ],
)
def test_prewrite_drift_refuses_with_zero_writes(override, reason):
    plan = make_plan()
    fake = FakeTransport(read_overrides={1: override})
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "refused"
    assert reason in outcome["reason_codes"]
    assert fake.write_ops() == []


def test_uncertain_close_landed_proceeds_without_second_close():
    plan = make_plan()
    fake = FakeTransport(close_mode="uncertain-landed")
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "closed-verified"
    assert sum(1 for op in fake.ops if op[0] == "close") == 1


def test_uncertain_close_not_landed_unresolved_no_retry():
    plan = make_plan()
    fake = FakeTransport(close_mode="uncertain-open")
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "unresolved"
    assert "session-closure.close-uncertain" in outcome["reason_codes"]
    assert sum(1 for op in fake.ops if op[0] == "close") == 1


def test_uncertain_comment_landed_proceeds_without_repost():
    plan = make_plan()
    fake = FakeTransport(comment_mode="uncertain-landed")
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "closed-verified"
    assert sum(1 for op in fake.ops if op[0] == "post_comment") == 1


def test_uncertain_comment_absent_unresolved_no_repost():
    plan = make_plan()
    fake = FakeTransport(comment_mode="uncertain-absent")
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "unresolved"
    assert "session-closure.comment-uncertain" in outcome["reason_codes"]
    assert sum(1 for op in fake.ops if op[0] == "post_comment") == 1


def test_uncertain_label_landed_is_verified():
    plan = make_plan()
    fake = FakeTransport(label_mode="uncertain-landed")
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "closed-verified"


def test_uncertain_label_present_flagged_closure_stays_verified():
    plan = make_plan()
    fake = FakeTransport(label_mode="uncertain-present")
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "closed-verified-label-reconciliation-required"
    assert len(fake.comments) == 1


def test_concurrent_label_change_only_status_ready_removed():
    # The harness models the concurrent label as a readback observation:
    # the final fresh read reports an extra label that was not present at
    # plan time. The dedicated removal must touch only status:ready, and
    # the executor must still verify closure rather than fail on the
    # unrelated label.
    plan = make_plan()
    fake = FakeTransport(extra_label_at_final=True)
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "closed-verified"
    assert [op for op in fake.ops if op[0] == "remove_label"] == [("remove_label", "status:ready")]
    assert "status:ready" not in fake.labels


def test_missing_post_close_readback_is_closed_unverified_not_verified():
    plan = make_plan()
    fake = FakeTransport(unavailable_reads={2})
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "closed-unverified"
    assert "session-closure.readback-unavailable" in outcome["reason_codes"]


def test_prewrite_read_unavailable_zero_writes():
    plan = make_plan()
    fake = FakeTransport(unavailable_reads={1})
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "unresolved"
    assert fake.write_ops() == []


def test_blocked_item_does_not_stop_eligible_item():
    blocked_plan = make_plan()
    blocked_fake = FakeTransport(read_overrides={1: {"digest": "0" * 64}})
    eligible_plan = make_plan()
    eligible_fake = FakeTransport()
    outcomes = execute_batch([(blocked_plan, blocked_fake), (eligible_plan, eligible_fake)])
    assert outcomes[0]["status"] == "refused"
    assert blocked_fake.write_ops() == []
    assert outcomes[1]["status"] == "closed-verified"
    assert eligible_fake.state == "closed"


# --- Manifest mapping ------------------------------------------------------

def test_manifest_uses_only_connected_tools_and_no_delete():
    plan = make_plan()
    manifest = mcp_manifest(plan)
    tools = {step["tool"] for step in manifest}
    assert tools <= {"issue_read", "issue_write", "add_issue_comment"}
    assert "issue_write" in tools and "add_issue_comment" in tools
    assert all(step["params"]["owner"] == "Blummer92" and step["params"]["repo"] == "agent-os"
               for step in manifest)
    close_steps = [s for s in manifest if s["action"] == "close-issue"]
    assert len(close_steps) == 1
    assert close_steps[0]["params"]["state"] == "closed"
    assert close_steps[0]["params"]["state_reason"] == "completed"
    assert set(close_steps[0]["params"]) == {
        "owner", "repo", "issue_number", "state", "state_reason",
    }
    assert not any("DELETE" in json.dumps(step) for step in manifest)
    label_steps = [s for s in manifest if "label" in s["action"]]
    assert any(s["tool"] == "issue_write" for s in label_steps)


def test_manifest_derives_owner_repo_from_plan_including_label_step():
    from dataclasses import replace

    plan = make_plan()
    foreign = replace(plan, repository="Other/repo")
    manifest = mcp_manifest(foreign)
    assert all(step["params"]["owner"] == "Other" and step["params"]["repo"] == "repo"
               for step in manifest)
    label_step = [s for s in manifest if s["action"] == "label-replacement"]
    assert len(label_step) == 1
    assert label_step[0]["params"]["owner"] == "Other"


def test_duplicate_with_wrong_close_reason_is_unverified():
    plan = make_plan()
    fake = FakeTransport(read_overrides={1: {"state": "closed", "labels": [], "comments": [plan.comment_body], "state_reason": "not_planned"}})
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "closed-unverified"


def test_manifest_without_label_requirement_skips_label_steps():
    plan = make_plan(snapshot=snapshot(lifecycle_labels=()))
    manifest = mcp_manifest(plan)
    assert not any("label" in step["action"] for step in manifest)


# --- CLI -------------------------------------------------------------------

def _cli_payload(**qa_changes):
    qa_data = dict(
        verdict="pass", evidence_id="qa-evidence-9876", evaluator_id="qa-test-agent",
        issue_number=9876, validated_head_sha=None, issue_body_digest=DIGEST,
        provenance="runtime_handoff", qa_session_ref="s", delivery_ref="d",
    )
    qa_data.update(qa_changes)
    return {
        "decision": {
            "repository": REPO, "issue_number": 9876, "pull_request_number": None,
            "requested_mutations": ["close-issue"], "authorizer_id": "Blummer92",
            "decision_id": "owner-decision-9876", "decision_recorded": True,
        },
        "qa": qa_data,
        "snapshot": {
            "repository": REPO, "issue_number": 9876, "pull_request_number": None,
            "source_head": None, "base_head": None, "pr_state": "none", "merged": False,
            "issue_state": "open", "review_state": "unknown", "unresolved_threads": 0,
            "lifecycle_labels": ["status:ready"], "observed_revision": "github-issue-v1:rev-9876-1",
        },
        "body_digest": DIGEST, "delivery_id": "d", "trigger_id": "t",
        "trigger_body_hash": TRIGGER_HASH,
    }


def test_cli_plan_prints_manifest_and_refuses_forgery():
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.agent_os_issue_acceptance.session_closure_adapter", "plan"],
        input=json.dumps(_cli_payload()), capture_output=True, text=True, cwd="/tmp/agent-os-fresh",
    )
    assert proc.returncode == 0, proc.stderr
    printed = json.loads(proc.stdout)
    assert printed["admitted"] is True
    assert any(step["action"] == "close-issue" for step in printed["manifest"])
    proc2 = subprocess.run(
        [sys.executable, "-m", "scripts.agent_os_issue_acceptance.session_closure_adapter", "plan"],
        input=json.dumps(_cli_payload(provenance="file")), capture_output=True, text=True,
        cwd="/tmp/agent-os-fresh",
    )
    assert proc2.returncode == 2
    refused = json.loads(proc2.stdout)
    assert refused["admitted"] is False
    assert "manifest" not in refused
