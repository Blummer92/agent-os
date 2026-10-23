"""#3690 closure trust-boundary repairs (ADV-1, ADV-2, ADV-5, ADV-6, ADV-7).

Each section reproduces the unsafe behavior an independent Wire-or-Retire
review demonstrated on main a3a396b0 (the exploit assertion is the one that
fails against the pre-repair tree), proves the exploit is now rejected, and
keeps the legitimate positive path working. Shared regressions cover the
protected target, stale authorization / replay, and the absence of any new
write authority. No new closure mechanism is introduced: every repair lives
in the existing admission evaluator, verification gate, batch consumer, and
lane post-PR readback.
"""

from __future__ import annotations

import copy
import itertools

import pytest

from agent_os_execution_service import mcp_server
from scripts.agent_os_issue_acceptance import closure_admission_actions as closure_module
from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    CLOSURE_STATE_REASONS,
    HOST_DISPATCH_CONTRACT,
    ClosureAcceptanceEvidence,
    ClosureIssueReadback,
    IssueClosureRequest,
    _receipt,
    _readback_status,
    classify_closure_readback,
    evaluate_issue_closure,
    run_closure_batch,
    verify_closure_admission_receipt,
)
from scripts.agent_os_issue_acceptance.lane_post_pr_issue_reconciliation import (
    LanePostPrIssueDisposition,
    LanePostPrIssueEvidence,
    evaluate_lane_post_pr_issue_readback,
    project_lane_post_pr_issue_reconciliation,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
    produce_lifecycle_mutation_authorization,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    evaluate_lifecycle_mutation,
)
from tests.agent_os_issue_acceptance.test_closure_admission_actions import (
    REPO,
    FakeReader,
    FakeWriter,
    snapshot,
)

CURRENT = "1" * 64
SUPERSEDED = "2" * 64
HEAD = "a" * 40
OTHER_HEAD = "f" * 40


def satisfaction(issue=3432, *, digest=CURRENT, disposition="satisfied"):
    status = "complete" if disposition == "satisfied" else "incomplete"
    return {
        "repository": REPO,
        "issue_number": issue,
        "issue_body_digest": digest,
        "status": status,
        "criteria": [
            {
                "index": 1,
                "identity": "criterion-1-0123456789ab",
                "disposition": disposition,
                "reason_code": f"reason-{disposition}",
                "evidence": [f"pr:{issue}@{'b' * 40}/qa-verdict-1"],
            }
        ],
    }


def acceptance(issue=3432, *, head=None, bound_issue=None):
    return ClosureAcceptanceEvidence(
        verdict="pass",
        evidence_id=f"qa-evidence-{issue}",
        evaluator_id="independent-qa",
        issue_number=bound_issue,
        validated_head_sha=head,
    )


def decision(issue=3432):
    return LifecycleOwnerDecision(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        requested_mutations=("close-issue",),
        authorizer_id="repository-owner",
        decision_id=f"owner-decision-{issue}",
        decision_recorded=True,
    )


def request(issue=3432, *, sat=None, acc=None):
    return IssueClosureRequest(
        decision=decision(issue),
        acceptance=acc if acc is not None else acceptance(issue),
        satisfaction=sat,
    )


def authorization_for(req, snap):
    return produce_lifecycle_mutation_authorization(req.decision, snap)


def recompute_id(receipt):
    core = {key: receipt.get(key) for key in closure_module._RECEIPT_CORE_KEYS}
    if "satisfaction" in receipt:
        core["satisfaction"] = receipt["satisfaction"]
    receipt["receipt_id"] = closure_module._receipt_id(core)
    return receipt


def verify(receipt, req, snap, **kw):
    return verify_closure_admission_receipt(
        receipt,
        authorization=authorization_for(req, snap),
        fresh_snapshot=snap,
        acceptance=req.acceptance,
        **kw,
    )


