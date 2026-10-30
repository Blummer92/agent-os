"""Production-caller acceptance for the #3489 session closure adapter.

The adapter adds no evaluation logic: admission is canonical
``evaluate_issue_closure`` and the pre-write gate is canonical
``verify_closure_admission_receipt``. These tests prove the transfer
discipline instead, under the repaired authority model:

* F1: no JSON/CLI path exists; admission requires host-registry tokens
  (owner grant + registered QA delivery). Forged tokens, forged fields,
  and unregistered records refuse with zero mutation calls.
* F2: the production entry point (``execute_session_closure``) drives
  the executor; the manifest is an audit record whose steps match the
  mocked MCP tool trace exactly.
* F3: already-closed issues receive zero mutations by default; recovery
  needs a separate grant, never re-closes, removes labels only
  surgically, and never substitutes labels replacement.

All GitHub interaction is through a fake transport; no live issue, PR,
or credential is touched. Issue 3292 appears only as a synthetic fixture.
"""

import hashlib
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    ClosureAcceptanceEvidence,
    IssueClosureRequest,
    evaluate_issue_closure,
)
from scripts.agent_os_issue_acceptance.github_closure_dispatch import (
    _completion_comment,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    LifecycleStateSnapshot,
)
from scripts.agent_os_issue_acceptance import session_closure_adapter as adapter
from scripts.agent_os_issue_acceptance.session_closure_adapter import (
    FreshRead,
    HostRegistry,
    LabelRemovalUnsupported,
    QaRecord,
    TransportUnavailable,
    TransportUncertain,
    build_plan,
    execute_batch,
    execute_plan,
    execute_session_closure,
    mcp_manifest,
)

REPO = "Blummer92/agent-os"
BODY = "Synthetic issue body for offline proof only."
DIGEST = hashlib.sha256(BODY.encode()).hexdigest()
TRIGGER = "/agent-os close-admit 9876"
HEAD = "a" * 40
OWNER = "Blummer92"


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


def qa_record(issue=9876, **changes):
    data = dict(
        verdict="pass",
        evidence_id=f"qa-evidence-{issue}",
        evaluator_id="qa-test-agent",
        issue_number=issue,
        validated_head_sha=None,
        issue_body_digest=DIGEST,
        delivery_ref=f"qa-delivery-{issue}",
    )
    data.update(changes)
    return QaRecord(**data)


class Setup:
    """One host session: fresh registry with a valid grant + QA delivery."""

    def __init__(self, issue=9876, **qa_changes):
        self.issue = issue
        self.registry = HostRegistry()
        self.grant = self.registry.grant_owner_closure(
            repository=REPO, issue_number=issue, authorizer_id=OWNER
        )
        self.qa_token = self.registry.register_qa_delivery(qa_record(issue, **qa_changes))
        self.snapshot = snapshot(issue)

    def plan_kwargs(self, **overrides):
        kwargs = dict(
            registry=self.registry,
            owner_grant_token=self.grant.token,
            qa_delivery_token=self.qa_token,
            snapshot=self.snapshot,
            body_digest=DIGEST,
            trigger_id=f"trigger-{self.issue}",
            trigger_body=TRIGGER,
        )
        kwargs.update(overrides)
        return kwargs

    def make_plan(self, **overrides):
        plan, reasons = build_plan(**self.plan_kwargs(**overrides))
        assert plan is not None, reasons
        return plan

    def run_entry(self, transport, **overrides):
        kwargs = dict(
            registry=self.registry,
            owner_grant_token=self.grant.token,
            qa_delivery_token=self.qa_token,
            snapshot=self.snapshot,
            body_digest=DIGEST,
            trigger_id=f"trigger-{self.issue}",
            trigger_body=TRIGGER,
            transport=transport,
        )
        kwargs.update(overrides)
        return execute_session_closure(**kwargs)


