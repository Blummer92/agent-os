"""#3690 CR-3 / D5: differential parity between ``run_closure_batch`` and the supported path.

``run_closure_batch`` has no production caller. Before it can be retired, every
protection it enforces must be demonstrably preserved by a supported,
executable path. The supported path is the published MCP closure pair
(``admit_agent_os_issue_closure_tool`` / ``verify_agent_os_issue_closure_admission_tool``,
which delegate to the same ``evaluate_issue_closure`` /
``verify_closure_admission_receipt``), the host dispatch contract they name,
and the shared closure-readback rule (``classify_closure_readback``) that the
Safe Implementation Lane post-PR proof also consumes.

These tests run the SAME inputs through the batch and through that supported
path and require the same refusal / verdict. They add no executor, writer, or
state machine: the only driver code is a recording writer fake. Protections
that exist ONLY inside the batch (post-write identity binding, uncertain-write
reconciliation, reader/writer error propagation, finite-set duplicate refusal)
have no supported-path analogue and are deliberately NOT asserted here; they
remain pinned by the batch's own tests until a supported path can carry them.
"""

from __future__ import annotations

import copy
import itertools

import pytest
from agent_os_execution_service.mcp_server import (
    admit_agent_os_issue_closure_tool,
    verify_agent_os_issue_closure_admission_tool,
)
from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    HOST_DISPATCH_CONTRACT,
    READY_LABEL,
    ClosureAcceptanceEvidence,
    ClosureIssueReadback,
    IssueClosureRequest,
    _receipt,
    classify_closure_readback,
    run_closure_batch,
)
from scripts.agent_os_issue_acceptance.lane_post_pr_issue_reconciliation import (
    LanePostPrIssueEvidence,
    evaluate_lane_post_pr_issue_readback,
    project_lane_post_pr_issue_reconciliation,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
    produce_lifecycle_mutation_authorization,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    LifecycleStateSnapshot,
    evaluate_lifecycle_mutation,
)

REPO = "Blummer92/agent-os"
ISSUE = 3432
PROTECTED = 3292


def snapshot_dict(issue=ISSUE, **changes):
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


def decision_dict(issue=ISSUE, **changes):
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


def acceptance_dict(issue=ISSUE, **changes):
    data = dict(
        verdict="pass",
        evidence_id=f"qa-evidence-{issue}",
        evaluator_id="independent-qa",
    )
    data.update(changes)
    return data


def to_snapshot(data):
    data = dict(data)
    data["lifecycle_labels"] = tuple(data["lifecycle_labels"])
    return LifecycleStateSnapshot(**data)


def to_request(decision, acceptance):
    decision = dict(decision)
    decision["requested_mutations"] = tuple(decision["requested_mutations"])
    return IssueClosureRequest(
        decision=LifecycleOwnerDecision(**decision),
        acceptance=ClosureAcceptanceEvidence(**acceptance),
    )


class ScriptedReader:
    """Canonical reader fake; ``after`` is what the post-write readback shows."""

    def __init__(self, first, *, after=None, drift=None):
        self.first = first
        self.after = after
        self.drift = drift
        self.written = False
        self.snapshot_reads = 0

    def _current(self):
        return self.after if (self.written and self.after is not None) else self.first

    def read_issue_snapshot(self, repository, issue_number):
        self.snapshot_reads += 1
        if self.drift is not None and not self.written:
            return self.drift
        return self._current().snapshot

    def read_issue_readback(self, repository, issue_number):
        return self._current()


class RecordingWriter:
    def __init__(self, reader):
        self.reader = reader
        self.calls = []

    def close_issue(self, repository, issue_number, *, state_reason):
        self.calls.append((repository, issue_number, state_reason))
        self.reader.written = True


def readback(snapshot, state_reason=None):
    return ClosureIssueReadback(
        snapshot=to_snapshot(snapshot), state_reason=state_reason
    )


def initial_readback(snapshot):
    # A closed issue canonically reads back with the ``completed`` reason.
    closed = snapshot["issue_state"] == "closed"
    return readback(snapshot, "completed" if closed else None)