class DigestReader(FakeReader):
    """Canonical reader that also reports the current issue-body digest."""

    def __init__(self, snapshots, *, digests, **kw):
        super().__init__(snapshots, **kw)
        self._digests = dict(digests)

    def read_issue_readback(self, repository, issue_number):
        base = super().read_issue_readback(repository, issue_number)
        return ClosureIssueReadback(
            snapshot=base.snapshot,
            state_reason=base.state_reason,
            issue_body_digest=self._digests.get(issue_number),
        )


# ---------------------------------------------------------------------------
# ADV-1 — stale issue-body evidence.
# ---------------------------------------------------------------------------


def test_adv1_batch_refuses_satisfaction_for_a_superseded_body():
    # Exploit (pre-repair): the batch never consulted body currentness, so a
    # record bound to the superseded body closed the issue.
    reader = DigestReader({3432: snapshot()}, digests={3432: CURRENT})
    writer = FakeWriter(reader)
    outcomes = run_closure_batch(
        (request(sat=satisfaction(digest=SUPERSEDED)),), reader=reader, writer=writer
    )
    assert outcomes[0].status == "blocked"
    assert outcomes[0].reason_codes == ("closure.satisfaction-stale",)
    assert writer.calls == []


def test_adv1_batch_positive_current_body_still_closes():
    reader = DigestReader({3432: snapshot()}, digests={3432: CURRENT})
    writer = FakeWriter(reader)
    outcomes = run_closure_batch(
        (request(sat=satisfaction(digest=CURRENT)),), reader=reader, writer=writer
    )
    assert outcomes[0].status == "closed-verified"
    assert outcomes[0].readback_verified is True
    assert writer.calls == [(3432, "completed")]


def test_adv1_reader_without_body_evidence_neither_proves_nor_fabricates():
    # Optional satisfaction and optional body evidence keep their existing
    # semantics: no digest from the reader means no currentness claim, and
    # the receipt cites the record exactly as supplied.
    reader = FakeReader({3432: snapshot()})
    writer = FakeWriter(reader)
    outcomes = run_closure_batch(
        (request(sat=satisfaction(digest=SUPERSEDED)),), reader=reader, writer=writer
    )
    assert outcomes[0].status == "closed-verified"
    assert outcomes[0].receipt["satisfaction"]["issue_body_digest"] == SUPERSEDED


def test_adv1_body_edit_between_reads_fails_closed_through_revision_binding():
    reader = DigestReader({3432: snapshot()}, digests={3432: CURRENT})
    writer = FakeWriter(reader)
    original = reader.read_issue_snapshot
    calls = itertools.count()

    def edited_before_dispatch(repository, issue_number):
        snap = original(repository, issue_number)
        if next(calls) == 1:  # the pre-dispatch reacquisition
            return snapshot(observed_revision="rev-3432-body-edited")
        return snap

    reader.read_issue_snapshot = edited_before_dispatch
    outcomes = run_closure_batch(
        (request(sat=satisfaction(digest=CURRENT)),), reader=reader, writer=writer
    )
    assert outcomes[0].reason_codes == ("closure.verification-failed-stale-or-drifted",)
    assert writer.calls == []


def test_adv1_verify_gate_binds_current_digest_to_trusted_record():
    sat = satisfaction(digest=CURRENT)
    req = request(sat=sat)
    snap = snapshot()
    receipt = evaluate_issue_closure(req, snap, current_issue_body_digest=CURRENT)
    assert verify(receipt, req, snap, satisfaction=sat, current_issue_body_digest=CURRENT)
    assert not verify(receipt, req, snap, satisfaction=sat, current_issue_body_digest=SUPERSEDED)
    assert not verify(receipt, req, snap, satisfaction=sat, current_issue_body_digest="A" * 64)
    assert not verify(receipt, req, snap, satisfaction=sat, current_issue_body_digest="1" * 63)


def test_adv1_digest_without_trusted_record_fails_closed():
    req = request()
    snap = snapshot()
    receipt = evaluate_issue_closure(req, snap)
    assert verify(receipt, req, snap)
    assert not verify(receipt, req, snap, current_issue_body_digest=CURRENT)


