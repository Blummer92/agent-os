"""CRH8A pure-local blinded historical code-review benchmark and scorer."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any
from .models import EvidenceValidationError, deterministic_id
from .review_findings import FindingSeverity

BENCHMARK_VERSION = "1.0.0"
SCORER_VERSION = "1.0.0"
MAX_ITEMS = 64
MAX_TEXT = 10000

class Detectability(str, Enum):
    STATIC_CODE = "static-code-detectable"
    REQUIREMENTS = "requirements-detectable"
    REPOSITORY_CONTEXT = "repository-context-detectable"
    REVIEW_TIME_TEST = "review-time-test-detectable"
    RUNTIME_EVIDENCE_REQUIRED = "runtime-evidence-required"
    LATER_EVIDENCE_ONLY = "later-evidence-only"
    REVIEW_TIME_UNKNOWABLE = "review-time-unknowable"
    MANUAL_REVIEW = "manual-review"

class CaseOutcome(str, Enum):
    DEFECT = "defect"
    CLEAN = "clean"
    MANUAL_REVIEW = "manual-review"
    RED_HERRING = "red-herring"

@dataclass(frozen=True, slots=True)
class ReviewerPacket:
    case_id: str
    case_version: str
    source_head_sha: str
    review_contract_version: str
    evidence_refs: tuple[str, ...]
    required_attack_ids: tuple[str, ...]
    visible_context: tuple[str, ...]
    @property
    def fingerprint(self) -> str:
        return deterministic_id(asdict(self))

@dataclass(frozen=True, slots=True)
class AnswerDefect:
    defect_id: str
    attack_ids: tuple[str, ...]
    severity: FindingSeverity
    minimum_repair_refs: tuple[str, ...]
    regression_recommendations: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class AnswerKey:
    case_id: str
    case_version: str
    outcome: CaseOutcome
    detectability: Detectability
    defects: tuple[AnswerDefect, ...]
    supporting_evidence_refs: tuple[str, ...]
    leakage_risks: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class BenchmarkFinding:
    finding_id: str
    attack_ids: tuple[str, ...]
    severity: FindingSeverity
    blocking: bool
    evidence_refs: tuple[str, ...]
    repair_refs: tuple[str, ...] = ()
    test_recommendations: tuple[str, ...] = ()
    supported: bool = True

@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    benchmark_version: str
    scorer_version: str
    case_id: str
    case_version: str
    packet_fingerprint: str
    model_identity: str
    reasoning_setting: str
    run_number: int
    tool_profile: tuple[str, ...]
    findings: tuple[BenchmarkFinding, ...] = ()
    manual_review: bool = False
    contaminated: bool = False
    contamination_reasons: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class CaseScore:
    eligible: bool
    detected_defects: int
    scorable_defects: int
    substantive_findings: int
    true_positive_findings: int
    blocking_findings: int
    true_positive_blockers: int
    false_blocks: int
    severity_credit: float
    severity_possible: float
    evidence_quality: float
    fix_boundary_accuracy: float
    test_recommendation_quality: float
    manual_review_calibration: float
    unsupported_claims: int
    execution_authorized: bool = False
    merge_authorized: bool = False
    closure_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False

    def to_dict(self) -> dict[str, Any]: return asdict(self)

@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    defect_recall: float | None
    severity_weighted_defect_recall: float | None
    review_precision: float | None
    blocking_finding_precision: float | None
    false_block_rate: float | None
    severity_calibration: float | None
    evidence_quality: float | None
    fix_boundary_accuracy: float | None
    test_recommendation_quality: float | None
    manual_review_calibration: float | None
    unsupported_claim_rate: float | None
    cross_run_blocking_stability: float | None
    eligible_runs: int
    ineligible_runs: int
    execution_authorized: bool = False
    merge_authorized: bool = False
    closure_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > MAX_TEXT: raise EvidenceValidationError(f"{field} must be a bounded non-empty string")
    return value.strip()

def _items(values: tuple[str, ...], field: str, required: bool=False) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) > MAX_ITEMS: raise EvidenceValidationError(f"{field} must be a bounded tuple")
    result=tuple(sorted({_text(v, field) for v in values}))
    if required and not result: raise EvidenceValidationError(f"{field} must not be empty")
    return result

def _sha(value: str) -> str:
    value=_text(value,"source_head_sha").lower()
    if len(value)!=40 or any(c not in "0123456789abcdef" for c in value): raise EvidenceValidationError("source_head_sha must be a 40-character hexadecimal SHA")
    return value

def _mean(values: list[float]) -> float | None: return sum(values)/len(values) if values else None

def validate_case(packet: ReviewerPacket, answer: AnswerKey) -> None:
    if type(packet) is not ReviewerPacket or type(answer) is not AnswerKey: raise EvidenceValidationError("case surfaces must use benchmark models")
    if packet.case_id != answer.case_id or packet.case_version != answer.case_version: raise EvidenceValidationError("reviewer packet and answer key identity mismatch")
    _text(packet.case_id,"case_id"); _text(packet.case_version,"case_version"); _sha(packet.source_head_sha)
    _items(packet.evidence_refs,"evidence_refs",True); _items(packet.required_attack_ids,"required_attack_ids"); _items(packet.visible_context,"visible_context")
    if type(answer.outcome) is not CaseOutcome or type(answer.detectability) is not Detectability: raise EvidenceValidationError("unsupported answer vocabulary")
    if answer.outcome is CaseOutcome.CLEAN and not answer.supporting_evidence_refs: raise EvidenceValidationError("clean controls require positive bounded evidence")
    hidden_tokens=("answer_key","root cause","review finding","issue #","pull/")
    visible="\n".join(packet.evidence_refs+packet.visible_context).lower()
    if any(token in visible for token in hidden_tokens): raise EvidenceValidationError("reviewer packet contains answer-leakage material")
    for defect in answer.defects:
        if type(defect.severity) is not FindingSeverity: raise EvidenceValidationError("defect severity must reuse CRH6 FindingSeverity")
        if not set(defect.attack_ids).issubset(set(packet.required_attack_ids)): raise EvidenceValidationError("answer defect must reuse supplied CRH5/CRH7 attack identities")

def score_case(packet: ReviewerPacket, answer: AnswerKey, run: BenchmarkRun) -> CaseScore:
    validate_case(packet,answer)
    if run.benchmark_version != BENCHMARK_VERSION or run.scorer_version != SCORER_VERSION or run.case_id != packet.case_id or run.case_version != packet.case_version or run.packet_fingerprint != packet.fingerprint: raise EvidenceValidationError("run identity/version does not match frozen benchmark case")
    if run.run_number < 1: raise EvidenceValidationError("run_number must be positive")
    if run.contaminated or run.contamination_reasons: return CaseScore(False,0,0,0,0,0,0,0,0,0,0,0,0,0)
    scorable = answer.detectability not in {Detectability.LATER_EVIDENCE_ONLY,Detectability.REVIEW_TIME_UNKNOWABLE,Detectability.RUNTIME_EVIDENCE_REQUIRED}
    expected={d.defect_id:d for d in answer.defects} if scorable else {}
    findings={f.finding_id:f for f in run.findings}
    matched=[]
    for f in findings.values():
        candidates=[d for d in expected.values() if set(f.attack_ids)&set(d.attack_ids)]
        if len(candidates)==1 and f.supported: matched.append((f,candidates[0]))
    matched_defects={d.defect_id for _,d in matched}
    weights={FindingSeverity.LOW:1,FindingSeverity.MEDIUM:2,FindingSeverity.HIGH:4,FindingSeverity.CRITICAL:8}
    sev_possible=sum(weights[d.severity] for d in expected.values())
    sev_credit=sum(weights[d.severity] if f.severity is d.severity else weights[d.severity]*0.5 for f,d in matched)
    blockers=[f for f in findings.values() if f.blocking]
    tp_blockers=sum(1 for f,d in matched if f.blocking)
    false_blocks=len(blockers)-tp_blockers if answer.outcome in {CaseOutcome.CLEAN,CaseOutcome.RED_HERRING} else max(0,len(blockers)-tp_blockers)
    evidence=_mean([1.0 if f.evidence_refs and f.supported else 0.0 for f in findings.values()]) or 0.0
    fix=_mean([1.0 if set(d.minimum_repair_refs).issubset(set(f.repair_refs)) and set(f.repair_refs).issubset(set(d.minimum_repair_refs)) else 0.0 for f,d in matched]) or 0.0
    tests=_mean([1.0 if set(f.test_recommendations).issubset(set(d.regression_recommendations)) and f.test_recommendations else 0.0 for f,d in matched]) or 0.0
    manual=1.0 if (answer.outcome is CaseOutcome.MANUAL_REVIEW)==run.manual_review else 0.0
    unsupported=sum(1 for f in findings.values() if not f.supported)
    return CaseScore(True,len(matched_defects),len(expected),len(findings),len(matched),len(blockers),tp_blockers,false_blocks,sev_credit,sev_possible,evidence,fix,tests,manual,unsupported)

def aggregate_metrics(scores: tuple[CaseScore,...], runs: tuple[BenchmarkRun,...]) -> BenchmarkMetrics:
    eligible=[s for s in scores if s.eligible]; total_findings=sum(s.substantive_findings for s in eligible); total_blockers=sum(s.blocking_findings for s in eligible)
    controls=sum(1 for s in eligible if s.scorable_defects==0); false_blocks=sum(s.false_blocks for s in eligible)
    grouped: dict[tuple[str,str,str],list[frozenset[str]]]={}
    for r in runs:
        if not r.contaminated: grouped.setdefault((r.case_id,r.model_identity,r.reasoning_setting),[]).append(frozenset(f.finding_id for f in r.findings if f.blocking))
    stability=[]
    for values in grouped.values():
        if len(values)>1:
            base=values[0]; stability.extend(1.0 if value==base else 0.0 for value in values[1:])
    def ratio(a:int|float,b:int|float): return a/b if b else None
    return BenchmarkMetrics(ratio(sum(s.detected_defects for s in eligible),sum(s.scorable_defects for s in eligible)),ratio(sum(s.severity_credit for s in eligible),sum(s.severity_possible for s in eligible)),ratio(sum(s.true_positive_findings for s in eligible),total_findings),ratio(sum(s.true_positive_blockers for s in eligible),total_blockers),ratio(false_blocks,controls),_mean([ratio(s.severity_credit,s.severity_possible) for s in eligible if s.severity_possible]) ,_mean([s.evidence_quality for s in eligible]),_mean([s.fix_boundary_accuracy for s in eligible]),_mean([s.test_recommendation_quality for s in eligible]),_mean([s.manual_review_calibration for s in eligible]),ratio(sum(s.unsupported_claims for s in eligible),total_findings),_mean(stability),len(eligible),len(scores)-len(eligible))