def run_batch(decision, acceptance, snapshot, **reader_kw):
    reader = ScriptedReader(initial_readback(snapshot), **reader_kw)
    writer = RecordingWriter(reader)
    outcomes = run_closure_batch(
        (to_request(decision, acceptance),), reader=reader, writer=writer
    )
    return outcomes[0], writer


def supported_admit(decision, acceptance, snapshot, issue=ISSUE):
    return admit_agent_os_issue_closure_tool(
        REPO, issue, decision, acceptance, snapshot
    )


def supported_verify(receipt, decision, acceptance, fresh, issue=ISSUE):
    auth = produce_lifecycle_mutation_authorization(
        LifecycleOwnerDecision(
            **{
                **decision,
                "requested_mutations": tuple(decision["requested_mutations"]),
            }
        ),
        to_snapshot(snapshot_dict(decision["issue_number"])),
    )
    return verify_agent_os_issue_closure_admission_tool(
        REPO, issue, receipt, auth.to_dict(), fresh, acceptance
    )


# ---------------------------------------------------------------------------
# Positive path: the write the batch performs IS the contract the verify tool names.
# ---------------------------------------------------------------------------


def test_positive_path_batch_write_equals_supported_dispatch_contract():
    decision, acceptance, snap = decision_dict(), acceptance_dict(), snapshot_dict()
    outcome, writer = run_batch(
        decision,
        acceptance,
        snap,
        after=readback(
            snapshot_dict(issue_state="closed", observed_revision="rev-3432-2"),
            "completed",
        ),
    )
    assert outcome.status == "closed-verified" and outcome.readback_verified is True
    assert writer.calls == [(REPO, ISSUE, HOST_DISPATCH_CONTRACT["state_reason"])]

    receipt = supported_admit(decision, acceptance, snap)
    assert receipt["admitted"] is True
    verified = supported_verify(receipt, decision, acceptance, snap)
    assert verified["verified"] is True
    contract = verified["host_dispatch_contract"]
    assert {k: contract[k] for k in HOST_DISPATCH_CONTRACT} == HOST_DISPATCH_CONTRACT
    assert receipt["receipt_id"] == outcome.receipt["receipt_id"]


# ---------------------------------------------------------------------------
# Pre-dispatch protections: same input, same refusal, no write.
# ---------------------------------------------------------------------------

REFUSALS = {
    "qa-missing": dict(acceptance=acceptance_dict(verdict="missing")),
    "qa-failed": dict(acceptance=acceptance_dict(verdict="fail")),
    "self-acceptance": dict(
        acceptance=acceptance_dict(evaluator_id="repository-owner")
    ),
    "decision-unrecorded": dict(decision=decision_dict(decision_recorded=False)),
    "qa-bound-to-other-issue": dict(acceptance=acceptance_dict(issue_number=ISSUE + 1)),
    "snapshot-already-closed-state-drift": dict(
        snapshot=snapshot_dict(issue_state="closed")
    ),
}


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_refusal_is_identical_and_never_writes(name):
    inputs = dict(
        decision=decision_dict(), acceptance=acceptance_dict(), snapshot=snapshot_dict()
    )
    inputs.update(copy.deepcopy(REFUSALS[name]))
    outcome, writer = run_batch(**inputs)
    receipt = supported_admit(**inputs)
    assert receipt["admitted"] is False
    assert writer.calls == []
    if inputs["snapshot"]["issue_state"] == "closed":
        # The batch reports a closed issue as already-closed (never re-closes);
        # the supported path refuses admission outright. Both: no dispatch.
        assert outcome.status == "already-closed"
        return
    assert outcome.status == "blocked"
    assert list(outcome.reason_codes) == receipt["reason_codes"]


def test_protected_target_refused_by_both_paths():
    decision = decision_dict(PROTECTED)
    acceptance = acceptance_dict(PROTECTED)
    snap = snapshot_dict(PROTECTED)
    outcome, writer = run_batch(decision, acceptance, snap)
    receipt = supported_admit(decision, acceptance, snap, issue=PROTECTED)
    assert outcome.status == "blocked" and writer.calls == []
    assert receipt["admitted"] is False
    assert "closure.protected-target" in outcome.reason_codes
    assert "closure.protected-target" in receipt["reason_codes"]


