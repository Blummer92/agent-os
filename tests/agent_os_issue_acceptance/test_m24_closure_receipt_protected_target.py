"""M24: forged admitted receipt for protected issue 3292 via verify gate.

Gap covered: ``test_closure_admission_actions.test_protected_target_never_touched``
exercises the protected refusal only through ``evaluate_issue_closure`` /
``run_closure_batch``. A caller (e.g. the #3675 MCP verify tool) can supply
a receipt directly to ``verify_closure_admission_receipt``, bypassing
``evaluate_issue_closure`` entirely. Neither
``produce_lifecycle_mutation_authorization`` nor
``evaluate_lifecycle_mutation`` has a protected-target check, so a
hash-valid admitted receipt for 3292 can be constructed from the lower
layers alone (see the witness construction below). The only guard on
that path is the protected refusal inside
``verify_closure_admission_receipt`` itself::

    if authorization.issue_number in PROTECTED_ISSUE_NUMBERS:
        return False

Mutation M24 removes exactly that refusal. Under M24 the forged-3292
test in this file fails (verify returns True); on unmodified code every
test here passes. Synthetic fixtures only; no GitHub interaction.
"""

import copy

from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    ClosureAcceptanceEvidence,
    IssueClosureRequest,
    _receipt,
    evaluate_issue_closure,
    verify_closure_admission_receipt,
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
PROTECTED = 3292
CONTROL = 3432
OTHER = 3306
HEAD = "a" * 40
OTHER_HEAD = "f" * 40


def snap(issue=CONTROL, head=HEAD, rev="rev-1"):
    return LifecycleStateSnapshot(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        source_head=head,
        base_head=None,
        pr_state="none",
        merged=False,
        issue_state="open",
        review_state="clear",
        unresolved_threads=0,
        lifecycle_labels=(),
        observed_revision=rev,
    )


def acceptance(issue=CONTROL, head=HEAD):
    return ClosureAcceptanceEvidence(
        verdict="pass",
        evidence_id="ev1",
        evaluator_id="qa",
        issue_number=issue,
        validated_head_sha=head,
    )


def decision(issue):
    return LifecycleOwnerDecision(
        repository=REPO,
        issue_number=issue,
        requested_mutations=("close-issue",),
        authorizer_id="owner",
        decision_id="d1",
        decision_recorded=True,
    )


def forged_admitted_receipt(issue):
    """Hash-valid admitted receipt built WITHOUT evaluate_issue_closure.

    Uses only the lower layers (authorization + lifecycle guard), which
    admit even the protected target, plus the module's own ``_receipt``
    builder. Returns (receipt, authorization, snapshot, acceptance).
    """
    s = snap(issue)
    acc = acceptance(issue)
    auth = produce_lifecycle_mutation_authorization(decision(issue), s)
    adm = evaluate_lifecycle_mutation(auth, s, "close-issue")
    assert adm.admitted, f"lower layers unexpectedly refuse {issue}: {adm}"
    receipt = _receipt(
        repository=REPO,
        issue_number=issue,
        admitted=True,
        reason_codes=(),
        authorization_id=auth.authorization_id,
        admission_result_id=adm.result_id,
        snapshot_id=s.snapshot_id,
        acceptance_evidence_id=acc.evidence_id,
        next_action="host-close-issue-then-canonical-readback",
    )
    return receipt, auth, s, acc


def legitimate_receipt(issue=CONTROL):
    """Receipt through the governed evaluate_issue_closure path."""
    s = snap(issue)
    acc = acceptance(issue)
    req = IssueClosureRequest(decision=decision(issue), acceptance=acc)
    receipt = evaluate_issue_closure(req, s)
    assert receipt["admitted"] is True
    auth = produce_lifecycle_mutation_authorization(req.decision, s)
    return receipt, auth, s, acc


# --- The M24 escape -------------------------------------------------------


def test_forged_admitted_receipt_for_protected_3292_rejected_by_verify():
    receipt, auth, s, acc = forged_admitted_receipt(PROTECTED)
    assert receipt["admitted"] is True
    assert receipt["issue_number"] == PROTECTED
    assert (
        verify_closure_admission_receipt(
            receipt, authorization=auth, fresh_snapshot=s, acceptance=acc
        )
        is False
    )


def test_forged_construction_is_hash_valid_for_nonprotected_control():
    # Positive control for the forgery itself: the identical construction
    # for a non-protected issue verifies True, proving the 3292 rejection
    # above is the protected guard and not a malformed receipt.
    receipt, auth, s, acc = forged_admitted_receipt(CONTROL)
    assert (
        verify_closure_admission_receipt(
            receipt, authorization=auth, fresh_snapshot=s, acceptance=acc
        )
        is True
    )


