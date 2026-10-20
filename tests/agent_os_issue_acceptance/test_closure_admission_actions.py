"""Regression matrix for the #3489 governed closure dispatch consumer."""

import pytest

from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    ClosureAcceptanceEvidence,
    ClosureWriteUncertain,
    IssueClosureRequest,
    evaluate_issue_closure,
    run_closure_batch,
    verify_closure_admission_receipt,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
    produce_lifecycle_mutation_authorization,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    LifecycleStateSnapshot,
)

HEAD = "a" * 40
BASE = "b" * 40
REPO = "Blummer92/agent-os"


def snapshot(issue=3432, **changes):
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
        lifecycle_labels=(),
        observed_revision=f"rev-{issue}-1",
    )
    data.update(changes)
    return LifecycleStateSnapshot(**data)


def request(issue=3432, **kw):
    decision = LifecycleOwnerDecision(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        requested_mutations=("close-issue",),
        authorizer_id=kw.get("authorizer_id", "repository-owner"),
        decision_id=kw.get("decision_id", f"owner-decision-{issue}"),
        decision_recorded=kw.get("decision_recorded", True),
    )
    acceptance = ClosureAcceptanceEvidence(
        verdict=kw.get("verdict", "pass"),
        evidence_id=kw.get("evidence_id", f"qa-evidence-{issue}"),
        evaluator_id=kw.get("evaluator_id", "independent-qa"),
    )
    return IssueClosureRequest(decision=decision, acceptance=acceptance)


class FakeReader:
    def __init__(self, snapshots):
        self._snapshots = dict(snapshots)
        self.reads = []

    def read_issue_snapshot(self, repository, issue_number):
        self.reads.append(issue_number)
        return self._snapshots[issue_number]

    def set(self, snap):
        self._snapshots[snap.issue_number] = snap


class FakeWriter:
    """Simulated GitHub Service Agent writer (native issue_write analogue)."""

    def __init__(self, reader, *, fail_for=(), uncertain_for=(), silent_for=()):
        self.reader = reader
        self.calls = []
        self.fail_for = set(fail_for)
        self.uncertain_for = set(uncertain_for)
        self.silent_for = set(silent_for)

    def close_issue(self, repository, issue_number, *, state_reason):
        self.calls.append((issue_number, state_reason))
        if issue_number in self.fail_for:
            raise RuntimeError("github-write-failed")
        if issue_number not in self.silent_for:
            current = self.reader._snapshots[issue_number]
            self.reader.set(
                snapshot(
                    issue_number,
                    issue_state="closed",
                    observed_revision=current.observed_revision + "-closed",
                )
            )
        if issue_number in self.uncertain_for:
            raise ClosureWriteUncertain("response lost")


def admitted_setup(issue=3432):
    req = request(issue)
    snap = snapshot(issue)
    receipt = evaluate_issue_closure(req, snap)
    auth = produce_lifecycle_mutation_authorization(req.decision, snap)
    return req, snap, receipt, auth


def test_owner_authorized_qa_passed_admitted():
    _, _, receipt, _ = admitted_setup()
    assert receipt["admitted"] is True
    assert receipt["reason_codes"] == []
    assert receipt["closure_performed"] is False
    assert receipt["host_dispatch_contract"]["tool"] == "issue_write"
    assert receipt["next_action"] == "host-close-issue-then-canonical-readback"


def test_batch_four_eligible_close_sequentially():
    issues = (3432, 3306, 3307, 3656)
    reader = FakeReader({i: snapshot(i) for i in issues})
    writer = FakeWriter(reader)
    outcomes = run_closure_batch(
        tuple(request(i) for i in issues), reader=reader, writer=writer
    )
    assert [o.status for o in outcomes] == ["closed-verified"] * 4
    assert all(o.readback_verified for o in outcomes)
    assert [c[0] for c in writer.calls] == list(issues)


def test_batch_one_missing_qa_stays_open_others_continue():
    issues = (3432, 3306, 3307)
    reader = FakeReader({i: snapshot(i) for i in issues})
    writer = FakeWriter(reader)
    reqs = (request(3432), request(3306, verdict="missing"), request(3307))
    outcomes = run_closure_batch(reqs, reader=reader, writer=writer)
    assert outcomes[0].status == "closed-verified"
    assert outcomes[1].status == "blocked"
    assert outcomes[1].reason_codes == ("closure.acceptance-not-passed",)
    assert outcomes[2].status == "closed-verified"
    assert [c[0] for c in writer.calls] == [3432, 3307]


