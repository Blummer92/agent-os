from dataclasses import replace
import pytest
from scripts.agent_os_pr_remediation.code_review_benchmark import *
from scripts.agent_os_pr_remediation.models import EvidenceValidationError
from scripts.agent_os_pr_remediation.review_findings import FindingSeverity
SHA="a"*40

def case(outcome=CaseOutcome.DEFECT, detectability=Detectability.STATIC_CODE):
    p=ReviewerPacket("case-001","1",SHA,"crh6-crh7-v1",("src/parser.py","tests/parser.py"),("attack-parser",),("diff:bounded parser change","tests:bounded parser tests"))
    defects=() if outcome is not CaseOutcome.DEFECT else (AnswerDefect("defect-1",("attack-parser",),FindingSeverity.HIGH,("src/parser.py",),("ambiguous-input-regression",)),)
    return p,AnswerKey("case-001","1",outcome,detectability,defects,("canonical-evidence",),("historical-identity",))
def run(p,findings=(),**kw): return BenchmarkRun(BENCHMARK_VERSION,SCORER_VERSION,p.case_id,p.case_version,p.fingerprint,"model-x","high",kw.pop("run_number",1),("packet-only",),findings,**kw)
def finding(**kw): return BenchmarkFinding(kw.pop("finding_id","f1"),("attack-parser",),kw.pop("severity",FindingSeverity.HIGH),kw.pop("blocking",True),kw.pop("evidence_refs",("src/parser.py",)),kw.pop("repair_refs",("src/parser.py",)),kw.pop("test_recommendations",("ambiguous-input-regression",)),**kw)
def test_packet_fingerprint_deterministic_and_versioned():
    p,_=case(); assert p.fingerprint==replace(p).fingerprint; assert p.fingerprint!=replace(p,case_version="2").fingerprint
def test_answer_leakage_rejected():
    p,a=case()
    with pytest.raises(EvidenceValidationError): validate_case(replace(p,visible_context=("root cause: parser",)),a)
def test_later_only_not_false_negative():
    p,a=case(detectability=Detectability.LATER_EVIDENCE_ONLY); s=score_case(p,a,run(p)); assert s.scorable_defects==0
def test_clean_control_false_block_penalized():
    p,a=case(CaseOutcome.CLEAN); s=score_case(p,a,run(p,(finding(supported=False),))); assert (s.false_blocks,s.unsupported_claims)==(1,1)
def test_duplicate_findings_do_not_inflate_defect_identity():
    p,a=case(); s=score_case(p,a,run(p,(finding(finding_id="f1"),finding(finding_id="f2")))); assert s.detected_defects==1
def test_manual_review_calibration():
    p,a=case(CaseOutcome.MANUAL_REVIEW,Detectability.MANUAL_REVIEW); assert score_case(p,a,run(p,manual_review=True)).manual_review_calibration==1
def test_unsupported_test_recommendation_no_credit():
    p,a=case(); assert score_case(p,a,run(p,(finding(test_recommendations=("invented",)),))).test_recommendation_quality==0
def test_overlarge_repair_no_boundary_credit():
    p,a=case(); assert score_case(p,a,run(p,(finding(repair_refs=("src/parser.py","src/unrelated.py")),))).fix_boundary_accuracy==0
def test_contaminated_run_ineligible():
    p,a=case(); s=score_case(p,a,run(p,contaminated=True,contamination_reasons=("repository-wide-search",)))
    assert s.to_dict() == {
        "eligible": False,
        "detected_defects": 0,
        "scorable_defects": 0,
        "substantive_findings": 0,
        "true_positive_findings": 0,
        "blocking_findings": 0,
        "true_positive_blockers": 0,
        "false_blocks": 0,
        "severity_credit": 0,
        "severity_possible": 0,
        "evidence_quality": 0,
        "fix_boundary_accuracy": 0,
        "test_recommendation_quality": 0,
        "manual_review_calibration": 0,
        "unsupported_claims": 0,
        "execution_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "external_write_authorized": False,
        "side_effects_performed": False,
    }
def test_deterministic_scorer():
    p,a=case(); r=run(p,(finding(),)); assert score_case(p,a,r)==score_case(p,a,r)
def test_changed_packet_identity_fails_closed():
    p,a=case()
    with pytest.raises(EvidenceValidationError): score_case(p,a,replace(run(p),packet_fingerprint="bad"))
def test_multiple_runs_expose_unstable_blockers():
    p,a=case(); r1=run(p,(finding(),),run_number=1); r2=run(p,(),run_number=2); assert aggregate_metrics((score_case(p,a,r1),score_case(p,a,r2)),(r1,r2)).cross_run_blocking_stability==0
def test_output_non_authorizing():
    p,a=case(); r=run(p,(finding(),)); s=score_case(p,a,r); m=aggregate_metrics((s,),(r,)); assert not any((s.execution_authorized,s.merge_authorized,s.closure_authorized,s.external_write_authorized,s.side_effects_performed,m.execution_authorized,m.merge_authorized,m.closure_authorized,m.external_write_authorized,m.side_effects_performed))
