"""Evidence-backed substantive review findings and deterministic clearing semantics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable

from .models import EvidenceValidationError, deterministic_id
from .review_attack_plan import RequiredAttack
from .review_evidence import review_invalidation_scope

MAX_ITEMS = 256
MAX_TEXT = 10_000


class FindingSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingState(str, Enum):
    CURRENT = "current"
    RESOLVED = "resolved"
    STALE = "stale"
    SUPERSEDED = "superseded"
    MANUAL_REVIEW = "manual-review"


class ClearingEvidenceClass(str, Enum):
    REGRESSION_TEST = "regression-test"
    EXACT_HEAD_VALIDATION = "exact-head-validation"
    INVARIANT_PROOF = "invariant-proof"
    SURFACE_ABSENT = "surface-absent"
    SUPERSEDED_CONTRACT = "superseded-contract"


@dataclass(frozen=True, slots=True)
class ClearingCondition:
    evidence_class: ClearingEvidenceClass
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubstantiveReviewFinding:
    attack_id: str
    reviewed_head_sha: str
    invariant: str
    affected_surface_refs: tuple[str, ...]
    failure_scenario: str
    severity: FindingSeverity
    supporting_evidence_refs: tuple[str, ...]
    clearing_condition: ClearingCondition
    state: FindingState = FindingState.CURRENT
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
        identity = {
            "attack_id": self.attack_id,
            "reviewed_head_sha": self.reviewed_head_sha,
            "invariant": self.invariant,
            "affected_surface_refs": self.affected_surface_refs,
            "failure_scenario": self.failure_scenario,
            "severity": self.severity.value,
            "supporting_evidence_refs": self.supporting_evidence_refs,
            "clearing_condition": {
                "evidence_class": self.clearing_condition.evidence_class.value,
                "evidence_refs": self.clearing_condition.evidence_refs,
            },
        }
        return deterministic_id(identity)

    @property
    def blocks_review(self) -> bool:
        return self.state in {FindingState.CURRENT, FindingState.MANUAL_REVIEW}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        data["state"] = self.state.value
        data["clearing_condition"]["evidence_class"] = self.clearing_condition.evidence_class.value
        data["finding_id"] = self.finding_id
        data["blocks_review"] = self.blocks_review
        return data


@dataclass(frozen=True, slots=True)
class ReviewSuggestion:
    affected_surface_refs: tuple[str, ...]
    observation: str
    rationale: str
    blocking: bool = False
    satisfies_required_attack: bool = False
    counts_as_discovered_defect: bool = False
    creates_authority: bool = False


@dataclass(frozen=True, slots=True)
class FindingCurrentness:
    state: FindingState
    invalidated_surface_refs: tuple[str, ...]


def _text(value: Any, field: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > MAX_TEXT:
        raise EvidenceValidationError(f"{field} must be a bounded non-empty string")
    return value.strip()


def _sha(value: Any, field: str) -> str:
    text = _text(value, field).lower()
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise EvidenceValidationError(f"{field} must be a 40-character hexadecimal SHA")
    return text


def _items(values: Iterable[str], field: str, *, required: bool = True) -> tuple[str, ...]:
    if type(values) not in {tuple, list} or len(values) > MAX_ITEMS:
        raise EvidenceValidationError(f"{field} must be a bounded list or tuple")
    result = tuple(sorted({_text(value, f"{field} item") for value in values}))
    if required and not result:
        raise EvidenceValidationError(f"{field} must not be empty")
    return result


def build_substantive_finding(
    *,
    attack: RequiredAttack,
    invariant: str,
    affected_surface_refs: tuple[str, ...] | list[str],
    failure_scenario: str,
    severity: FindingSeverity,
    supporting_evidence_refs: tuple[str, ...] | list[str],
    clearing_evidence_class: ClearingEvidenceClass,
    clearing_evidence_refs: tuple[str, ...] | list[str],
) -> SubstantiveReviewFinding:
    """Build a falsifiable finding tied to one existing CRH5 attack."""
    if type(attack) is not RequiredAttack:
        raise EvidenceValidationError("attack must be an existing CRH5 RequiredAttack")
    if type(severity) is not FindingSeverity:
        raise EvidenceValidationError("severity must use the finite FindingSeverity vocabulary")
    if type(clearing_evidence_class) is not ClearingEvidenceClass:
        raise EvidenceValidationError("clearing evidence class is unsupported")
    canonical_invariant = _text(invariant, "invariant")
    if canonical_invariant != attack.invariant:
        raise EvidenceValidationError("finding invariant must match its CRH5 attack invariant")
    surfaces = _items(affected_surface_refs, "affected_surface_refs")
    if not set(surfaces).issubset(set(attack.affected_surface_refs)):
        raise EvidenceValidationError("finding surface must be bounded by the CRH5 attack surface")
    return SubstantiveReviewFinding(
        attack_id=attack.attack_id,
        reviewed_head_sha=_sha(attack.reviewed_head_sha, "reviewed_head_sha"),
        invariant=canonical_invariant,
        affected_surface_refs=surfaces,
        failure_scenario=_text(failure_scenario, "failure_scenario"),
        severity=severity,
        supporting_evidence_refs=_items(supporting_evidence_refs, "supporting_evidence_refs"),
        clearing_condition=ClearingCondition(
            evidence_class=clearing_evidence_class,
            evidence_refs=_items(clearing_evidence_refs, "clearing_evidence_refs"),
        ),
    )


def build_suggestion(*, affected_surface_refs: tuple[str, ...] | list[str], observation: str, rationale: str) -> ReviewSuggestion:
    """Represent style/maintainability feedback without promoting it to defect evidence."""
    return ReviewSuggestion(
        affected_surface_refs=_items(affected_surface_refs, "affected_surface_refs", required=False),
        observation=_text(observation, "observation"),
        rationale=_text(rationale, "rationale"),
    )


def resolve_finding(
    finding: SubstantiveReviewFinding,
    *,
    evidence_class: ClearingEvidenceClass,
    evidence_refs: tuple[str, ...] | list[str],
    evidence_head_sha: str,
) -> SubstantiveReviewFinding:
    """Resolve only with the evidence class/refs named by the deterministic clearing condition."""
    if type(finding) is not SubstantiveReviewFinding:
        raise EvidenceValidationError("finding must be a SubstantiveReviewFinding")
    if evidence_class is not finding.clearing_condition.evidence_class:
        raise EvidenceValidationError("clearing evidence class does not satisfy the finding condition")
    supplied = _items(evidence_refs, "evidence_refs")
    required = set(finding.clearing_condition.evidence_refs)
    if not required.issubset(set(supplied)):
        raise EvidenceValidationError("required clearing evidence is missing")
    if _sha(evidence_head_sha, "evidence_head_sha") != finding.reviewed_head_sha:
        raise EvidenceValidationError("clearing evidence must be current for the reviewed exact head")
    return SubstantiveReviewFinding(
        **{**asdict(finding), "clearing_condition": finding.clearing_condition, "state": FindingState.RESOLVED, "clearing_evidence_refs": supplied}
    )


def finding_currentness(
    finding: SubstantiveReviewFinding,
    *,
    current_head_sha: str,
    changed_paths_since_review: tuple[str, ...] | list[str],
    material_change_kinds: tuple[str, ...] | list[str],
) -> FindingCurrentness:
    """Reuse CRH1 proportional invalidation; do not create a second currentness engine."""
    current = _sha(current_head_sha, "current_head_sha")
    invalidated = review_invalidation_scope(
        prior_reviewed_head=finding.reviewed_head_sha,
        current_head=current,
        changed_paths_since_review=changed_paths_since_review,
        material_change_kinds=material_change_kinds,
        previously_reviewed_paths=finding.affected_surface_refs,
    )
    if current == finding.reviewed_head_sha:
        return FindingCurrentness(finding.state, ())
    if invalidated:
        return FindingCurrentness(FindingState.STALE, invalidated)
    return FindingCurrentness(finding.state, ())