def test_merged_pr_but_incomplete_acceptance_refused():
    receipt = evaluate_issue_closure(request(verdict="fail"), snapshot())
    assert receipt["admitted"] is False
    assert receipt["reason_codes"] == ["closure.acceptance-not-passed"]


def test_self_acceptance_refused():
    receipt = evaluate_issue_closure(
        request(evaluator_id="repository-owner"), snapshot()
    )
    assert receipt["admitted"] is False
    assert receipt["reason_codes"] == ["closure.acceptance-not-independent"]


def test_stale_revision_fails_verify_gate():
    _, snap, receipt, auth = admitted_setup()
    fresh = snapshot(observed_revision="rev-3432-2")
    assert verify_closure_admission_receipt(
        receipt,
        authorization=auth,
        fresh_snapshot=fresh,
        acceptance=request().acceptance,
    ) is False


def test_batch_stale_revision_between_reads_blocks_without_write():
    reader = FakeReader({3432: snapshot()})
    writer = FakeWriter(reader)
    original = reader.read_issue_snapshot

    calls = {"n": 0}

    def drifting(repository, issue_number):
        calls["n"] += 1
        if calls["n"] >= 2:
            return snapshot(observed_revision="rev-3432-2")
        return original(repository, issue_number)

    reader.read_issue_snapshot = drifting
    outcomes = run_closure_batch((request(),), reader=reader, writer=writer)
    assert outcomes[0].status == "blocked"
    assert outcomes[0].reason_codes == ("closure.verification-failed-stale-or-drifted",)
    assert writer.calls == []


def test_wrong_issue_identity_refused():
    receipt = evaluate_issue_closure(request(3432), snapshot(9999))
    assert receipt["admitted"] is False
    assert receipt["reason_codes"] == ["closure.issue-identity-mismatch"]


def test_verify_gate_rejects_wrong_issue_receipt():
    _, snap, receipt, _ = admitted_setup(3432)
    other = request(3306)
    other_auth = produce_lifecycle_mutation_authorization(other.decision, snapshot(3306))
    assert verify_closure_admission_receipt(
        receipt,
        authorization=other_auth,
        fresh_snapshot=snapshot(3306),
        acceptance=other.acceptance,
    ) is False


def test_already_closed_no_duplicate_closure():
    reader = FakeReader({3432: snapshot(issue_state="closed")})
    writer = FakeWriter(reader)
    outcomes = run_closure_batch((request(),), reader=reader, writer=writer)
    assert outcomes[0].status == "already-closed"
    assert writer.calls == []


def test_uncertain_write_reconciles_via_readback_no_retry():
    reader = FakeReader({3432: snapshot()})
    writer = FakeWriter(reader, uncertain_for={3432})
    outcomes = run_closure_batch((request(),), reader=reader, writer=writer)
    assert outcomes[0].status == "closed-verified-after-uncertain-write"
    assert outcomes[0].readback_verified is True
    assert len(writer.calls) == 1


def test_uncertain_write_not_applied_reports_uncertain_no_retry():
    reader = FakeReader({3432: snapshot()})
    writer = FakeWriter(reader, uncertain_for={3432}, silent_for={3432})
    outcomes = run_closure_batch((request(),), reader=reader, writer=writer)
    assert outcomes[0].status == "uncertain-write-not-closed"
    assert outcomes[0].readback_verified is False
    assert len(writer.calls) == 1


def test_write_failure_exact_no_false_success_and_batch_continues():
    reader = FakeReader({3432: snapshot(), 3306: snapshot(3306)})
    writer = FakeWriter(reader, fail_for={3432})
    outcomes = run_closure_batch(
        (request(3432), request(3306)), reader=reader, writer=writer
    )
    assert outcomes[0].status == "write-failed"
    assert outcomes[0].reason_codes == ("closure.write-failed:RuntimeError",)
    assert outcomes[0].readback_verified is False
    assert outcomes[1].status == "closed-verified"