@pytest.mark.parametrize("bad", ["", "A" * 64, "1" * 63, 7, b"1" * 64])
def test_adv1_readback_rejects_malformed_body_digest(bad):
    with pytest.raises(ValueError):
        ClosureIssueReadback(snapshot=snapshot(), state_reason=None, issue_body_digest=bad)


# ---------------------------------------------------------------------------
# ADV-2 — QA head binding against a head-less snapshot.
# ---------------------------------------------------------------------------


def test_adv2_head_bound_acceptance_against_headless_snapshot_is_refused():
    # Exploit (pre-repair): the head comparison was skipped whenever the
    # snapshot carried no source_head, so the binding was never checked.
    req = request(acc=acceptance(head=OTHER_HEAD))
    receipt = evaluate_issue_closure(req, snapshot(source_head=None))
    assert receipt["admitted"] is False
    assert receipt["reason_codes"] == ["closure.acceptance-head-unverifiable"]
    assert receipt["next_action"] == "reacquire-snapshot-with-validated-head"


def test_adv2_verify_gate_refuses_head_binding_without_comparable_head():
    # A hash-valid admitted receipt built from the lower layers (bypassing
    # the evaluator) must still fail at the gate when the fresh snapshot
    # cannot confirm the acceptance's head binding.
    snap = snapshot(source_head=None)
    acc = acceptance(head=HEAD)
    req = request(acc=acc)
    auth = authorization_for(req, snap)
    admission = evaluate_lifecycle_mutation(auth, snap, "close-issue")
    assert admission.admitted is True
    forged = _receipt(
        repository=REPO,
        issue_number=3432,
        admitted=True,
        reason_codes=(),
        authorization_id=auth.authorization_id,
        admission_result_id=admission.result_id,
        snapshot_id=snap.snapshot_id,
        acceptance_evidence_id=acc.evidence_id,
        next_action="host-close-issue-then-canonical-readback",
    )
    assert verify_closure_admission_receipt(
        forged, authorization=auth, fresh_snapshot=snap, acceptance=acc
    ) is False
    # The same receipt shape verifies for unbound acceptance (control).
    unbound = acceptance(head=None)
    control = dict(forged, acceptance_evidence_id=unbound.evidence_id)
    assert verify_closure_admission_receipt(
        recompute_id(control), authorization=auth, fresh_snapshot=snap, acceptance=unbound
    ) is True


def test_adv2_issue_only_closure_with_unbound_acceptance_is_unchanged():
    req = request()
    snap = snapshot(source_head=None)
    receipt = evaluate_issue_closure(req, snap)
    assert receipt["admitted"] is True
    assert verify(receipt, req, snap)


def test_adv2_head_bound_acceptance_with_matching_head_still_admits():
    req = request(acc=acceptance(head=HEAD, bound_issue=3432))
    snap = snapshot(source_head=HEAD)
    receipt = evaluate_issue_closure(req, snap)
    assert receipt["admitted"] is True
    assert verify(receipt, req, snap)
    assert not verify(receipt, req, snapshot(source_head=OTHER_HEAD))


def test_adv2_batch_never_writes_for_unverifiable_head_binding():
    reader = FakeReader({3432: snapshot(source_head=None)})
    writer = FakeWriter(reader)
    outcomes = run_closure_batch(
        (request(acc=acceptance(head=HEAD)),), reader=reader, writer=writer
    )
    assert outcomes[0].reason_codes == ("closure.acceptance-head-unverifiable",)
    assert writer.calls == []


def test_adv2_mcp_admit_tool_refuses_unverifiable_head_binding():
    result = mcp_server.admit_agent_os_issue_closure_tool(
        REPO,
        3432,
        {
            "repository": REPO,
            "issue_number": 3432,
            "requested_mutations": ["close-issue"],
            "authorizer_id": "repository-owner",
            "decision_id": "owner-decision-3432",
            "decision_recorded": True,
        },
        {
            "verdict": "pass",
            "evidence_id": "qa-evidence-3432",
            "evaluator_id": "independent-qa",
            "validated_head_sha": HEAD,
        },
        snapshot(source_head=None).to_dict(),
    )
    assert result["admitted"] is False
    assert result["reason_codes"] == ["closure.acceptance-head-unverifiable"]


