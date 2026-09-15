"""Compose existing PR-remediation review evidence for bounded bulk repair.

BR4 is an adapter only. It reuses the canonical review-depth selector, review
packet builder, finding currentness, review invalidation, and review coverage
records. It performs no review execution, repair, validation, merge, or external
mutation and creates no second review architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from scripts.agent_os_pr_remediation.review_coverage import ReviewCoverageRecord
from scripts.agent_os_pr_remediation.review_evidence import (
    ReviewDepth,
    ReviewEvidencePacket,
    ReviewRiskEvidence,
    build_review_evidence_packet,
    review_invalidation_scope,
    select_review_depth,
)
from scripts.agent_os_pr_remediation.review_findings import (
    FindingState,
    SubstantiveReviewFinding,
    finding_currentness,
)


class BulkReviewDisposition(str, Enum):
    CLEARED = "cleared"
    REVIEW_REQUIRED = "review-required"
    REPAIR_REQUIRED = "repair-required"
    MANUAL_BLOCKED = "manual-blocked"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class BulkRepairReviewInput:
    repository: str
    issue_number: int
    pull_request_number: int
    base_sha: str
    head_sha: str
    objective: str
    acceptance_criteria: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    non_goals: tuple[str, ...]
    authorization_ceiling: tuple[str, ...]
    changed_files: tuple[str, ...]
    bounded_diff: str
    changed_contracts: tuple[str, ...] = ()
    dependency_changes: tuple[str, ...] = ()
    workflow_changes: tuple[str, ...] = ()
    risk_evidence: tuple[ReviewRiskEvidence, ...] = ()
    validation_profiles: tuple[str, ...] = ()
    validation_results: tuple[str, ...] = ()
    exact_tested_sha: str | None = None
    findings: tuple[SubstantiveReviewFinding, ...] = ()
    coverage: tuple[ReviewCoverageRecord, ...] = ()
    prior_reviewed_head: str | None = None
    paths_changed_since_review: tuple[str, ...] = ()
    material_change_kinds: tuple[str, ...] = ()
    change_kinds: tuple[str, ...] = ()
    deterministic_failure: bool = False
    stale_or_conflicting_risk_evidence: bool = False
    code_changed: bool = True


@dataclass(frozen=True, slots=True)
class BulkRepairReviewProjection:
    repository: str
    pull_request_number: int
    reviewed_head_sha: str
    review_depth: ReviewDepth
    disposition: BulkReviewDisposition
    packet: ReviewEvidencePacket
    unresolved_finding_ids: tuple[str, ...]
    repaired_finding_ids: tuple[str, ...]
    invalidated_finding_ids: tuple[str, ...]
    blocking_coverage_ids: tuple[str, ...]
    invalidated_paths: tuple[str, ...]
    reason_codes: tuple[str, ...]
    handoff_to_br3: bool
    repair_required: bool
    manual_review_required: bool
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    closure_authorized: Literal[False] = field(default=False, init=False)
    readiness_authorized: Literal[False] = field(default=False, init=False)
    production_authorized: Literal[False] = field(default=False, init=False)
    external_write_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def evaluate_bulk_repair_review(evidence: BulkRepairReviewInput) -> BulkRepairReviewProjection:
    if type(evidence) is not BulkRepairReviewInput:
        raise TypeError("evidence must be BulkRepairReviewInput")

    depth = select_review_depth(
        changed_files=evidence.changed_files,
        change_kinds=evidence.change_kinds,
        risk_evidence=evidence.risk_evidence,
        deterministic_failure=evidence.deterministic_failure,
        stale_or_conflicting_risk_evidence=evidence.stale_or_conflicting_risk_evidence,
        code_changed=evidence.code_changed,
    )

    invalidated_paths: tuple[str, ...] = ()
    if evidence.prior_reviewed_head is not None:
        invalidated_paths = review_invalidation_scope(
            prior_reviewed_head=evidence.prior_reviewed_head,
            current_head=evidence.head_sha,
            changed_paths_since_review=evidence.paths_changed_since_review,
            material_change_kinds=evidence.material_change_kinds,
            previously_reviewed_paths=evidence.changed_files,
        )

    unresolved: list[str] = []
    repaired: list[str] = []
    invalidated: list[str] = []
    for finding in evidence.findings:
        currentness = finding_currentness(
            finding,
            current_head_sha=evidence.head_sha,
            changed_paths_since_review=evidence.paths_changed_since_review,
            material_change_kinds=evidence.material_change_kinds,
        )
        if currentness.state in {FindingState.CURRENT, FindingState.MANUAL_REVIEW}:
            unresolved.append(finding.finding_id)
        elif currentness.state is FindingState.RESOLVED:
            repaired.append(finding.finding_id)
        elif currentness.state in {FindingState.STALE, FindingState.SUPERSEDED}:
            invalidated.append(finding.finding_id)

    blocking_coverage = tuple(sorted(record.coverage_id for record in evidence.coverage if record.blocks_review))

    packet = build_review_evidence_packet(
        repository=evidence.repository,
        issue_number=evidence.issue_number,
        pr_number=evidence.pull_request_number,
        base_sha=evidence.base_sha,
        head_sha=evidence.head_sha,
        metadata_fingerprint=None,
        objective=evidence.objective,
        acceptance_criteria=evidence.acceptance_criteria,
        allowed_paths=evidence.allowed_paths,
        forbidden_paths=evidence.forbidden_paths,
        non_goals=evidence.non_goals,
        authorization_ceiling=evidence.authorization_ceiling,
        changed_files=evidence.changed_files,
        bounded_diff=evidence.bounded_diff,
        changed_contracts=evidence.changed_contracts,
        dependency_changes=evidence.dependency_changes,
        workflow_changes=evidence.workflow_changes,
        risk_evidence=evidence.risk_evidence,
        validation_profiles=evidence.validation_profiles,
        validation_results=evidence.validation_results,
        exact_tested_sha=evidence.exact_tested_sha,
        failed_finding_ids=tuple(sorted(unresolved)),
        repaired_finding_ids=tuple(sorted(repaired)),
        unresolved_finding_ids=tuple(sorted(unresolved)),
        prior_reviewed_head=evidence.prior_reviewed_head,
        paths_changed_since_review=evidence.paths_changed_since_review,
        activated_references=(
            "scripts/agent_os_pr_remediation/review_evidence.py",
            "scripts/agent_os_pr_remediation/review_findings.py",
            "scripts/agent_os_pr_remediation/review_coverage.py",
            "scripts/agent_os_pr_remediation/merge_evidence_summary.py",
        ),
        review_depth=depth.depth,
    )

    reasons: list[str] = []
    if depth.depth is ReviewDepth.MANUAL:
        disposition = BulkReviewDisposition.MANUAL_BLOCKED
        reasons.append("review-depth-manual")
    elif invalidated_paths or invalidated:
        disposition = BulkReviewDisposition.STALE
        reasons.append("review-evidence-invalidated")
    elif unresolved:
        disposition = BulkReviewDisposition.REPAIR_REQUIRED
        reasons.append("unresolved-blocking-findings")
    elif blocking_coverage:
        disposition = BulkReviewDisposition.REVIEW_REQUIRED
        reasons.append("review-coverage-incomplete-or-blocked")
    elif depth.depth is ReviewDepth.NO_AI:
        disposition = BulkReviewDisposition.CLEARED
        reasons.append("no-ai-review-required")
    elif not evidence.coverage:
        disposition = BulkReviewDisposition.REVIEW_REQUIRED
        reasons.append("required-review-coverage-missing")
    else:
        disposition = BulkReviewDisposition.CLEARED
        reasons.append("current-head-review-cleared")

    return BulkRepairReviewProjection(
        repository=evidence.repository,
        pull_request_number=evidence.pull_request_number,
        reviewed_head_sha=evidence.head_sha,
        review_depth=depth.depth,
        disposition=disposition,
        packet=packet,
        unresolved_finding_ids=tuple(sorted(unresolved)),
        repaired_finding_ids=tuple(sorted(repaired)),
        invalidated_finding_ids=tuple(sorted(invalidated)),
        blocking_coverage_ids=blocking_coverage,
        invalidated_paths=invalidated_paths,
        reason_codes=tuple(reasons),
        handoff_to_br3=disposition is BulkReviewDisposition.CLEARED,
        repair_required=disposition is BulkReviewDisposition.REPAIR_REQUIRED,
        manual_review_required=disposition is BulkReviewDisposition.MANUAL_BLOCKED,
    )