def test_missing_authorization_no_closure():
    reader = FakeReader({3432: snapshot()})
    writer = FakeWriter(reader)
    outcomes = run_closure_batch(
        (request(decision_recorded=False),), reader=reader, writer=writer
    )
    assert outcomes[0].status == "blocked"
    assert outcomes[0].reason_codes == ("closure.authorization-not-recorded",)
    assert writer.calls == []


def test_silent_write_success_but_still_open_is_unverified():
    reader = FakeReader({3432: snapshot()})
    writer = FakeWriter(reader, silent_for={3432})
    outcomes = run_closure_batch((request(),), reader=reader, writer=writer)
    assert outcomes[0].status == "write-unverified"
    assert outcomes[0].readback_verified is False


def test_stale_ready_label_closed_verified_reconciliation_required_no_label_edit():
    reader = FakeReader({3432: snapshot(lifecycle_labels=("status:ready",))})
    writer = FakeWriter(reader)
    # FakeWriter rebuilds the closed snapshot without labels; emulate GitHub
    # keeping the stale label by restoring it after close.
    original_close = writer.close_issue

    def close(repository, issue_number, *, state_reason):
        original_close(repository, issue_number, state_reason=state_reason)
        current = reader._snapshots[issue_number]
        reader.set(
            snapshot(
                issue_number,
                issue_state="closed",
                lifecycle_labels=("status:ready",),
                observed_revision=current.observed_revision,
            )
        )

    writer.close_issue = close
    outcomes = run_closure_batch((request(),), reader=reader, writer=writer)
    assert outcomes[0].status == "closed-verified-label-reconciliation-required"
    assert "closure.stale-ready-label-present" in outcomes[0].reason_codes
    assert outcomes[0].readback_verified is True
    assert [c[0] for c in writer.calls] == [3432]  # close only; no label writer exists


def test_protected_target_never_touched():
    receipt = evaluate_issue_closure(request(3292), snapshot(3292))
    assert receipt["admitted"] is False
    assert receipt["reason_codes"] == ["closure.protected-target"]
    reader = FakeReader({3292: snapshot(3292)})
    writer = FakeWriter(reader)
    outcomes = run_closure_batch((request(3292),), reader=reader, writer=writer)
    assert outcomes[0].status == "blocked"
    assert writer.calls == []


def test_authorization_not_broadened_beyond_finite_set():
    reader = FakeReader({3432: snapshot(), 3306: snapshot(3306)})
    writer = FakeWriter(reader)
    outcomes = run_closure_batch((request(3432),), reader=reader, writer=writer)
    assert [o.issue_number for o in outcomes] == [3432]
    assert [c[0] for c in writer.calls] == [3432]


def test_duplicate_issue_in_set_refused():
    reader = FakeReader({3432: snapshot()})
    writer = FakeWriter(reader)
    with pytest.raises(ValueError):
        run_closure_batch((request(), request()), reader=reader, writer=writer)
    assert writer.calls == []


def test_request_cannot_authorize_other_mutations():
    with pytest.raises(ValueError):
        IssueClosureRequest(
            decision=LifecycleOwnerDecision(
                repository=REPO,
                issue_number=3432,
                pull_request_number=None,
                requested_mutations=("close-issue", "merge"),
                authorizer_id="repository-owner",
                decision_id="d1",
                decision_recorded=True,
            ),
            acceptance=ClosureAcceptanceEvidence(
                verdict="pass", evidence_id="e1", evaluator_id="independent-qa"
            ),
        )


def test_forged_receipt_fails_verify_gate():
    req, snap, receipt, auth = admitted_setup()
    acc = req.acceptance
    forged = dict(receipt, admission_result_id="closure-admission-receipt:forged")
    assert verify_closure_admission_receipt(
        forged, authorization=auth, fresh_snapshot=snap, acceptance=acc
    ) is False
    assert verify_closure_admission_receipt(
        receipt, authorization=auth, fresh_snapshot=snap, acceptance=acc
    ) is True