# ---------------------------------------------------------------------------
# ADV-5 — lane post-PR readback projection.
# ---------------------------------------------------------------------------


def lane_evidence(*, open=True, labels=("status:ready",), state_reason=None, repository=REPO):
    return LanePostPrIssueEvidence(
        issue_number=2770,
        issue_open=open,
        lifecycle_labels=labels,
        linked_pull_request_number=2790,
        pr_state="draft",
        pr_head_sha="b" * 40,
        pr_readback_current=True,
        closure_authorized=True,
        evidence_current=True,
        repository=repository,
        state_reason=state_reason,
    )


def lane_readback(plan, *, open=False, labels=(), state_reason="completed", repository=REPO, current=True):
    return evaluate_lane_post_pr_issue_readback(
        plan,
        issue_number=2770,
        issue_open=open,
        lifecycle_labels=labels,
        evidence_current=current,
        state_reason=state_reason,
        repository=repository,
    )


def close_plan(**kw):
    plan = project_lane_post_pr_issue_reconciliation(lane_evidence(**kw))
    assert plan.disposition is LanePostPrIssueDisposition.RECONCILE_READY_AND_CLOSE
    return plan


def test_adv5_closed_with_stale_ready_label_is_not_reconciled():
    # Exploit (pre-repair): a closed readback proved reconciliation even
    # while status:ready survived.
    proof = lane_readback(close_plan(), labels=("status:ready",))
    assert proof.fully_reconciled is False
    assert proof.reason_codes == (
        "closure.readback-closed",
        "closure.stale-ready-label-present",
    )


@pytest.mark.parametrize(
    "state_reason,code",
    [
        (None, "closure.readback-reason-unverified"),
        ("not_planned", "closure.readback-reason-mismatch"),
        ("duplicate", "closure.readback-reason-mismatch"),
    ],
)
def test_adv5_closed_with_missing_or_wrong_reason_is_not_reconciled(state_reason, code):
    proof = lane_readback(close_plan(), state_reason=state_reason)
    assert proof.fully_reconciled is False
    assert proof.reason_codes == (code,)


@pytest.mark.parametrize(
    "readback_repository,plan_repository",
    [("Other/repo", REPO), (None, REPO), (REPO, None)],
)
def test_adv5_repository_identity_must_match(readback_repository, plan_repository):
    plan = close_plan(repository=plan_repository)
    proof = lane_readback(plan, repository=readback_repository)
    assert proof.fully_reconciled is False
    assert proof.reason_codes == ("lane-post-pr.readback-repository-mismatch",)


def test_adv5_issue_identity_mismatch_still_raises():
    with pytest.raises(ValueError, match="does not match the reconciled issue"):
        evaluate_lane_post_pr_issue_readback(
            close_plan(),
            issue_number=2771,
            issue_open=False,
            lifecycle_labels=(),
            evidence_current=True,
            state_reason="completed",
            repository=REPO,
        )


def test_adv5_missing_readback_evidence_never_reconciles():
    assert lane_readback(close_plan(), current=False).fully_reconciled is False
    assert lane_readback(close_plan(), state_reason=None).fully_reconciled is False


def test_adv5_positive_completed_clean_close_reconciles():
    proof = lane_readback(close_plan())
    assert proof.fully_reconciled is True
    assert proof.reason_codes == ("lane-post-pr.issue-closed",)
    legacy = project_lane_post_pr_issue_reconciliation(lane_evidence(repository=None))
    assert lane_readback(legacy, repository=None).fully_reconciled is True


