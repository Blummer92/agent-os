"""Pure-local risk-triggered code-review selection and bounded evidence packets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable

from .models import EvidenceValidationError, deterministic_id

MAX_ITEMS = 256
MAX_TEXT = 10_000
MAX_DIFF_CHARS = 64_000
MAX_PACKET_CHARS = 160_000


class ReviewDepth(str, Enum):
    NO_AI = "no-ai-review-required"
    NORMAL = "normal-review-required"
    ADVERSARIAL = "adversarial-review-required"
    MANUAL = "manual-decision-required"


ADVERSARIAL_RISKS = frozenset(
    {
        "parser",
        "resolver",
        "selector",
        "authorization",
        "permissions",
        "security",
        "state-machine",
        "persistence",
        "migration",
        "external-mutation",
        "concurrency",
        "lease-fencing",
        "retry-idempotency-reconciliation",
        "workflow-ci-authority",
        "cross-system-integration",
        "external-api-semantics",
        "production-impact",
        "architecture-ownership-interface",
        "ambiguous-evidence",
        "conflicting-evidence",
        "repeated-repair-failure",
        "post-merge-regression-repair",
    }
)

NO_AI_CHANGE_KINDS = frozenset(
    {
        "markdown-only",
        "changelog-version-only",
        "pr-metadata-only",
        "deterministic-failure-only",
        "fixture-only-no-semantic-change",
    }
)

FULL_REVIEW_INVALIDATORS = frozenset(
    {
        "public-interface",
        "architecture-ownership",
        "authorization-security",
        "dependency",
        "workflow",
        "issue-scope",
        "unrelated-implementation-surface",
    }
)


@dataclass(frozen=True, slots=True)
class ReviewRiskEvidence:
    risk_class: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewDepthDecision:
    depth: ReviewDepth
    risk_classes: tuple[str, ...]
    reasons: tuple[str, ...]
    execution_authorized: bool = False
    merge_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False


@dataclass(frozen=True, slots=True)
class ReviewEvidencePacket:
    repository: str
    issue_number: int
    pr_number: int
    base_sha: str
    head_sha: str
    metadata_fingerprint: str | None
    objective: str
    acceptance_criteria: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    non_goals: tuple[str, ...]
    authorization_ceiling: tuple[str, ...]
    changed_files: tuple[str, ...]
    bounded_diff: str
    changed_contracts: tuple[str, ...]
    dependency_changes: tuple[str, ...]
    workflow_changes: tuple[str, ...]
    risk_evidence: tuple[ReviewRiskEvidence, ...]
    validation_profiles: tuple[str, ...]
    validation_results: tuple[str, ...]
    exact_tested_sha: str | None
    failed_finding_ids: tuple[str, ...]
    repaired_finding_ids: tuple[str, ...]
    unresolved_finding_ids: tuple[str, ...]
    prior_reviewed_head: str | None
    paths_changed_since_review: tuple[str, ...]
    activated_references: tuple[str, ...]
    review_depth: ReviewDepth
    execution_authorized: bool = False
    merge_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["review_depth"] = self.review_depth.value
        return data

    @property
    def packet_id(self) -> str:
        return deterministic_id(self.to_dict())


def _text(value: Any, field: str) -> str:
    if type(value) is not str or not value or len(value) > MAX_TEXT:
        raise EvidenceValidationError(f"{field} must be a bounded non-empty string")
    return value


def _sha(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    text = _text(value, field).lower()
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise EvidenceValidationError(f"{field} must be a 40-character hexadecimal SHA")
    return text


def _items(values: Iterable[str], field: str) -> tuple[str, ...]:
    if type(values) not in {tuple, list}:
        raise EvidenceValidationError(f"{field} must be a list or tuple")
    if len(values) > MAX_ITEMS:
        raise EvidenceValidationError(f"{field} exceeds item limit")
    result = tuple(_text(value, f"{field} item") for value in values)
    if len(set(result)) != len(result):
        raise EvidenceValidationError(f"{field} contains duplicates")
    return tuple(sorted(result))


def select_review_depth(
    *,
    changed_files: tuple[str, ...] | list[str],
    change_kinds: tuple[str, ...] | list[str],
    risk_evidence: tuple[ReviewRiskEvidence, ...] | list[ReviewRiskEvidence] = (),
    deterministic_failure: bool = False,
    stale_or_conflicting_risk_evidence: bool = False,
    code_changed: bool = True,
) -> ReviewDepthDecision:
    """Select the cheapest review depth supported by deterministic supplied evidence."""

    files = _items(changed_files, "changed_files")
    kinds = _items(change_kinds, "change_kinds")
    if type(deterministic_failure) is not bool or type(stale_or_conflicting_risk_evidence) is not bool:
        raise EvidenceValidationError("review selection flags must be booleans")
    if type(code_changed) is not bool:
        raise EvidenceValidationError("code_changed must be a boolean")
    if type(risk_evidence) not in {tuple, list} or len(risk_evidence) > MAX_ITEMS:
        raise EvidenceValidationError("risk_evidence must be bounded")
    if any(type(item) is not ReviewRiskEvidence for item in risk_evidence):
        raise EvidenceValidationError("risk_evidence contains unsupported values")

    risks: list[str] = []
    reasons: list[str] = []
    for item in risk_evidence:
        risk = _text(item.risk_class, "risk_class")
        evidence = _items(item.evidence, "risk evidence")
        if not evidence:
            raise EvidenceValidationError("each risk class requires evidence")
        risks.append(risk)
        reasons.extend(f"{risk}:{entry}" for entry in evidence)

    if stale_or_conflicting_risk_evidence:
        return ReviewDepthDecision(ReviewDepth.MANUAL, tuple(sorted(set(risks))), ("risk-evidence-stale-or-conflicting",))
    if deterministic_failure:
        return ReviewDepthDecision(ReviewDepth.NO_AI, tuple(sorted(set(risks))), ("deterministic-failure-first",))
    if any(risk in ADVERSARIAL_RISKS for risk in risks):
        return ReviewDepthDecision(ReviewDepth.ADVERSARIAL, tuple(sorted(set(risks))), tuple(sorted(set(reasons))))
    if not code_changed or (kinds and set(kinds).issubset(NO_AI_CHANGE_KINDS)):
        return ReviewDepthDecision(ReviewDepth.NO_AI, tuple(sorted(set(risks))), ("no-semantic-code-review-needed",))
    if not files:
        return ReviewDepthDecision(ReviewDepth.MANUAL, tuple(sorted(set(risks))), ("changed-file-evidence-missing",))
    return ReviewDepthDecision(ReviewDepth.NORMAL, tuple(sorted(set(risks))), tuple(sorted(set(reasons))) or ("ordinary-code-change",))


def review_invalidation_scope(
    *,
    prior_reviewed_head: str,
    current_head: str,
    changed_paths_since_review: tuple[str, ...] | list[str],
    material_change_kinds: tuple[str, ...] | list[str],
    previously_reviewed_paths: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Return only the paths whose prior semantic review evidence is invalidated."""

    previous = _sha(prior_reviewed_head, "prior_reviewed_head")
    current = _sha(current_head, "current_head")
    changed = _items(changed_paths_since_review, "changed_paths_since_review")
    kinds = _items(material_change_kinds, "material_change_kinds")
    reviewed = _items(previously_reviewed_paths, "previously_reviewed_paths")
    if previous == current:
        return ()
    if set(kinds) & FULL_REVIEW_INVALIDATORS:
        return reviewed
    return tuple(path for path in changed if path in set(reviewed))


