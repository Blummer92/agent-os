"""Provider-neutral evidence-backed review findings and deterministic clearing."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any

from .models import EvidenceValidationError, deterministic_id
from .review_attack_plan import RequiredAttack


class FindingSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(str, Enum):
    OPEN = "open"
    RESOLVED_CURRENT = "resolved-current"
    STALE = "stale"
    SUPERSEDED = "superseded"
    MANUAL_REVIEW = "manual-review"


class ClearingEvidenceClass(str, Enum):
    REGRESSION_TEST = "regression-test"
    EXACT_HEAD_VALIDATION = "exact-head-validation"
    BOUNDED_INVARIANT_PROOF = "bounded-invariant-proof"
    CURRENT_DIFF_ABSENCE = "current-diff-absence"
    SUPERSEDED_CONTRACT = "superseded-contract"


@dataclass(frozen=True, slots=True)
class ClearingCondition:
    evidence_class: ClearingEvidenceClass
    evidence_identity: str


@dataclass(frozen=True, slots=True)
class ReviewSuggestion:
    affected_path: str
    suggestion: str
    reviewed_head_sha: str
    symbol_or_contract_ref: str | None = None
    blocking: bool = False

    @property
    def suggestion_id(self) -> str:
        return deterministic_id(asdict(self))


@dataclass(frozen=True, slots=True)
class EvidenceBackedReviewFinding:
    attack_id: str | None
    threatened_invariant: str
    affected_path: str
    failure_scenario: str
    severity: FindingSeverity
    supporting_evidence_refs: tuple[str, ...]
    clearing_condition: ClearingCondition
    reviewed_head_sha: str
    symbol_or_contract_ref: str | None = None
    status: FindingStatus = FindingStatus.OPEN
    clearing_evidence_refs: tuple[str, ...] = ()
    execution_authorized: bool = False
    merge_authorized: bool = False
    closure_authorized: bool = False
    readiness_authorized: bool = False
    production_authorized: bool = False
    protected_setting_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False

    @property
    def finding_id(self) -> str:
        # Lifecycle/evidence updates do not change defect identity.
        identity = {
            "attack_id": self.attack_id,
            "threatened_invariant": self.threatened_invariant,
            "affected_path": self.affected_path,
            "symbol_or_contract_ref": self.symbol_or_contract_ref,
            "failure_scenario": self.failure_scenario,
            "severity": self.severity.value,
            "supporting_evidence_refs": self.supporting_evidence_refs,
            "clearing_condition": asdict(self.clearing_condition),
            "reviewed_head_sha": self.reviewed_head_sha,
        }
        return deterministic_id(identity)

    @property
    def blocking(self) -> bool:
        return self.status in {FindingStatus.OPEN, FindingStatus.STALE, FindingStatus.MANUAL_REVIEW}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["finding_id"] = self.finding_id
        data["severity"] = self.severity.value
        data["status"] = self.status.value
        data["clearing_condition"]["evidence_class"] = self.clearing_condition.evidence_class.value
        return data


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 10_000:
        raise EvidenceValidationError(f"{field} must be bounded non-empty text")
    return value.strip()


def _sha(value: object) -> str:
    text = _text(value, "reviewed_head_sha").lower()
    if len(text) != 40 or any(c not in "0123456789abcdef" for c in text):
        raise EvidenceValidationError("reviewed_head_sha must be a 40-character hexadecimal SHA")
    return text


def _refs(values: object, field: str) -> tuple[str, ...]:
    if type(values) not in {tuple, list} or len(values) > 256:
        raise EvidenceValidationError(f"{field} must be a bounded list or tuple")
    result = tuple(sorted({_text(v, field) for v in values}))
    return result


def build_review_suggestion(*, affected_path: object, suggestion: object, reviewed_head_sha: object,
                            symbol_or_contract_ref: object = None) -> ReviewSuggestion:
    symbol = None if symbol_or_contract_ref is None else _text(symbol_or_contract_ref, "symbol_or_contract_ref")
    return ReviewSuggestion(_text(affected_path, "affected_path"), _text(suggestion, "suggestion"), _sha(reviewed_head_sha), symbol)


def build_review_finding(*, attack: RequiredAttack | None, threatened_invariant: object,
                         affected_path: object, failure_scenario: object, severity: object,
                         supporting_evidence_refs: object, clearing_evidence_class: object,
                         clearing_evidence_identity: object, reviewed_head_sha: object,
                         symbol_or_contract_ref: object = None) -> EvidenceBackedReviewFinding:
    if attack is not None and type(attack) is not RequiredAttack:
        raise EvidenceValidationError("attack must be a RequiredAttack when supplied")
    if type(severity) is not FindingSeverity:
        raise EvidenceValidationError("severity must be FindingSeverity")
    if type(clearing_evidence_class) is not ClearingEvidenceClass:
        raise EvidenceValidationError("clearing_evidence_class must be ClearingEvidenceClass")
    head = _sha(reviewed_head_sha)
    if attack is not None and attack.reviewed_head_sha != head:
        raise EvidenceValidationError("attack and finding reviewed head must match")
    invariant = _text(threatened_invariant, "threatened_invariant")
    if attack is not None and invariant != attack.invariant:
        raise EvidenceValidationError("finding invariant must match the linked attack")
    refs = _refs(supporting_evidence_refs, "supporting_evidence_refs")
    if not refs:
        raise EvidenceValidationError("substantive finding requires supporting evidence")
    symbol = None if symbol_or_contract_ref is None else _text(symbol_or_contract_ref, "symbol_or_contract_ref")
    return EvidenceBackedReviewFinding(
        attack_id=None if attack is None else attack.attack_id,
        threatened_invariant=invariant,
        affected_path=_text(affected_path, "affected_path"),
        symbol_or_contract_ref=symbol,
        failure_scenario=_text(failure_scenario, "failure_scenario"),
        severity=severity,
        supporting_evidence_refs=refs,
        clearing_condition=ClearingCondition(clearing_evidence_class, _text(clearing_evidence_identity, "clearing_evidence_identity")),
        reviewed_head_sha=head,
    )


def reevaluate_finding(*, finding: EvidenceBackedReviewFinding, current_head_sha: object,
                       invalidated_paths: object, clearing_evidence_refs: object = (),
                       superseded: bool = False, manual_review: bool = False) -> EvidenceBackedReviewFinding:
    """Consume CRH1-computed invalidated paths; this function does not derive invalidation scope."""
    if type(finding) is not EvidenceBackedReviewFinding:
        raise EvidenceValidationError("finding must be EvidenceBackedReviewFinding")
    current = _sha(current_head_sha)
    invalidated = _refs(invalidated_paths, "invalidated_paths")
    evidence = _refs(clearing_evidence_refs, "clearing_evidence_refs")
    if type(superseded) is not bool or type(manual_review) is not bool:
        raise EvidenceValidationError("lifecycle flags must be booleans")
    if superseded:
        status = FindingStatus.SUPERSEDED
    elif manual_review:
        status = FindingStatus.MANUAL_REVIEW
    elif current != finding.reviewed_head_sha and finding.affected_path in invalidated:
        status = FindingStatus.STALE
    elif finding.clearing_condition.evidence_identity in evidence:
        status = FindingStatus.RESOLVED_CURRENT
    elif current != finding.reviewed_head_sha:
        # CRH1 said this affected path was not invalidated; compatible evidence may survive.
        status = finding.status if finding.status is FindingStatus.RESOLVED_CURRENT else FindingStatus.OPEN
    else:
        status = FindingStatus.OPEN
    return replace(finding, status=status, clearing_evidence_refs=evidence)


def unresolved_finding_ids(items: object) -> tuple[str, ...]:
    if type(items) not in {tuple, list}:
        raise EvidenceValidationError("findings must be a list or tuple")
    if any(type(item) is not EvidenceBackedReviewFinding for item in items):
        raise EvidenceValidationError("suggestions cannot enter substantive finding sets")
    return tuple(sorted(item.finding_id for item in items if item.blocking))