def test_adv5_issue_closed_without_lane_closure_authority_still_needs_proof():
    plan = project_lane_post_pr_issue_reconciliation(
        LanePostPrIssueEvidence(
            issue_number=2770, issue_open=True, lifecycle_labels=("status:ready",),
            linked_pull_request_number=2790, pr_state="draft", pr_head_sha="b" * 40,
            pr_readback_current=True, closure_authorized=False, evidence_current=True,
            repository=REPO,
        )
    )
    assert plan.disposition is (
        LanePostPrIssueDisposition.RECONCILE_READY_AWAITING_CLOSURE_AUTHORITY
    )
    assert lane_readback(plan, state_reason=None).fully_reconciled is False
    assert lane_readback(plan, labels=("status:ready",)).fully_reconciled is False
    assert lane_readback(plan).fully_reconciled is True


@pytest.mark.parametrize(
    "state_reason,labels,expected",
    [
        ("completed", (), LanePostPrIssueDisposition.ALREADY_RECONCILED),
        (None, (), LanePostPrIssueDisposition.NEEDS_DECISION),
        ("not_planned", (), LanePostPrIssueDisposition.NEEDS_DECISION),
        ("completed", ("status:ready",), LanePostPrIssueDisposition.NEEDS_DECISION),
    ],
)
def test_adv5_already_closed_plan_requires_verified_closure(state_reason, labels, expected):
    # Exploit (pre-repair): any closed issue planned as already reconciled
    # (fully_reconciled=True) regardless of its reason or a stale label.
    plan = project_lane_post_pr_issue_reconciliation(
        lane_evidence(open=False, labels=labels, state_reason=state_reason)
    )
    assert plan.disposition is expected
    assert plan.fully_reconciled is (expected is LanePostPrIssueDisposition.ALREADY_RECONCILED)
    assert plan.expected_mutations == ()


def test_adv5_open_issue_with_terminal_reason_is_inconsistent():
    plan = project_lane_post_pr_issue_reconciliation(lane_evidence(state_reason="completed"))
    assert plan.disposition is LanePostPrIssueDisposition.NEEDS_DECISION
    assert plan.reason_codes == ("closure.readback-inconsistent",)
    proof = lane_readback(close_plan(), open=True, labels=())
    assert proof.fully_reconciled is False


@pytest.mark.parametrize("bad", ["closed", "COMPLETED", ""])
def test_adv5_unsupported_state_reason_is_rejected(bad):
    with pytest.raises(ValueError, match="state_reason"):
        lane_readback(close_plan(), state_reason=bad)
    with pytest.raises(ValueError, match="state_reason"):
        lane_evidence(open=False, state_reason=bad)


def test_adv5_mcp_lane_tool_forwards_identity_and_reason():
    plan = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="plan", issue_number=2770, issue_open=True,
        lifecycle_labels=["status:ready"], linked_pull_request_number=2790,
        pr_state="draft", pr_head_sha="b" * 40, pr_readback_current=True,
        closure_authorized=True, evidence_current=True, repository=REPO,
    )
    assert plan["repository"] == REPO

    def proof(**kw):
        args = dict(
            phase="readback-proof", issue_number=2770, issue_open=False,
            lifecycle_labels=[], evidence_current=True, plan=plan,
            repository=REPO, state_reason="completed",
        )
        args.update(kw)
        return mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(**args)

    assert proof()["fully_reconciled"] is True
    assert proof(lifecycle_labels=["status:ready"])["fully_reconciled"] is False
    assert proof(state_reason=None)["fully_reconciled"] is False
    assert proof(repository="Other/repo")["fully_reconciled"] is False


def test_adv5_lane_and_batch_share_one_readback_rule():
    # Wire-or-Retire: the lane readback reuses the batch's canonical rule
    # rather than carrying a second classifier.
    for closed, reason, labels, wrote in itertools.product(
        (True, False),
        (None, *sorted(CLOSURE_STATE_REASONS)),
        ((), ("status:ready",)),
        (True, False),
    ):
        snap = snapshot(
            issue_state="closed" if closed else "open", lifecycle_labels=labels
        )
        readback = ClosureIssueReadback(snapshot=snap, state_reason=reason)
        assert _readback_status(readback, wrote=wrote) == classify_closure_readback(
            issue_closed=closed, state_reason=reason, lifecycle_labels=labels, wrote=wrote
        )


