"""CRH7 provider-neutral review coverage and test-adequacy evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable

from .models import EvidenceValidationError, deterministic_id
from .review_attack_plan import ReviewAttackPlan, RequiredAttack
from .review_evidence import review_invalidation_scope
from .review_findings import FindingState, SubstantiveReviewFinding

MAX_ITEMS = 256
MAX_TEXT = 10_000
ALLOWED_ADEQUACY_RECOMMENDATIONS = frozenset({"property-test-candidate", "mutation-test-candidate"})


class CoverageStatus(str, Enum):
    EXAMINED_CLEAR = "examined-clear"
    EXAMINED_FINDING = "examined-finding"
    NOT_APPLICABLE = "not-applicable"
    UNEXAMINED_BLOCKING = "unexamined-blocking"
    MANUAL_REVIEW = "manual-review"
    STALE = "stale"


class AdequacyStatus(str, Enum):
    ADEQUATE = "adequate"
    INADEQUATE = "inadequate"
    NOT_APPLICABLE = "not-applicable"
    MANUAL_REVIEW = "manual-review"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class ReviewCoverageObservation:
    attack_id: str
    reviewed_head_sha: str
    review_execution_id: str
    disposition: CoverageStatus
    evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewCoverageRecord:
    attack_id: str
    reviewed_head_sha: str
    affected_surface_refs: tuple[str, ...]
    review_execution_id: str
    coverage_status: CoverageStatus
    finding_ids: tuple[str, ...]
    bounded_evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]
    execution_authorized: bool = False
    merge_authorized: bool = False
    closure_authorized: bool = False
    readiness_authorized: bool = False
    production_authorized: bool = False
    protected_setting_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False

    @property
    def coverage_id(self) -> str:
        return deterministic_id(asdict(self))

    @property
    def blocks_review(self) -> bool:
        return self.coverage_status in {
            CoverageStatus.UNEXAMINED_BLOCKING,
            CoverageStatus.MANUAL_REVIEW,
            CoverageStatus.STALE,
        }


@dataclass(frozen=True, slots=True)
class TestEvidence:
    tested_head_sha: str
    evidence_refs: tuple[str, ...]
    exercised_obligations: tuple[str, ...]
    evidence_surface_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TestAdequacyRecord:
    attack_id: str
    tested_head_sha: str
    adequacy_status: AdequacyStatus
    satisfied_obligations: tuple[str, ...]
    missing_obligations: tuple[str, ...]
    bounded_evidence_refs: tuple[str, ...]
    recommendations: tuple[str, ...]
    execution_authorized: bool = False
    merge_authorized: bool = False
    closure_authorized: bool = False
    readiness_authorized: bool = False
    production_authorized: bool = False
    protected_setting_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False

    @property
    def adequacy_id(self) -> str:
        return deterministic_id(asdict(self))


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > MAX_TEXT:
        raise EvidenceValidationError(f"{field} must be a bounded non-empty string")
    return value.strip()


def _sha(value: object, field: str) -> str:
    text = _text(value, field).lower()
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise EvidenceValidationError(f"{field} must be a 40-character hexadecimal SHA")
    return text


def _items(values: Iterable[str], field: str, *, required: bool = False) -> tuple[str, ...]:
    if type(values) not in {tuple, list} or len(values) > MAX_ITEMS:
        raise EvidenceValidationError(f"{field} must be a bounded list or tuple")
    result = tuple(sorted({_text(value, f"{field} item") for value in values}))
    if required and not result:
        raise EvidenceValidationError(f"{field} must not be empty")
    return result


def _attack_map(plan: ReviewAttackPlan) -> dict[str, RequiredAttack]:
    if type(plan) is not ReviewAttackPlan:
        raise EvidenceValidationError("plan must be a ReviewAttackPlan")
    return {attack.attack_id: attack for attack in plan.required_attacks}


def _coverage_invalidated(
    attack: RequiredAttack,
    *,
    current_head_sha: str,
    changed_paths_since_review: tuple[str, ...] | list[str],
    material_change_kinds: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    return review_invalidation_scope(
        prior_reviewed_head=attack.reviewed_head_sha,
        current_head=current_head_sha,
        changed_paths_since_review=changed_paths_since_review,
        material_change_kinds=material_change_kinds,
        previously_reviewed_paths=attack.affected_surface_refs,
    )


def normalize_review_coverage(
    *,
    plan: ReviewAttackPlan,
    observations: tuple[ReviewCoverageObservation, ...] | list[ReviewCoverageObservation],
    findings: tuple[SubstantiveReviewFinding, ...] | list[SubstantiveReviewFinding] = (),
    current_head_sha: str | None = None,
    changed_paths_since_review: tuple[str, ...] | list[str] = (),
    material_change_kinds: tuple[str, ...] | list[str] = (),
) -> tuple[ReviewCoverageRecord, ...]:
    """Return one deterministic fail-closed disposition for every required CRH5 attack."""
    attacks = _attack_map(plan)
    if type(observations) not in {tuple, list} or len(observations) > MAX_ITEMS:
        raise EvidenceValidationError("coverage observations must be bounded")
    if type(findings) not in {tuple, list} or len(findings) > MAX_ITEMS:
        raise EvidenceValidationError("findings must be bounded")
    current_head = _sha(current_head_sha or plan.reviewed_head_sha, "current_head_sha")
    changed_paths = _items(changed_paths_since_review, "changed_paths_since_review")
    material_kinds = _items(material_change_kinds, "material_change_kinds")

    if plan.manual_review_reasons:
        return ()

    by_attack: dict[str, list[ReviewCoverageObservation]] = {attack_id: [] for attack_id in attacks}
    for observation in observations:
        if type(observation) is not ReviewCoverageObservation:
            raise EvidenceValidationError("coverage observations must use ReviewCoverageObservation")
        if observation.attack_id not in attacks:
            raise EvidenceValidationError("coverage observation references unknown attack")
        if type(observation.disposition) is not CoverageStatus:
            raise EvidenceValidationError("coverage disposition is unsupported")
        _sha(observation.reviewed_head_sha, "reviewed_head_sha")
        _text(observation.review_execution_id, "review_execution_id")
        _items(observation.evidence_refs, "evidence_refs")
        _items(observation.reason_codes, "reason_codes")
        by_attack[observation.attack_id].append(observation)

    finding_map: dict[str, list[SubstantiveReviewFinding]] = {attack_id: [] for attack_id in attacks}
    for finding in findings:
        if type(finding) is not SubstantiveReviewFinding or finding.attack_id not in attacks:
            raise EvidenceValidationError("finding references unknown attack")
        finding_map[finding.attack_id].append(finding)

    records: list[ReviewCoverageRecord] = []
    for attack_id in sorted(attacks):
        attack = attacks[attack_id]
        candidates = by_attack[attack_id]
        current_findings = tuple(
            sorted(
                (finding for finding in finding_map[attack_id] if finding.state is FindingState.CURRENT),
                key=lambda item: item.finding_id,
            )
        )
        manual_findings = tuple(
            finding for finding in finding_map[attack_id] if finding.state is FindingState.MANUAL_REVIEW
        )

        if not candidates:
            status = CoverageStatus.UNEXAMINED_BLOCKING
            execution_id = "missing-review-execution"
            evidence = ()
            reasons = ("required-attack-unexamined",)
        else:
            normalized = {
                (
                    _sha(item.reviewed_head_sha, "reviewed_head_sha"),
                    _text(item.review_execution_id, "review_execution_id"),
                    item.disposition,
                    _items(item.evidence_refs, "evidence_refs"),
                    _items(item.reason_codes, "reason_codes"),
                )
                for item in candidates
            }
            if len(normalized) != 1:
                status = CoverageStatus.MANUAL_REVIEW
                execution_id = "conflicting-review-observations"
                evidence = tuple(sorted({ref for item in candidates for ref in item.evidence_refs}))
                reasons = ("contradictory-coverage-observations",)
            else:
                head, execution_id, status, evidence, reasons = next(iter(normalized))
                if head != attack.reviewed_head_sha:
                    status = CoverageStatus.STALE
                    reasons = tuple(sorted(set(reasons) | {"reviewed-head-stale"}))
                elif manual_findings:
                    status = CoverageStatus.MANUAL_REVIEW
                    reasons = tuple(sorted(set(reasons) | {"finding-currentness-manual-review"}))
                elif status in {CoverageStatus.EXAMINED_CLEAR, CoverageStatus.EXAMINED_FINDING} and not evidence:
                    status = CoverageStatus.MANUAL_REVIEW
                    reasons = tuple(sorted(set(reasons) | {"examined-disposition-requires-bounded-evidence"}))
                elif status is CoverageStatus.EXAMINED_CLEAR and current_findings:
                    status = CoverageStatus.MANUAL_REVIEW
                    reasons = tuple(sorted(set(reasons) | {"clear-conflicts-with-current-finding"}))
                elif status is CoverageStatus.EXAMINED_FINDING and not current_findings:
                    status = CoverageStatus.MANUAL_REVIEW
                    reasons = tuple(sorted(set(reasons) | {"finding-disposition-without-current-finding"}))
                elif status is CoverageStatus.NOT_APPLICABLE and (not evidence or not reasons):
                    status = CoverageStatus.MANUAL_REVIEW
                    reasons = tuple(sorted(set(reasons) | {"not-applicable-requires-bounded-evidence"}))

        invalidated = _coverage_invalidated(
            attack,
            current_head_sha=current_head,
            changed_paths_since_review=changed_paths,
            material_change_kinds=material_kinds,
        )
        if current_head != attack.reviewed_head_sha and invalidated:
            status = CoverageStatus.STALE
            reasons = tuple(sorted(set(reasons) | {"crh1-affected-surface-invalidated"}))

        records.append(
            ReviewCoverageRecord(
                attack_id=attack_id,
                reviewed_head_sha=attack.reviewed_head_sha,
                affected_surface_refs=attack.affected_surface_refs,
                review_execution_id=execution_id,
                coverage_status=status,
                finding_ids=tuple(finding.finding_id for finding in current_findings),
                bounded_evidence_refs=tuple(evidence),
                reason_codes=tuple(reasons),
            )
        )
    return tuple(records)


def assess_test_adequacy(
    *,
    attack: RequiredAttack,
    evidence: TestEvidence | None,
    required_test_obligations: tuple[str, ...] | list[str] = (),
    current_head_sha: str | None = None,
    changed_paths_since_test: tuple[str, ...] | list[str] = (),
    material_change_kinds: tuple[str, ...] | list[str] = (),
    recommendations: tuple[str, ...] | list[str] = (),
) -> TestAdequacyRecord:
    """Compare caller-supplied test obligations/evidence without selecting or executing tests."""
    if type(attack) is not RequiredAttack:
        raise EvidenceValidationError("attack must be a RequiredAttack")

    required = _items(required_test_obligations, "required_test_obligations")
    attack_obligations = set(attack.bounded_evidence_requirements)
    if not set(required).issubset(attack_obligations):
        raise EvidenceValidationError("required test obligations must come from the CRH5 attack")
    recommended = _items(recommendations, "recommendations")
    if not set(recommended).issubset(ALLOWED_ADEQUACY_RECOMMENDATIONS):
        raise EvidenceValidationError("unsupported test-adequacy recommendation")

    if not required:
        return TestAdequacyRecord(
            attack_id=attack.attack_id,
            tested_head_sha=attack.reviewed_head_sha,
            adequacy_status=AdequacyStatus.NOT_APPLICABLE,
            satisfied_obligations=(),
            missing_obligations=(),
            bounded_evidence_refs=(),
            recommendations=recommended,
        )

    if evidence is None:
        return TestAdequacyRecord(
            attack_id=attack.attack_id,
            tested_head_sha=attack.reviewed_head_sha,
            adequacy_status=AdequacyStatus.INADEQUATE,
            satisfied_obligations=(),
            missing_obligations=required,
            bounded_evidence_refs=(),
            recommendations=tuple(sorted(set(recommended) | {"add-material-regression-evidence"})),
        )
    if type(evidence) is not TestEvidence:
        raise EvidenceValidationError("evidence must be TestEvidence")

    tested_head = _sha(evidence.tested_head_sha, "tested_head_sha")
    current_head = _sha(current_head_sha or attack.reviewed_head_sha, "current_head_sha")
    refs = _items(evidence.evidence_refs, "evidence_refs", required=True)
    exercised = _items(evidence.exercised_obligations, "exercised_obligations")
    evidence_surfaces = _items(evidence.evidence_surface_refs, "evidence_surface_refs")
    changed_paths = _items(changed_paths_since_test, "changed_paths_since_test")
    material_kinds = _items(material_change_kinds, "material_change_kinds")

    if not set(exercised).issubset(attack_obligations):
        raise EvidenceValidationError("test evidence obligations must come from the CRH5 attack")

    semantic_invalidated = review_invalidation_scope(
        prior_reviewed_head=tested_head,
        current_head=current_head,
        changed_paths_since_review=changed_paths,
        material_change_kinds=material_kinds,
        previously_reviewed_paths=attack.affected_surface_refs,
    )
    test_surface_changed = bool(set(changed_paths) & set(evidence_surfaces))
    if tested_head != current_head and (semantic_invalidated or test_surface_changed):
        return TestAdequacyRecord(
            attack_id=attack.attack_id,
            tested_head_sha=tested_head,
            adequacy_status=AdequacyStatus.STALE,
            satisfied_obligations=(),
            missing_obligations=required,
            bounded_evidence_refs=refs,
            recommendations=tuple(sorted(set(recommended) | {"refresh-exact-head-test-evidence"})),
        )

    satisfied = tuple(sorted(set(required) & set(exercised)))
    missing = tuple(sorted(set(required) - set(exercised)))
    status = AdequacyStatus.ADEQUATE if not missing else AdequacyStatus.INADEQUATE
    final_recommendations = set(recommended)
    if missing:
        final_recommendations.add("add-material-regression-evidence")
    return TestAdequacyRecord(
        attack_id=attack.attack_id,
        tested_head_sha=tested_head,
        adequacy_status=status,
        satisfied_obligations=satisfied,
        missing_obligations=missing,
        bounded_evidence_refs=refs,
        recommendations=tuple(sorted(final_recommendations)),
    )
