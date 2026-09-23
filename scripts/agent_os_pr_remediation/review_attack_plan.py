"""Deterministic provider-neutral Review Attack Plans built from CRH1 evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import EvidenceValidationError, deterministic_id
from .review_evidence import ADVERSARIAL_RISKS, MANUAL_RISKS, ReviewDepth, ReviewEvidencePacket


@dataclass(frozen=True, slots=True)
class RequiredAttack:
    attack_family: str
    invariant: str
    reviewed_head_sha: str
    affected_surface_refs: tuple[str, ...]
    bounded_evidence_requirements: tuple[str, ...]
    reason_codes: tuple[str, ...]

    @property
    def attack_id(self) -> str:
        return deterministic_id(asdict(self))


@dataclass(frozen=True, slots=True)
class ReviewAttackPlan:
    reviewed_head_sha: str
    risk_classes: tuple[str, ...]
    required_attacks: tuple[RequiredAttack, ...]
    activated_contracts: tuple[str, ...]
    bounded_evidence_requirements: tuple[str, ...]
    manual_review_reasons: tuple[str, ...]
    execution_authorized: bool = False
    merge_authorized: bool = False
    closure_authorized: bool = False
    readiness_authorized: bool = False
    production_authorized: bool = False
    protected_setting_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False

    @property
    def plan_id(self) -> str:
        return deterministic_id(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for attack, serialized in zip(self.required_attacks, data["required_attacks"]):
            serialized["attack_id"] = attack.attack_id
        data["plan_id"] = self.plan_id
        return data


# Finite defect-class catalog. Each tuple is (family, invariant, evidence obligations, reason code).
_ATTACKS: dict[str, tuple[tuple[str, str, tuple[str, ...], str], ...]] = {
    "parser": (
        ("parser", "malformed or unsupported input fails closed", ("malformed-input-case", "fail-closed-result"), "parser-malformed-fail-closed"),
        ("parser", "ambiguous or multiple valid-looking targets are not resolved by first match", ("ambiguous-input-case", "selection-result"), "parser-ambiguity-first-match"),
        ("parser", "quoted, commented, duplicated, missing, or stale values cannot impersonate the canonical target", ("noncanonical-input-case", "canonical-target-proof"), "parser-noncanonical-target"),
    ),
    "authorization": (
        ("authorization", "evidence never creates authority", ("authority-source-proof", "non-authority-output"), "authorization-evidence-not-authority"),
        ("authorization", "authorization is current and bound to the intended identity and SHA", ("authorization-currentness", "identity-sha-binding"), "authorization-current-identity"),
        ("authorization", "permissions do not widen beyond the bounded authorized surface", ("permission-boundary", "excluded-surface-proof"), "authorization-no-privilege-widening"),
    ),
    "state-machine": (
        ("state-machine", "illegal, skipped, or impossible transitions fail closed", ("illegal-transition-case", "transition-result"), "state-illegal-transition"),
        ("state-machine", "partial or interrupted effects remain distinguishable from terminal success", ("partial-effect-case", "terminal-state-proof"), "state-partial-effect"),
        ("state-machine", "retry and repeated transition behavior is idempotent and converges", ("retry-case", "idempotency-or-convergence-proof"), "state-retry-idempotency"),
    ),
    "persistence": (
        ("persistence", "partial, stale, corrupt, or incompatible persisted state fails closed", ("persisted-state-case", "validation-result"), "persistence-corrupt-version"),
        ("persistence", "replay, recovery, rollback, and migration ordering preserve contract compatibility", ("recovery-or-migration-case", "compatibility-result"), "persistence-recovery-ordering"),
    ),
    "concurrency": (
        ("concurrency", "stale or foreign leases cannot authorize duplicate execution", ("lease-identity-case", "admission-result"), "concurrency-stale-foreign-lease"),
        ("concurrency", "race, takeover, fencing, and replay cannot create duplicate mutation or lost update", ("race-or-replay-case", "fencing-result"), "concurrency-fencing-duplicate"),
    ),
    "workflow": (
        ("workflow", "transport success cannot impersonate semantic validation success", ("transport-result", "semantic-result"), "workflow-transport-vs-semantic"),
        ("workflow", "validation evidence is bound to the intended exact head identity", ("tested-sha", "expected-head-sha"), "workflow-wrong-sha"),
        ("workflow", "stale, skipped, cancelled, superseded, duplicate, or conflicting evidence cannot synthesize green", ("status-lineage", "currentness-proof"), "workflow-stale-conflicting-evidence"),
    ),
    "integration": (
        ("integration", "provider success semantics match the intended Agent OS state transition", ("provider-response", "intended-state-proof"), "integration-provider-semantics"),
        ("integration", "partial effects, retries, and reconciliation cannot duplicate or silently lose mutation", ("effect-identity", "reconciliation-result"), "integration-partial-retry-reconcile"),
    ),
    "architecture": (
        ("architecture", "one canonical owner and source of truth remain authoritative", ("owner-reference", "source-of-truth-reference"), "architecture-single-owner"),
        ("architecture", "no hidden authority transfer, bypass, compatibility break, or parallel contract is introduced", ("caller-path", "contract-boundary-proof"), "architecture-no-bypass-parallel-contract"),
    ),
}

_RISK_TO_FAMILY = {
    "parser": "parser", "resolver": "parser", "selector": "parser",
    "authorization": "authorization", "permissions": "authorization", "security": "authorization",
    "state-machine": "state-machine", "retry-idempotency-reconciliation": "state-machine",
    "repeated-repair-failure": "state-machine", "post-merge-regression-repair": "state-machine",
    "persistence": "persistence", "migration": "persistence",
    "concurrency": "concurrency", "lease-fencing": "concurrency",
    "workflow-ci-authority": "workflow",
    "cross-system-integration": "integration", "external-api-semantics": "integration", "external-mutation": "integration", "production-impact": "integration",
    "architecture-ownership-interface": "architecture",
}


def _affected_surfaces(packet: ReviewEvidencePacket, family: str) -> tuple[str, ...]:
    """Reuse CRH1 supplied surface identity; do not infer a second changed-path model."""
    refs = set(packet.changed_files)
    if family == "workflow":
        refs.update(packet.workflow_changes)
    if family == "architecture":
        refs.update(packet.changed_contracts)
        refs.update(packet.dependency_changes)
    return tuple(sorted(refs))


def build_review_attack_plan(packet: ReviewEvidencePacket) -> ReviewAttackPlan:
    """Project one deterministic finite attack plan from a CRH1 evidence packet."""
    if type(packet) is not ReviewEvidencePacket:
        raise EvidenceValidationError("packet must be a ReviewEvidencePacket")

    risks = tuple(sorted({item.risk_class for item in packet.risk_evidence}))
    manual: list[str] = []
    unknown = tuple(risk for risk in risks if risk not in ADVERSARIAL_RISKS and risk not in MANUAL_RISKS)
    if packet.review_depth is ReviewDepth.MANUAL:
        manual.append("review-depth-requires-manual-decision")
    if any(risk in MANUAL_RISKS for risk in risks):
        manual.append("risk-evidence-ambiguous-or-conflicting")
    if unknown:
        manual.append("unknown-risk-class:" + ",".join(unknown))

    attacks: dict[str, RequiredAttack] = {}
    if not manual and packet.review_depth is ReviewDepth.ADVERSARIAL:
        for risk in risks:
            family = _RISK_TO_FAMILY.get(risk)
            if family is None:
                manual.append("unmapped-adversarial-risk:" + risk)
                continue
            for attack_family, invariant, obligations, reason in _ATTACKS[family]:
                attack = RequiredAttack(
                    attack_family=attack_family,
                    invariant=invariant,
                    reviewed_head_sha=packet.head_sha,
                    affected_surface_refs=_affected_surfaces(packet, family),
                    bounded_evidence_requirements=obligations,
                    reason_codes=(reason,),
                )
                attacks[attack.attack_id] = attack

    ordered = tuple(attacks[key] for key in sorted(attacks)) if not manual else ()
    obligations = tuple(sorted({item for attack in ordered for item in attack.bounded_evidence_requirements}))
    return ReviewAttackPlan(
        reviewed_head_sha=packet.head_sha,
        risk_classes=risks,
        required_attacks=ordered,
        activated_contracts=tuple(sorted(packet.activated_references)),
        bounded_evidence_requirements=obligations,
        manual_review_reasons=tuple(sorted(set(manual))),
    )