def forged_admitted_receipt(issue):
    """Hash-valid admitted receipt built from the lower layers only (M24 witness).

    ``produce_lifecycle_mutation_authorization`` and ``evaluate_lifecycle_mutation``
    know nothing about protected issues, so the only guard on a caller-supplied
    receipt is the one inside ``verify_closure_admission_receipt``.
    """
    snap = to_snapshot(snapshot_dict(issue))
    auth = produce_lifecycle_mutation_authorization(
        LifecycleOwnerDecision(
            **{**decision_dict(issue), "requested_mutations": ("close-issue",)}
        ),
        snap,
    )
    admission = evaluate_lifecycle_mutation(auth, snap, "close-issue")
    assert admission.admitted
    receipt = _receipt(
        repository=REPO,
        issue_number=issue,
        admitted=True,
        reason_codes=(),
        authorization_id=auth.authorization_id,
        admission_result_id=admission.result_id,
        snapshot_id=snap.snapshot_id,
        acceptance_evidence_id=acceptance_dict(issue)["evidence_id"],
        next_action="host-close-issue-then-canonical-readback",
    )
    return receipt, auth


@pytest.mark.parametrize(
    ("issue", "expect_verified"),
    [(ISSUE, True), (PROTECTED, False)],
    ids=["control", "protected"],
)
def test_forged_admitted_receipt_is_refused_only_for_the_protected_target(
    issue, expect_verified
):
    receipt, auth = forged_admitted_receipt(issue)
    result = verify_agent_os_issue_closure_admission_tool(
        REPO,
        issue,
        receipt,
        auth.to_dict(),
        snapshot_dict(issue),
        acceptance_dict(issue),
    )
    # The control proves the forgery is hash-valid and would verify; the
    # protected case is therefore refused by the protected-target guard alone.
    assert result["verified"] is expect_verified
    assert (result["host_dispatch_contract"] is not None) is expect_verified


# ---------------------------------------------------------------------------
# Currentness, tampering and replay.
# ---------------------------------------------------------------------------


def test_revision_drift_before_dispatch_blocks_both_paths():
    decision, acceptance, snap = decision_dict(), acceptance_dict(), snapshot_dict()
    drifted = snapshot_dict(observed_revision="rev-3432-2")
    outcome, writer = run_batch(
        decision, acceptance, snap, drift=readback(drifted).snapshot
    )
    assert outcome.status == "blocked" and writer.calls == []
    assert outcome.reason_codes == ("closure.verification-failed-stale-or-drifted",)

    receipt = supported_admit(decision, acceptance, snap)
    result = supported_verify(receipt, decision, acceptance, drifted)
    assert result["verified"] is False and result["host_dispatch_contract"] is None


@pytest.mark.parametrize(
    "drift",
    [
        dict(lifecycle_labels=["status:needs-decision"]),
        dict(unresolved_threads=1),
        dict(review_state="blocked"),
    ],
    ids=["label-change", "unresolved-thread", "review-state"],
)
def test_any_state_change_after_admission_fails_both_paths(drift):
    decision, acceptance, snap = decision_dict(), acceptance_dict(), snapshot_dict()
    moved = snapshot_dict(**drift)
    outcome, writer = run_batch(decision, acceptance, snap, drift=to_snapshot(moved))
    assert outcome.status == "blocked" and writer.calls == []
    receipt = supported_admit(decision, acceptance, snap)
    assert supported_verify(receipt, decision, acceptance, moved)["verified"] is False


def test_replayed_receipt_after_closure_is_not_verified_and_batch_does_not_reclose():
    decision, acceptance, snap = decision_dict(), acceptance_dict(), snapshot_dict()
    receipt = supported_admit(decision, acceptance, snap)
    closed = snapshot_dict(issue_state="closed", observed_revision="rev-3432-2")
    # Supported path: the previously admitted receipt cannot authorize a second close.
    replay = supported_verify(receipt, decision, acceptance, closed)
    assert replay["verified"] is False and replay["host_dispatch_contract"] is None
    # Batch: an already-closed issue is reported, never written again.
    outcome, writer = run_batch(decision, acceptance, closed)
    assert outcome.status == "already-closed" and writer.calls == []