# ---------------------------------------------------------------------------
# ADV-6 / ADV-7 — satisfaction receipt integrity.
# ---------------------------------------------------------------------------


def test_adv6_stripping_satisfaction_from_a_receipt_never_verifies():
    snap = snapshot()
    incomplete = satisfaction(disposition="missing")
    blocked = evaluate_issue_closure(request(sat=incomplete), snap)
    assert blocked["admitted"] is False
    # Exploit (pre-repair): re-evaluating without the record yields a
    # receipt with no block, and the gate verified it.
    stripped = evaluate_issue_closure(request(), snap)
    req = request()
    assert not verify(stripped, req, snap, satisfaction=incomplete)
    assert not verify(stripped, req, snap, satisfaction=satisfaction())
    # Deleting the block from a complete receipt is detected too.
    complete = evaluate_issue_closure(request(sat=satisfaction()), snap)
    deleted = copy.deepcopy(complete)
    del deleted["satisfaction"]
    assert not verify(recompute_id(deleted), req, snap, satisfaction=satisfaction())


def test_adv7_swapping_in_complete_evidence_with_recomputed_id_never_verifies():
    snap = snapshot()
    incomplete = satisfaction(disposition="missing")
    blocked = evaluate_issue_closure(request(sat=incomplete), snap)
    forged = copy.deepcopy(blocked)
    forged["satisfaction"] = satisfaction()
    forged["admitted"] = True
    forged["reason_codes"] = []
    forged["next_action"] = "host-close-issue-then-canonical-readback"
    auth = authorization_for(request(), snap)
    forged["authorization_id"] = auth.authorization_id
    forged["admission_result_id"] = evaluate_lifecycle_mutation(
        auth, snap, "close-issue"
    ).result_id
    recompute_id(forged)
    req = request()
    # Exploit (pre-repair): with no trusted record the gate trusted the block.
    assert not verify(forged, req, snap)
    assert not verify(forged, req, snap, satisfaction=incomplete)
    # Injecting a complete block into an unsatisfied-free receipt is refused
    # unless the verifier itself holds exactly that record.
    plain = evaluate_issue_closure(req, snap)
    injected = recompute_id(dict(plain, satisfaction=satisfaction()))
    assert not verify(injected, req, snap)
    # When the verifier does hold that exact complete record, the receipt is
    # byte-identical to an honest evaluation with it — nothing is gained.
    honest = evaluate_issue_closure(request(sat=satisfaction()), snap)
    assert injected == honest
    assert verify(honest, req, snap, satisfaction=satisfaction())


@pytest.mark.parametrize(
    "trusted",
    [
        satisfaction(issue=3306),
        {**satisfaction(), "status": "incomplete"},
        {"status": "complete"},
        "complete",
    ],
)
def test_adv7_untrusted_or_foreign_trusted_record_fails_closed(trusted):
    snap = snapshot()
    receipt = evaluate_issue_closure(request(sat=satisfaction()), snap)
    assert not verify(receipt, request(), snap, satisfaction=trusted)


def test_adv6_adv7_optional_satisfaction_preserved_and_positive_path_works():
    snap = snapshot()
    req = request()
    plain = evaluate_issue_closure(req, snap)
    assert verify(plain, req, snap)  # neither side carries satisfaction
    sat = satisfaction()
    cited = evaluate_issue_closure(request(sat=sat), snap)
    assert verify(cited, req, snap, satisfaction=sat)
    assert verify(cited, req, snap, satisfaction=closure_module._satisfaction_snapshot(sat))
    assert not verify(cited, req, snap)  # a cited block needs the trusted record