def test_gate_rejects_hand_built_receipt_without_evaluation():
    # QA D1 regression: a receipt assembled by hand from public admission
    # outputs — never passed through evaluate_issue_closure and backed by
    # no acceptance — must not verify.
    from scripts.agent_os_issue_acceptance.closure_admission_actions import (
        HOST_DISPATCH_CONTRACT,
    )
    from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
        evaluate_lifecycle_mutation,
    )

    req, snap, receipt, auth = admitted_setup()
    adm = evaluate_lifecycle_mutation(auth, snap, "close-issue")
    hand = {
        "operation": "close-issue",
        "repository": REPO,
        "issue_number": 3432,
        "authorization_id": auth.authorization_id,
        "host_dispatch_contract": dict(HOST_DISPATCH_CONTRACT),
        "admission_result_id": adm.result_id,
        "snapshot_id": snap.snapshot_id,
        "admitted": True,
        "receipt_id": "totally-made-up",
        "acceptance_evidence_id": "no-qa-ever",
        "schema_version": "bogus",
    }
    assert verify_closure_admission_receipt(
        hand, authorization=auth, fresh_snapshot=snap, acceptance=req.acceptance
    ) is False


def test_gate_rejects_each_tampered_receipt_field():
    req, snap, receipt, auth = admitted_setup()
    acc = req.acceptance
    tampers = [
        {"schema_version": "999"},
        {"receipt_id": "closure-admission-receipt:forged"},
        {"acceptance_evidence_id": "forged-never-existed"},
        {"reason_codes": ["bogus"]},
        {"closure_performed": True},
        {"merge_authorized": True},
        {"side_effects_performed": True},
        {"next_action": "do-anything"},
        {"admitted": False},
    ]
    for tamper in tampers:
        forged = dict(receipt, **tamper)
        assert verify_closure_admission_receipt(
            forged, authorization=auth, fresh_snapshot=snap, acceptance=acc
        ) is False, tamper
    for key in ("receipt_id", "acceptance_evidence_id", "schema_version"):
        forged = {k: v for k, v in receipt.items() if k != key}
        assert verify_closure_admission_receipt(
            forged, authorization=auth, fresh_snapshot=snap, acceptance=acc
        ) is False, key


def test_gate_rejects_overbroad_authorization_and_bad_acceptance():
    req, snap, receipt, auth = admitted_setup()
    broad_decision = LifecycleOwnerDecision(
        repository=REPO,
        issue_number=3432,
        pull_request_number=None,
        requested_mutations=("close-issue", "merge"),
        authorizer_id="repository-owner",
        decision_id="broad-1",
        decision_recorded=True,
    )
    broad_auth = produce_lifecycle_mutation_authorization(broad_decision, snap)
    broad_receipt = dict(receipt, authorization_id=broad_auth.authorization_id)
    assert verify_closure_admission_receipt(
        broad_receipt,
        authorization=broad_auth,
        fresh_snapshot=snap,
        acceptance=req.acceptance,
    ) is False
    wrong_acceptance = ClosureAcceptanceEvidence(
        verdict="pass", evidence_id="other-evidence", evaluator_id="independent-qa"
    )
    assert verify_closure_admission_receipt(
        receipt, authorization=auth, fresh_snapshot=snap, acceptance=wrong_acceptance
    ) is False
    self_acceptance = ClosureAcceptanceEvidence(
        verdict="pass",
        evidence_id=req.acceptance.evidence_id,
        evaluator_id="repository-owner",
    )
    assert verify_closure_admission_receipt(
        receipt, authorization=auth, fresh_snapshot=snap, acceptance=self_acceptance
    ) is False
    failing_acceptance = ClosureAcceptanceEvidence(
        verdict="fail",
        evidence_id=req.acceptance.evidence_id,
        evaluator_id="independent-qa",
    )
    assert verify_closure_admission_receipt(
        receipt, authorization=auth, fresh_snapshot=snap, acceptance=failing_acceptance
    ) is False


def test_gate_rejects_extra_keys_and_nonserializable_core():
    req, snap, receipt, auth = admitted_setup()
    acc = req.acceptance
    extra = dict(receipt, authorized_mutations=["merge"])
    assert verify_closure_admission_receipt(
        extra, authorization=auth, fresh_snapshot=snap, acceptance=acc
    ) is False
    evil = dict(receipt, snapshot_id=object())
    assert verify_closure_admission_receipt(
        evil, authorization=auth, fresh_snapshot=snap, acceptance=acc
    ) is False
