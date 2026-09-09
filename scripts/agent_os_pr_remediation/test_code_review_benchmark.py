from dataclasses import replace
import pytest
from .code_review_benchmark import *
from .models import EvidenceValidationError
from .review_findings import FindingSeverity

SHA="a"*40

def case(outcome=CaseOutcome.DEFECT, detectability=Detectability.STATIC_CODE):
    packet=ReviewerPacket("case-001","1",SHA,"crh6-crh7-v1",("src/parser.py","tests/parser.py"),("attack-parser",),("diff:bounded parser change","tests:bounded parser tests"))
    defects=() if outcome is not CaseOutcome.DEFECT else (AnswerDefect("defect-1",("attack-parser",),FindingSeverity.HIGH,("src/parser.py",),("ambiguous-input-regression",)),)
    answer=AnswerKey("case-001","1",outcome,detectability,defects,("canonical-evidence",),("historical-identity",))
    return packet,answer

def run(packet,findings=(),**kw):
    return BenchmarkRun(BENCHMARK_VERSION,SCORER_VERSION,packet.case_id,packet.case_version,packet.fingerprint,"model-x","high",kw.pop("run_number",1),("packet-only",),findings,**kw)

def finding(**kw):
    return BenchmarkFinding(kw.pop("finding_id","f1"),("attack-parser",),kw.pop("severity",FindingSeverity.HIGH),kw.pop("blocking",True),kw.pop("evidence_refs",("src/parser.py",)),kw.pop("repair_refs",("src/parser.py",)),kw.pop("test_recommendations",("ambiguous-input-regression",)),**kw)

def test_packet_fingerprint_is_deterministic_and_version_sensitive():
    p,_=case(); assert p.fingerprint==replace(p).fingerprint; assert p.fingerprint!=replace(p,case_version="2").fingerprint

def test_reviewer_packet_rejects_answer_leakage():
    p,a=case(); p=replace(p,visible_context=("root cause: parser",));
    with pytest.raises(EvidenceValidationError): validate_case(p,a)

def test_later_only_does_not_count_false_negative():
    p,a=case(detectability=Detectability.LATER_EVIDENCE_ONLY); s=score_case(p,a,run(p)); assert s.scorable_defects==0 and s.detected_defects==0

def test_clean_control_false_block_penalized():
    p,a=case(CaseOutcome.CLEAN); s=score_case(p,a,run(p,(finding(supported=False),))); assert s.false_blocks==1 and s.unsupported_claims==1

def test_duplicate_findings_do_not_inflate_defect_recall():
    p,a=case(); s=score_case(p,a,run(p,(finding(finding_id="f1"),finding(finding_id="f2")))); assert s.detected_defects==1 and s.true_positive_findings==2

def test_manual_review_rewards_calibrated_abstention():
    p,a=case(CaseOutcome.MANUAL_REVIEW,Detectability.MANUAL_REVIEW); assert score_case(p,a,run(p,manual_review=True)).manual_review_calibration==1

def test_unsupported_test_recommendation_gets_no_credit():
    p,a=case(); s=score_case(p,a,run(p,(finding(test_recommendations=("invented-test",)),))); assert s.test_recommendation_quality==0

def test_overlarge_repair_gets_no_boundary_credit():
    p,a=case(); s=score_case(p,a,run(p,(finding(repair_refs=("src/parser.py","src/unrelated.py")),))); assert s.fix_boundary_accuracy==0

def test_contaminated_run_is_ineligible():
    p,a=case(); s=score_case(p,a,run(p,contaminated=True,contamination_reasons=("repository-wide-search",))); assert not s.eligible

def test_scorer_is_deterministic():
    p,a=case(); r=run(p,(finding(),)); assert score_case(p,a,r)==score_case(p,a,r)

def test_wrong_packet_fingerprint_fails_closed():
    p,a=case(); r=replace(run(p),packet_fingerprint="bad")
    with pytest.raises(EvidenceValidationError): score_case(p,a,r)

def test_multiple_runs_expose_unstable_blockers():
    p,a=case(); r1=run(p,(finding(),),run_number=1); r2=run(p,(),run_number=2); scores=(score_case(p,a,r1),score_case(p,a,r2)); assert aggregate_metrics(scores,(r1,r2)).cross_run_blocking_stability==0

def test_output_is_non_authorizing():
    p,a=case(); s=score_case(p,a,run(p,(finding(),))); m=aggregate_metrics((s,),(run(p,(finding(),)),)); assert not any((s.execution_authorized,s.merge_authorized,s.closure_authorized,s.external_write_authorized,s.side_effects_performed,m.execution_authorized,m.merge_authorized,m.closure_authorized,m.external_write_authorized,m.side_effects_performed))
