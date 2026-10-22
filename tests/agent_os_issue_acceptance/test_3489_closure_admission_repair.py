"""Lane B (#3489) red/green tests for QA E5 closure escapes C1-C7."""
import copy
from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    ClosureAcceptanceEvidence, evaluate_issue_closure, verify_closure_admission_receipt,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision, produce_lifecycle_mutation_authorization,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import LifecycleStateSnapshot

REPO="Blummer92/agent-os"
def snap(issue=3432, head="a"*40, rev="rev-1"):
    return LifecycleStateSnapshot(repository=REPO, issue_number=issue, pull_request_number=None,
        source_head=head, base_head=None, pr_state="none", merged=False, issue_state="open",
        review_state="clear", unresolved_threads=0, lifecycle_labels=(), observed_revision=rev)
def complete(issue=3432, digest="c"*64):
    return {"repository":REPO,"issue_number":issue,"issue_body_digest":digest,"status":"complete",
        "criteria":[{"index":1,"identity":"c1","disposition":"satisfied","reason_code":"ok","evidence":["e1"]}]}
def incomplete(issue=3432):
    d=complete(issue); d["status"]="incomplete"
    d["criteria"]=[{"index":1,"identity":"c1","disposition":"unsatisfied","reason_code":"no","evidence":["e1"]}]
    return d
def req(satisfaction=None, acceptance=None, issue=3432):
    from scripts.agent_os_issue_acceptance.closure_admission_actions import IssueClosureRequest
    decision=LifecycleOwnerDecision(repository=REPO, issue_number=issue, requested_mutations=("close-issue",),
        authorizer_id="owner", decision_id="d1", decision_recorded=True)
    acc=acceptance or ClosureAcceptanceEvidence(verdict="pass", evidence_id="ev1", evaluator_id="qa")
    return IssueClosureRequest(decision=decision, acceptance=acc, satisfaction=satisfaction)

def test_c1_incomplete_satisfaction_blocks():
    r=evaluate_issue_closure(req(satisfaction=incomplete()), snap())
    assert r["admitted"] is False and r["reason_codes"]==["closure.satisfaction-incomplete"]
def test_missing_satisfaction_is_not_treated_as_complete_but_unchanged():
    # Absent record: no satisfaction block is fabricated in the receipt.
    r=evaluate_issue_closure(req(), snap())
    assert "satisfaction" not in r
def test_c2_stale_digest_blocks_when_current_digest_supplied():
    r=evaluate_issue_closure(req(satisfaction=complete()), snap(), current_issue_body_digest="d"*64)
    assert r["admitted"] is False and r["reason_codes"]==["closure.satisfaction-stale"]
    r2=evaluate_issue_closure(req(satisfaction=complete()), snap(), current_issue_body_digest="c"*64)
    assert r2["admitted"] is True
def test_c3_qa_evidence_for_wrong_issue_blocks():
    acc=ClosureAcceptanceEvidence(verdict="pass", evidence_id="ev1", evaluator_id="qa", issue_number=9999)
    r=evaluate_issue_closure(req(acceptance=acc), snap())
    assert r["admitted"] is False and r["reason_codes"]==["closure.acceptance-issue-mismatch"]
def test_c7_qa_evidence_for_wrong_head_blocks():
    acc=ClosureAcceptanceEvidence(verdict="pass", evidence_id="ev1", evaluator_id="qa", validated_head_sha="f"*40)
    r=evaluate_issue_closure(req(acceptance=acc), snap())
    assert r["admitted"] is False and r["reason_codes"]==["closure.acceptance-head-mismatch"]
def test_complete_bound_evidence_admits_and_verifies():
    acc=ClosureAcceptanceEvidence(verdict="pass", evidence_id="ev1", evaluator_id="qa", issue_number=3432, validated_head_sha="a"*40)
    rq=req(satisfaction=complete(), acceptance=acc); s=snap()
    r=evaluate_issue_closure(rq, s)
    assert r["admitted"] is True
    PRODUCED=produce_lifecycle_mutation_authorization(rq.decision, s)
    assert verify_closure_admission_receipt(r, authorization=PRODUCED, fresh_snapshot=s, acceptance=acc) is True
def test_c5_receipt_cannot_verify_against_drifted_snapshot():
    rq=req(satisfaction=complete()); s=snap(); r=evaluate_issue_closure(rq, s)
    PRODUCED=produce_lifecycle_mutation_authorization(rq.decision, s)
    drifted=snap(rev="rev-2")
    assert verify_closure_admission_receipt(r, authorization=PRODUCED, fresh_snapshot=drifted, acceptance=rq.acceptance) is False
def test_verify_rejects_receipt_with_incomplete_satisfaction_block():
    rq=req(satisfaction=complete()); s=snap(); r=evaluate_issue_closure(rq, s)
    PRODUCED=produce_lifecycle_mutation_authorization(rq.decision, s)
    forged=copy.deepcopy(r); forged["satisfaction"]=incomplete()
    # Recompute id over forged core would be needed for a hash-valid forgery;
    # the gate must reject on the incomplete block regardless.
    from scripts.agent_os_issue_acceptance.closure_admission_actions import _receipt_id, _RECEIPT_CORE_KEYS
    core={k:forged.get(k) for k in _RECEIPT_CORE_KEYS}; core["satisfaction"]=forged["satisfaction"]
    forged["receipt_id"]=_receipt_id(core); forged["reason_codes"]=[]; forged["admitted"]=True
    assert verify_closure_admission_receipt(forged, authorization=PRODUCED, fresh_snapshot=s, acceptance=rq.acceptance) is False