def build_review_evidence_packet(**payload: Any) -> ReviewEvidencePacket:
    """Build one bounded, provider-neutral packet from caller-supplied canonical evidence."""

    risks = payload.get("risk_evidence", ())
    if type(risks) not in {tuple, list} or any(type(item) is not ReviewRiskEvidence for item in risks):
        raise EvidenceValidationError("risk_evidence must contain ReviewRiskEvidence values")
    bounded_diff = payload.get("bounded_diff")
    if type(bounded_diff) is not str or len(bounded_diff) > MAX_DIFF_CHARS:
        raise EvidenceValidationError("bounded_diff exceeds size limit or is not text")
    depth = payload.get("review_depth")
    if type(depth) is not ReviewDepth:
        raise EvidenceValidationError("review_depth must be ReviewDepth")

    packet = ReviewEvidencePacket(
        repository=_text(payload.get("repository"), "repository"),
        issue_number=payload.get("issue_number"),
        pr_number=payload.get("pr_number"),
        base_sha=_sha(payload.get("base_sha"), "base_sha") or "",
        head_sha=_sha(payload.get("head_sha"), "head_sha") or "",
        metadata_fingerprint=payload.get("metadata_fingerprint"),
        objective=_text(payload.get("objective"), "objective"),
        acceptance_criteria=_items(payload.get("acceptance_criteria", ()), "acceptance_criteria"),
        allowed_paths=_items(payload.get("allowed_paths", ()), "allowed_paths"),
        forbidden_paths=_items(payload.get("forbidden_paths", ()), "forbidden_paths"),
        non_goals=_items(payload.get("non_goals", ()), "non_goals"),
        authorization_ceiling=_items(payload.get("authorization_ceiling", ()), "authorization_ceiling"),
        changed_files=_items(payload.get("changed_files", ()), "changed_files"),
        bounded_diff=bounded_diff,
        changed_contracts=_items(payload.get("changed_contracts", ()), "changed_contracts"),
        dependency_changes=_items(payload.get("dependency_changes", ()), "dependency_changes"),
        workflow_changes=_items(payload.get("workflow_changes", ()), "workflow_changes"),
        risk_evidence=tuple(risks),
        validation_profiles=_items(payload.get("validation_profiles", ()), "validation_profiles"),
        validation_results=_items(payload.get("validation_results", ()), "validation_results"),
        exact_tested_sha=_sha(payload.get("exact_tested_sha"), "exact_tested_sha", optional=True),
        failed_finding_ids=_items(payload.get("failed_finding_ids", ()), "failed_finding_ids"),
        repaired_finding_ids=_items(payload.get("repaired_finding_ids", ()), "repaired_finding_ids"),
        unresolved_finding_ids=_items(payload.get("unresolved_finding_ids", ()), "unresolved_finding_ids"),
        prior_reviewed_head=_sha(payload.get("prior_reviewed_head"), "prior_reviewed_head", optional=True),
        paths_changed_since_review=_items(payload.get("paths_changed_since_review", ()), "paths_changed_since_review"),
        activated_references=_items(payload.get("activated_references", ()), "activated_references"),
        review_depth=depth,
    )
    if type(packet.issue_number) is not int or packet.issue_number <= 0 or type(packet.pr_number) is not int or packet.pr_number <= 0:
        raise EvidenceValidationError("issue_number and pr_number must be positive integers")
    if packet.metadata_fingerprint is not None:
        fingerprint = _text(packet.metadata_fingerprint, "metadata_fingerprint").lower()
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise EvidenceValidationError("metadata_fingerprint must be a SHA-256 hex digest")
        object.__setattr__(packet, "metadata_fingerprint", fingerprint)
    if len(str(packet.to_dict())) > MAX_PACKET_CHARS:
        raise EvidenceValidationError("review evidence packet exceeds size limit")
    return packet