def test_adv6_adv7_mcp_verify_tool_binds_trusted_record():
    snap = snapshot()
    sat = satisfaction()
    req = request(sat=sat)
    receipt = evaluate_issue_closure(req, snap)
    auth = authorization_for(req, snap).to_dict()
    acc = {"verdict": "pass", "evidence_id": "qa-evidence-3432", "evaluator_id": "independent-qa"}

    def tool(rcpt, **kw):
        return mcp_server.verify_agent_os_issue_closure_admission_tool(
            REPO, 3432, rcpt, auth, snap.to_dict(), acc, **kw
        )

    assert tool(receipt, satisfaction=sat)["verified"] is True
    assert tool(receipt)["verified"] is False
    assert tool(receipt, satisfaction=satisfaction(disposition="missing"))["verified"] is False
    stripped = recompute_id({k: v for k, v in receipt.items() if k != "satisfaction"})
    assert tool(stripped, satisfaction=sat)["verified"] is False
    refused = tool(receipt)
    assert refused["host_dispatch_contract"] is None
    assert refused["next_action"] == "do-not-dispatch-closure-reevaluate"


# ---------------------------------------------------------------------------
# Shared security regressions.
# ---------------------------------------------------------------------------


def test_protected_target_is_never_admitted_or_verified():
    snap = snapshot(3292)
    sat = satisfaction(issue=3292)
    receipt = evaluate_issue_closure(request(3292, sat=sat), snap)
    assert receipt["admitted"] is False
    assert receipt["reason_codes"] == ["closure.protected-target"]
    forged = recompute_id(
        dict(receipt, admitted=True, reason_codes=[],
             next_action="host-close-issue-then-canonical-readback")
    )
    assert not verify(forged, request(3292), snap, satisfaction=sat)


def test_stale_authorization_and_replay_are_refused():
    snap = snapshot()
    sat = satisfaction()
    req = request(sat=sat)
    receipt = evaluate_issue_closure(req, snap)
    assert verify(receipt, req, snap, satisfaction=sat)
    # Replay after the closure landed: the fresh closed snapshot never re-verifies.
    closed = snapshot(issue_state="closed", observed_revision="rev-3432-2")
    assert not verify_closure_admission_receipt(
        receipt, authorization=authorization_for(req, snap), fresh_snapshot=closed,
        acceptance=req.acceptance, satisfaction=sat,
    )
    # Stale revision and an authorization bound to another issue.
    drifted = snapshot(observed_revision="rev-3432-9")
    assert not verify_closure_admission_receipt(
        receipt, authorization=authorization_for(req, snap), fresh_snapshot=drifted,
        acceptance=req.acceptance, satisfaction=sat,
    )
    other = request(3306)
    assert not verify_closure_admission_receipt(
        receipt, authorization=authorization_for(other, snapshot(3306)),
        fresh_snapshot=snapshot(3306), acceptance=req.acceptance, satisfaction=sat,
    )


def test_no_new_write_authority_is_introduced():
    snap = snapshot(source_head=None)
    receipt = evaluate_issue_closure(request(sat=satisfaction()), snap)
    assert receipt["closure_performed"] is False
    assert receipt["merge_authorized"] is False
    assert receipt["side_effects_performed"] is False
    assert HOST_DISPATCH_CONTRACT == {
        "writer": "native-github-mcp",
        "tool": "issue_write",
        "method": "update",
        "state": "closed",
        "state_reason": "completed",
        "gate": "verify_closure_admission_receipt",
        "readback": "canonical-issue-read",
    }
    plan = project_lane_post_pr_issue_reconciliation(lane_evidence())
    assert plan.merge_authorized is False
    assert plan.ready_authorized is False
    assert plan.side_effects_performed is False
    assert set(plan.expected_mutations) <= {"remove-lifecycle-label", "close-issue"}
    verified = mcp_server.verify_agent_os_issue_closure_admission_tool(
        REPO, 3432, receipt, authorization_for(request(), snap).to_dict(),
        snap.to_dict(),
        {"verdict": "pass", "evidence_id": "qa-evidence-3432", "evaluator_id": "independent-qa"},
        satisfaction=satisfaction(),
    )
    assert verified["verified"] is True
    for key in ("closure_performed", "github_writes_authorized", "merge_authorized",
                "execution_authorized", "side_effects_performed"):
        assert verified[key] is False