def test_receipt_issued_for_another_issue_is_not_replayable():
    other = supported_admit(
        decision_dict(ISSUE + 1),
        acceptance_dict(ISSUE + 1),
        snapshot_dict(ISSUE + 1),
        issue=ISSUE + 1,
    )
    result = supported_verify(
        other, decision_dict(), acceptance_dict(), snapshot_dict()
    )
    assert result["verified"] is False


def test_tampered_receipt_is_rejected():
    decision, acceptance, snap = decision_dict(), acceptance_dict(), snapshot_dict()
    receipt = supported_admit(decision, acceptance, snap)
    tampered = copy.deepcopy(receipt)
    tampered["host_dispatch_contract"]["state_reason"] = "not_planned"
    assert supported_verify(tampered, decision, acceptance, snap)["verified"] is False
    forged = copy.deepcopy(receipt)
    forged["issue_number"] = ISSUE + 1
    assert supported_verify(forged, decision, acceptance, snap)["verified"] is False


# ---------------------------------------------------------------------------
# Closure state / reason / label reconciliation: one rule, three consumers.
# ---------------------------------------------------------------------------


def expected_status(closed, reason, ready):
    """Independent oracle for the post-write readback status (not the code under test)."""
    if closed:
        if reason == "completed":
            return (
                "closed-verified-label-reconciliation-required"
                if ready
                else "closed-verified"
            )
        if reason in ("not_planned", "duplicate"):
            return "closed-reason-mismatch"
        return "closed-reason-unverified"
    return "readback-inconsistent" if reason is not None else "write-unverified"


READBACK_CASES = list(
    itertools.product(
        (True, False),  # issue closed after the write
        (None, "completed", "not_planned", "duplicate"),  # canonical state_reason
        (False, True),  # stale Ready label survives
    )
)


@pytest.mark.parametrize(("closed", "reason", "ready"), READBACK_CASES)
def test_post_write_readback_matches_shared_rule_and_lane_proof(closed, reason, ready):
    labels = [READY_LABEL] if ready else []
    decision, acceptance, snap = decision_dict(), acceptance_dict(), snapshot_dict()
    after = readback(
        snapshot_dict(
            issue_state="closed" if closed else "open",
            lifecycle_labels=labels,
            observed_revision="rev-3432-2",
        ),
        reason,
    )
    outcome, writer = run_batch(decision, acceptance, snap, after=after)
    assert len(writer.calls) == 1

    assert outcome.status == expected_status(closed, reason, ready)
    status, reasons, verified = classify_closure_readback(
        issue_closed=closed,
        state_reason=reason,
        lifecycle_labels=tuple(labels),
        wrote=True,
    )
    assert (outcome.status, outcome.reason_codes, outcome.readback_verified) == (
        status,
        reasons,
        verified,
    )

    plan = project_lane_post_pr_issue_reconciliation(
        LanePostPrIssueEvidence(
            issue_number=ISSUE,
            issue_open=True,
            lifecycle_labels=(READY_LABEL,),
            linked_pull_request_number=1,
            pr_state="draft",
            pr_head_sha="a" * 40,
            pr_readback_current=True,
            closure_authorized=True,
            evidence_current=True,
            repository=REPO,
        )
    )
    proof = evaluate_lane_post_pr_issue_readback(
        plan,
        issue_number=ISSUE,
        issue_open=not closed,
        lifecycle_labels=tuple(labels),
        evidence_current=True,
        state_reason=reason,
        repository=REPO,
    )
    # A closure is fully reconciled by the lane proof exactly when the batch
    # reports a clean ``closed-verified`` (no stale Ready label, completed).
    assert proof.fully_reconciled is (outcome.status == "closed-verified")
    # And a verified-but-label-dirty closure is flagged, never silently clean.
    if verified and ready:
        assert outcome.status == "closed-verified-label-reconciliation-required"
        assert not proof.fully_reconciled