def test_valid_fixture_receipt_still_verifies():
    receipt, auth, s, acc = legitimate_receipt(CONTROL)
    assert (
        verify_closure_admission_receipt(
            receipt, authorization=auth, fresh_snapshot=s, acceptance=acc
        )
        is True
    )


# --- Receipt / target binding ----------------------------------------------


def test_receipt_for_one_issue_does_not_verify_for_another():
    receipt, _auth, _s, _acc = legitimate_receipt(CONTROL)
    other_receipt, other_auth, other_s, other_acc = legitimate_receipt(OTHER)
    assert other_receipt["admitted"] is True
    assert (
        verify_closure_admission_receipt(
            receipt,
            authorization=other_auth,
            fresh_snapshot=other_s,
            acceptance=other_acc,
        )
        is False
    )


def test_protected_receipt_does_not_verify_against_nonprotected_target():
    forged, _auth, _s, _acc = forged_admitted_receipt(PROTECTED)
    _receipt2, auth, s, acc = legitimate_receipt(CONTROL)
    assert (
        verify_closure_admission_receipt(
            forged, authorization=auth, fresh_snapshot=s, acceptance=acc
        )
        is False
    )


def test_nonprotected_receipt_does_not_verify_against_protected_target():
    receipt, _auth, _s, _acc = legitimate_receipt(CONTROL)
    _forged, p_auth, p_s, p_acc = forged_admitted_receipt(PROTECTED)
    assert (
        verify_closure_admission_receipt(
            receipt, authorization=p_auth, fresh_snapshot=p_s, acceptance=p_acc
        )
        is False
    )


# --- Wrong issue / head combinations ---------------------------------------


def test_wrong_acceptance_issue_rejected():
    receipt, auth, s, _acc = legitimate_receipt(CONTROL)
    wrong_acc = acceptance(issue=OTHER, head=HEAD)
    assert (
        verify_closure_admission_receipt(
            receipt, authorization=auth, fresh_snapshot=s, acceptance=wrong_acc
        )
        is False
    )


def test_wrong_acceptance_head_rejected():
    receipt, auth, s, _acc = legitimate_receipt(CONTROL)
    wrong_acc = acceptance(issue=CONTROL, head=OTHER_HEAD)
    assert (
        verify_closure_admission_receipt(
            receipt, authorization=auth, fresh_snapshot=s, acceptance=wrong_acc
        )
        is False
    )


def test_wrong_snapshot_head_rejected():
    receipt, auth, _s, acc = legitimate_receipt(CONTROL)
    drifted_head = snap(CONTROL, head=OTHER_HEAD)
    assert (
        verify_closure_admission_receipt(
            receipt, authorization=auth, fresh_snapshot=drifted_head, acceptance=acc
        )
        is False
    )


def test_wrong_snapshot_issue_rejected():
    receipt, auth, _s, acc = legitimate_receipt(CONTROL)
    other_s = snap(OTHER)
    assert (
        verify_closure_admission_receipt(
            receipt, authorization=auth, fresh_snapshot=other_s, acceptance=acc
        )
        is False
    )


# --- Stale / tampered receipts ----------------------------------------------


def test_stale_snapshot_rejected():
    receipt, auth, _s, acc = legitimate_receipt(CONTROL)
    stale = snap(CONTROL, rev="rev-2")
    assert (
        verify_closure_admission_receipt(
            receipt, authorization=auth, fresh_snapshot=stale, acceptance=acc
        )
        is False
    )


def test_tampered_receipt_fields_rejected():
    receipt, auth, s, acc = legitimate_receipt(CONTROL)
    tampers = [
        {"receipt_id": "closure-admission-receipt:forged"},
        {"admission_result_id": "closure-admission-receipt:forged"},
        {"snapshot_id": "snapshot:forged"},
        {"acceptance_evidence_id": "forged-never-existed"},
        {"authorization_id": "authorization:forged"},
        {"issue_number": OTHER},
        {"admitted": False},
        {"reason_codes": ["closure.protected-target"]},
        {"next_action": "do-anything"},
        {"closure_performed": True},
    ]
    for tamper in tampers:
        forged = copy.deepcopy(receipt)
        forged.update(tamper)
        assert (
            verify_closure_admission_receipt(
                forged, authorization=auth, fresh_snapshot=s, acceptance=acc
            )
            is False
        ), tamper


def test_forged_protected_receipt_tampered_copy_also_rejected():
    receipt, auth, s, acc = forged_admitted_receipt(PROTECTED)
    tampered = copy.deepcopy(receipt)
    tampered["receipt_id"] = "closure-admission-receipt:forged"
    assert (
        verify_closure_admission_receipt(
            tampered, authorization=auth, fresh_snapshot=s, acceptance=acc
        )
        is False
    )