class FakeTransport:
    """Fake GitHub with MCP tool-call log and failure injection.

    ``read_overrides`` maps a 1-based fresh_read call index to field
    overrides (state, digest, revision, trigger, labels, comments,
    state_reason). ``unavailable_reads`` maps call indexes that raise
    TransportUnavailable. ``surgical`` selects whether this host's
    catalog attaches remove_issue_label.
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
        self.tool_calls: list[tuple] = []
        self.read_count = 0
        self.read_overrides = flags.get("read_overrides", {})
        self.unavailable_reads = set(flags.get("unavailable_reads", ()))
        self.close_mode = flags.get("close_mode", "ok")  # ok|uncertain-landed|uncertain-open
        self.comment_mode = flags.get("comment_mode", "ok")  # ok|uncertain-landed|uncertain-open
        self.label_mode = flags.get("label_mode", "ok")  # ok|uncertain-landed|uncertain-present|unsupported
        self.supports_surgical_label_removal = flags.get("surgical", True)
        self.concurrent_label_at_read = flags.get("concurrent_label_at_read", None)
        self.source_head = flags.get("source_head", None)

    def _params(self, extra=None):
        params = {"owner": "Blummer92", "repo": "agent-os", "issue_number": self.issue}
        if extra:
            params.update(extra)
        return params

    def fresh_read(self):
        self.read_count += 1
        if self.read_count in self.unavailable_reads:
            raise TransportUnavailable("read unavailable")
        over = self.read_overrides.get(self.read_count, {})
        state = over.get("state", self.state)
        if self.concurrent_label_at_read == self.read_count and "type:bug" not in self.labels:
            # A concurrent writer adds an unrelated label to stored state.
            self.labels.append("type:bug")
        labels = list(over.get("labels", self.labels))
        self.ops.append(("read",))
        self.tool_calls.append(("issue_read", "get", self._params()))
        self.tool_calls.append(("issue_read", "get_comments", self._params()))
        self.tool_calls.append(("issue_read", "get_labels", self._params()))
        return FreshRead(
            snapshot=snapshot(
                self.issue,
                issue_state=state,
                lifecycle_labels=tuple(labels),
                observed_revision=over.get("revision", self.revision),
                source_head=self.source_head,
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
        self.ops.append(("close",))
        self.tool_calls.append(
            ("issue_write", "update", self._params({"state": "closed", "state_reason": "completed"}))
        )
        if self.close_mode == "uncertain-landed":
            self.state, self.state_reason = "closed", "completed"
            raise TransportUncertain("close uncertain, landed")
        if self.close_mode == "uncertain-open":
            raise TransportUncertain("close uncertain, not landed")
        self.state, self.state_reason = "closed", "completed"

    def remove_issue_label(self, label):
        if not self.supports_surgical_label_removal or self.label_mode == "unsupported":
            raise LabelRemovalUnsupported("no surgical label removal on this host")
        self.ops.append(("remove_issue_label", label))
        self.tool_calls.append(("remove_issue_label", "remove", self._params({"name": label})))
        if self.label_mode == "uncertain-landed":
            if label in self.labels:
                self.labels.remove(label)
            raise TransportUncertain("label removal uncertain, landed")
        if self.label_mode == "uncertain-present":
            raise TransportUncertain("label removal uncertain, still present")
        if label in self.labels:
            self.labels.remove(label)

    def list_comments(self):
        self.ops.append(("list_comments",))
        self.tool_calls.append(("issue_read", "get_comments", self._params()))
        return tuple(self.comments)

    def post_comment(self, body):
        self.ops.append(("post_comment",))
        self.tool_calls.append(("add_issue_comment", "add", self._params({"body": body})))
        if self.comment_mode == "uncertain-landed":
            self.comments.append(body)
            raise TransportUncertain("comment uncertain, landed")
        if self.comment_mode == "uncertain-open":
            raise TransportUncertain("comment uncertain, not landed")
        self.comments.append(body)

    def write_ops(self):
        return [op for op in self.ops if op[0] in ("close", "remove_issue_label", "post_comment")]

    def mutation_tool_calls(self):
        return [t for t in self.tool_calls if t[0] in ("issue_write", "remove_issue_label", "add_issue_comment")]


# ---------------------------------------------------------------- F1

def test_no_json_or_cli_authority_path_exists():
    assert not hasattr(adapter, "_plan_from_json")
    assert not hasattr(adapter, "main")
    assert not hasattr(adapter, "QaEvidence")
    # The module exposes no JSON parsing entry point at all.
    import inspect

    source = Path(adapter.__file__).read_text()
    assert "json.load" not in source
    assert "sys.argv" not in source


def test_forged_owner_grant_token_refused_with_zero_mutations():
    setup = Setup()
    fake = FakeTransport()
    outcome = setup.run_entry(fake, owner_grant_token="f" * 32)
    assert outcome["status"] == "refused"
    assert "session-closure.owner-grant-unknown" in outcome["reason_codes"]
    assert fake.mutation_tool_calls() == []


def test_forged_qa_delivery_token_refused_with_zero_mutations():
    setup = Setup()
    fake = FakeTransport()
    outcome = setup.run_entry(fake, qa_delivery_token="e" * 32)
    assert outcome["status"] == "refused"
    assert "session-closure.qa-delivery-unknown" in outcome["reason_codes"]
    assert fake.mutation_tool_calls() == []


def test_unregistered_qa_record_fields_cannot_admit():
    # A perfectly formed QA record that the host never registered is
    # worthless: there is no field-based path into admission.
    setup = Setup()
    fake = FakeTransport()
    unregistered = qa_record()
    # The entry point takes tokens, not records; passing a forged token
    # that merely names the record refuses.
    outcome = setup.run_entry(fake, qa_delivery_token="qa-delivery-9876")
    assert outcome["status"] == "refused"
    assert fake.mutation_tool_calls() == []
    assert unregistered.evidence_id == "qa-evidence-9876"


def test_forged_owner_fields_have_no_code_path():
    # Old CLI payload fields (decision_recorded, authorizer_id, verdict,
    # provenance, qa_session_ref, delivery_ref) are not parameters of
    # build_plan or the entry point at all.
    import inspect

    params = set(inspect.signature(build_plan).parameters)
    assert not {"decision", "qa", "decision_recorded", "provenance"} & params
    entry_params = set(inspect.signature(execute_session_closure).parameters)
    assert "owner_grant_token" in entry_params and "qa_delivery_token" in entry_params


@pytest.mark.parametrize("field,value,reason", [
    ("verdict", "fail", "session-closure.qa-not-passed"),
    ("evaluator_id", OWNER, "session-closure.qa-not-independent"),
    ("evaluator_id", "agent-os/authoritative-aggregate", "session-closure.qa-evaluator-not-qa"),
    ("issue_number", 1111, "session-closure.qa-issue-mismatch"),
    ("issue_body_digest", "0" * 64, "session-closure.qa-body-stale"),
])
def test_registered_record_binding_failures_refuse(field, value, reason):
    setup = Setup(**{field: value})
    fake = FakeTransport()
    outcome = setup.run_entry(fake)
    assert outcome["status"] == "refused"
    assert reason in outcome["reason_codes"]
    assert fake.mutation_tool_calls() == []


def test_wrong_head_binding_refuses():
    setup = Setup()
    setup.snapshot = snapshot(source_head=HEAD)
    fake = FakeTransport()
    outcome = setup.run_entry(fake)
    assert outcome["status"] == "refused"
    assert "session-closure.qa-head-mismatch" in outcome["reason_codes"]
    assert fake.mutation_tool_calls() == []


def test_head_bound_record_succeeds():
    reg = HostRegistry()
    grant = reg.grant_owner_closure(repository=REPO, issue_number=9876, authorizer_id=OWNER)
    token = reg.register_qa_delivery(qa_record(validated_head_sha=HEAD))
    fake = FakeTransport(source_head=HEAD)
    outcome = execute_session_closure(
        registry=reg, owner_grant_token=grant.token, qa_delivery_token=token,
        snapshot=snapshot(source_head=HEAD), body_digest=DIGEST,
        trigger_id="trigger-9876", trigger_body=TRIGGER, transport=fake,
    )
    assert outcome["status"] == "closed-verified", outcome


def test_conflicting_qa_records_refuse():
    setup = Setup()
    other = setup.registry.register_qa_delivery(qa_record(verdict="fail"))
    fake = FakeTransport()
    outcome = setup.run_entry(fake, other_qa_delivery_tokens=(other,))
    assert outcome["status"] == "refused"
    assert "session-closure.qa-conflict" in outcome["reason_codes"]
    assert fake.mutation_tool_calls() == []


def test_unknown_other_qa_token_refuses():
    setup = Setup()
    fake = FakeTransport()
    outcome = setup.run_entry(fake, other_qa_delivery_tokens=("d" * 32,))
    assert outcome["status"] == "refused"
    assert "session-closure.qa-delivery-unknown" in outcome["reason_codes"]
    assert fake.mutation_tool_calls() == []


def test_protected_target_fixture_refused():
    reg = HostRegistry()
    grant = reg.grant_owner_closure(repository=REPO, issue_number=3292, authorizer_id=OWNER)
    token = reg.register_qa_delivery(qa_record(issue=3292))
    fake = FakeTransport(issue=3292)
    outcome = execute_session_closure(
        registry=reg, owner_grant_token=grant.token, qa_delivery_token=token,
        snapshot=snapshot(issue=3292), body_digest=DIGEST,
        trigger_id="trigger-3292", trigger_body=TRIGGER, transport=fake,
    )
    assert outcome["status"] == "refused"
    assert "closure.protected-target" in outcome["reason_codes"]
    assert fake.mutation_tool_calls() == []


def test_repository_not_pinned_refused():
    reg = HostRegistry()
    grant = reg.grant_owner_closure(repository="Other/repo", issue_number=9876, authorizer_id=OWNER)
    token = reg.register_qa_delivery(qa_record())
    fake = FakeTransport()
    outcome = execute_session_closure(
        registry=reg, owner_grant_token=grant.token, qa_delivery_token=token,
        snapshot=snapshot(repository="Other/repo"), body_digest=DIGEST,
        trigger_id="trigger-9876", trigger_body=TRIGGER, transport=fake,
    )
    assert outcome["status"] == "refused"
    assert "session-closure.repository-not-pinned" in outcome["reason_codes"]
    assert fake.mutation_tool_calls() == []


def test_grant_for_other_issue_refused():
    setup = Setup()
    grant = setup.registry.grant_owner_closure(repository=REPO, issue_number=1111, authorizer_id=OWNER)
    fake = FakeTransport()
    outcome = setup.run_entry(fake, owner_grant_token=grant.token)
    assert outcome["status"] == "refused"
    assert "session-closure.decision-identity-mismatch" in outcome["reason_codes"]
    assert fake.mutation_tool_calls() == []


# ---------------------------------------------------------------- F2

def test_production_entry_point_full_sequence_and_tool_trace():
    setup = Setup()
    fake = FakeTransport()
    outcome = setup.run_entry(fake)
    assert outcome["status"] == "closed-verified", outcome
    assert fake.state == "closed" and fake.state_reason == "completed"
    assert fake.labels == []
    assert len(fake.comments) == 1
    assert [op[0] for op in fake.write_ops()] == ["close", "remove_issue_label", "post_comment"]
    mutations = fake.mutation_tool_calls()
    assert mutations[0] == (
        "issue_write", "update",
        {"owner": "Blummer92", "repo": "agent-os", "issue_number": 9876, "state": "closed", "state_reason": "completed"},
    )
    assert mutations[1] == (
        "remove_issue_label", "remove",
        {"owner": "Blummer92", "repo": "agent-os", "issue_number": 9876, "name": "status:ready"},
    )
    assert mutations[2][0] == "add_issue_comment" and mutations[2][1] == "add"
    assert mutations[2][2]["body"] == setup.make_plan().comment_body


def test_manifest_matches_executor_tool_trace():
    setup = Setup()
    plan = setup.make_plan()
    manifest = mcp_manifest(plan)
    # No prose checkpoints, no replacement step, surgical label step only.
    assert all("checkpoint" not in step for step in manifest)
    assert all(step["tool"] != "issue_write" or step["params"].get("labels") is None for step in manifest)
    assert [s for s in manifest if s["action"] == "label-removal-surgical"][0]["tool"] == "remove_issue_label"
    assert all("assertions" in step and "on_failure" in step for step in manifest)
    fake = FakeTransport()
    outcome = setup.run_entry(fake)
    assert outcome["status"] == "closed-verified"
    mutations = fake.mutation_tool_calls()
    manifest_mutations = [s for s in manifest if s["tool"] in ("issue_write", "remove_issue_label", "add_issue_comment")]
    assert len(mutations) == len(manifest_mutations)
    for tool_call, step in zip(mutations, manifest_mutations):
        assert tool_call[0] == step["tool"]
        assert tool_call[2] == step["params"]


def test_manifest_derives_owner_repo_from_plan():
    from dataclasses import replace

    setup = Setup()
    plan = setup.make_plan()
    foreign = replace(plan, repository="Other/repo")
    manifest = mcp_manifest(foreign)
    assert all(step["params"]["owner"] == "Other" and step["params"]["repo"] == "repo" for step in manifest)


def test_mutation_without_valid_admission_refused():
    # AC8: no admission receipt, no mutation phase. Every refusal path
    # below must leave the mutation tool log empty.
    setup = Setup()
    for kwargs in (
        {"owner_grant_token": None},
        {"qa_delivery_token": None},
        {"body_digest": "0" * 64},
        {"trigger_body": "forged trigger"},
    ):
        fake = FakeTransport()
        outcome = setup.run_entry(fake, **kwargs)
        assert outcome["status"] == "refused", kwargs
        assert fake.mutation_tool_calls() == []


def test_prewrite_drift_refuses_with_zero_mutations():
    setup = Setup()
    plan = setup.make_plan()
    fake = FakeTransport(read_overrides={1: {"digest": "0" * 64}})
    outcome = execute_plan(plan, fake)
    assert outcome["status"] == "refused"
    assert "session-closure.body-digest-drift" in outcome["reason_codes"]
    assert fake.mutation_tool_calls() == []


def test_entry_point_uses_canonical_admission():
    # The plan's receipt is byte-equal to a direct canonical evaluation
    # over the same inputs: the adapter adds no evaluation of its own.
    setup = Setup()
    plan = setup.make_plan()
    from scripts.agent_os_issue_acceptance.session_closure_adapter import decision_from_grant

    decision = decision_from_grant(setup.grant, pull_request_number=None)
    acceptance = ClosureAcceptanceEvidence(
        verdict="pass", evidence_id="qa-evidence-9876", evaluator_id="qa-test-agent",
        issue_number=9876, validated_head_sha=None,
    )
    direct = evaluate_issue_closure(
        IssueClosureRequest(decision=decision, acceptance=acceptance, satisfaction=None),
        setup.snapshot, current_issue_body_digest=DIGEST,
    )
    assert plan.receipt == direct


def test_comment_byte_identical_to_dispatcher_oracle():
    setup = Setup()
    plan = setup.make_plan()
    oracle = _completion_comment(
        repository=REPO, issue_number=9876,
        evidence_id="qa-evidence-9876", evaluator_id="qa-test-agent",
        receipt_id=plan.receipt_id,
    )
    assert plan.comment_body == oracle


def test_no_new_infrastructure_in_adapter():
    source = Path(adapter.__file__).read_text()
    for forbidden in ("codespace", "GITHUB_TOKEN", "os.environ", "subprocess", "socket", "urllib", "requests"):
        assert forbidden not in source
    imports = [line for line in source.splitlines() if line.startswith("from .") or line.startswith("import ")]
    assert all("scripts" not in line for line in imports)


# ---------------------------------------------------------------- F3

def test_already_closed_default_zero_mutations():
    setup = Setup()
    fake = FakeTransport()
    fake.state, fake.state_reason = "closed", "completed"
    outcome = setup.run_entry(fake)
    assert outcome["status"] == "already-closed-no-action"
    assert outcome["label_present"] is True
    assert fake.write_ops() == []
    assert fake.mutation_tool_calls() == []


def test_already_closed_default_no_action_even_with_comment_present():
    setup = Setup()
    plan = setup.make_plan()
    fake = FakeTransport()
    fake.state, fake.state_reason = "closed", "completed"
    fake.labels = []
    fake.comments = [plan.comment_body]
    outcome = setup.run_entry(fake)
    assert outcome["status"] == "already-closed-no-action"
    assert outcome["label_present"] is False
    assert fake.write_ops() == []


def test_already_closed_recovery_surgical():
    setup = Setup()
    plan = setup.make_plan()
    recovery = setup.registry.grant_recovery(issue_number=9876, receipt_id=plan.receipt_id)
    fake = FakeTransport()
    fake.state, fake.state_reason = "closed", "completed"
    outcome = setup.run_entry(fake, recovery_grant_token=recovery.token)
    assert outcome["status"] == "already-closed-recovered", outcome
    assert [op[0] for op in fake.write_ops()] == ["remove_issue_label", "post_comment"]
    assert fake.labels == []
    assert len(fake.comments) == 1


def test_already_closed_recovery_preserves_unrelated_labels():
    setup = Setup()
    plan = setup.make_plan()
    recovery = setup.registry.grant_recovery(issue_number=9876, receipt_id=plan.receipt_id)
    fake = FakeTransport()
    fake.state, fake.state_reason = "closed", "completed"
    fake.labels = ["status:ready", "type:bug", "area:docs"]
    outcome = setup.run_entry(fake, recovery_grant_token=recovery.token)
    assert outcome["status"] == "already-closed-recovered"
    assert fake.labels == ["type:bug", "area:docs"]
    label_call = [t for t in fake.mutation_tool_calls() if t[0] == "remove_issue_label"]
    assert label_call == [("remove_issue_label", "remove", {
        "owner": "Blummer92", "repo": "agent-os", "issue_number": 9876, "name": "status:ready"})]


def test_already_closed_recovery_stops_without_surgical():
    # Muse host: no surgical tool -> label step stops, no substitution,
    # comment still posted once, outcome flagged.
    setup = Setup()
    plan = setup.make_plan()
    recovery = setup.registry.grant_recovery(issue_number=9876, receipt_id=plan.receipt_id)
    fake = FakeTransport(surgical=False)
    fake.state, fake.state_reason = "closed", "completed"
    outcome = setup.run_entry(fake, recovery_grant_token=recovery.token)
    assert outcome["status"] == "already-closed-recovered-label-reconciliation-required"
    assert [op[0] for op in fake.write_ops()] == ["post_comment"]
    assert "status:ready" in fake.labels
    assert not any(t[0] == "issue_write" and "labels" in t[2] for t in fake.tool_calls)


def test_fresh_close_stops_label_without_surgical_and_stays_verified():
    setup = Setup()
    fake = FakeTransport(surgical=False)
    outcome = setup.run_entry(fake)
    assert outcome["status"] == "closed-verified-label-reconciliation-required"
    assert fake.state == "closed"
    assert "status:ready" in fake.labels
    assert not any(t[0] == "issue_write" and "labels" in t[2] for t in fake.tool_calls)


def test_invalid_recovery_grant_refuses_with_zero_mutations():
    setup = Setup()
    fake = FakeTransport()
    fake.state, fake.state_reason = "closed", "completed"
    outcome = setup.run_entry(fake, recovery_grant_token="a" * 32)
    assert outcome["status"] == "refused"
    assert "session-closure.recovery-grant-invalid" in outcome["reason_codes"]
    assert fake.mutation_tool_calls() == []


def test_recovery_grant_bound_to_receipt():
    setup = Setup()
    plan = setup.make_plan()
    recovery = setup.registry.grant_recovery(issue_number=9876, receipt_id="other-receipt")
    fake = FakeTransport()
    fake.state, fake.state_reason = "closed", "completed"
    outcome = setup.run_entry(fake, recovery_grant_token=recovery.token)
    assert outcome["status"] == "refused"
    assert fake.mutation_tool_calls() == []


def test_duplicate_delivery_no_duplicate_close_or_comment():
    setup = Setup()
    fake = FakeTransport()
    first = setup.run_entry(fake)
    assert first["status"] == "closed-verified"
    assert len(fake.comments) == 1
    # Second delivery of the same plan: default path, zero writes.
    second = setup.run_entry(fake)
    assert second["status"] == "already-closed-no-action"
    assert len(fake.comments) == 1
    assert [op for op in fake.ops if op[0] == "close"] == [("close",)]
    # Recovery delivery with the comment already present: no second comment.
    plan = setup.make_plan()
    recovery = setup.registry.grant_recovery(issue_number=9876, receipt_id=plan.receipt_id)
    third = setup.run_entry(fake, recovery_grant_token=recovery.token)
    assert third["status"] == "already-closed-recovered"
    assert len(fake.comments) == 1


def test_failed_reconciliation_never_reverses_closure():
    setup = Setup()
    fake = FakeTransport(surgical=False, comment_mode="uncertain-open")
    outcome = setup.run_entry(fake)
    assert outcome["status"] == "unresolved"
    assert fake.state == "closed"
    assert not any(t[0] == "issue_write" and t[2].get("state") == "open" for t in fake.tool_calls)


def test_uncertain_close_not_retried():
    setup = Setup()
    fake = FakeTransport(close_mode="uncertain-landed")
    outcome = setup.run_entry(fake)
    assert outcome["status"] == "closed-verified"
    assert [op for op in fake.ops if op[0] == "close"] == [("close",)]


def test_uncertain_close_not_landed_unresolved():
    setup = Setup()
    fake = FakeTransport(close_mode="uncertain-open")
    outcome = setup.run_entry(fake)
    assert outcome["status"] == "unresolved"
    assert [op for op in fake.ops if op[0] == "close"] == [("close",)]


def test_uncertain_comment_not_retried():
    setup = Setup()
    fake = FakeTransport(comment_mode="uncertain-landed")
    outcome = setup.run_entry(fake)
    assert outcome["status"] == "closed-verified"
    assert [op for op in fake.ops if op[0] == "post_comment"] == [("post_comment",)]


def test_missing_final_readback_not_success():
    setup = Setup()
    plan = setup.make_plan()
    # Fresh-read order on the fresh path: 1 prewrite, 2 post-close,
    # 3 label re-read, 4 final readback. Making #4 unavailable must
    # never yield a verified closure.
    fake = FakeTransport(unavailable_reads={4})
    outcome = execute_plan(plan, fake)
    assert outcome["status"] in ("closed-unverified", "unresolved")
    assert outcome["status"] != "closed-verified"


def test_duplicate_with_wrong_close_reason_unverified_under_recovery():
    setup = Setup()
    plan = setup.make_plan()
    recovery = setup.registry.grant_recovery(issue_number=9876, receipt_id=plan.receipt_id)
    fake = FakeTransport()
    fake.state, fake.state_reason = "closed", "not_planned"
    fake.labels = []
    fake.comments = [plan.comment_body]
    outcome = setup.run_entry(fake, recovery_grant_token=recovery.token)
    assert outcome["status"] == "closed-unverified"


def test_concurrent_label_change_preserved_under_surgical():
    setup = Setup()
    fake = FakeTransport(concurrent_label_at_read=3)
    outcome = setup.run_entry(fake)
    assert outcome["status"] == "closed-verified"
    assert "type:bug" in fake.labels and "status:ready" not in fake.labels


def test_blocked_then_eligible_batch():
    setup = Setup()
    blocked_plan, _ = build_plan(**setup.plan_kwargs(body_digest="0" * 64))
    assert blocked_plan is None
    # Build the batch from one refused plan (None is skipped by the
    # caller) and one valid plan: use execute_batch with the valid plan
    # plus a plan whose prewrite will refuse at execution time.
    valid = setup.make_plan()
    stale = setup.make_plan()
    fake_valid = FakeTransport()
    fake_stale = FakeTransport(read_overrides={1: {"digest": "0" * 64}})
    outcomes = execute_batch([(stale, fake_stale), (valid, fake_valid)])
    assert outcomes[0]["status"] == "refused"
    assert outcomes[1]["status"] == "closed-verified"
    assert fake_stale.mutation_tool_calls() == []
