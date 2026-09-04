"""Pure-local PR review remediation normalization, preflight, planning, and coordination."""

from .ci_evidence_recovery import (
    DEFAULT_DIAGNOSTIC_EXCERPT_LINES, DIAGNOSTIC_EXCERPT_EXPANSION_LINES,
    MAX_DIAGNOSTIC_EXCERPT_LINES, MIN_DIAGNOSTIC_EXCERPT_LINES,
    RECOVERY_FAILURE_REASONS, RECOVERY_PATHS, CIEvidenceIdentity,
    CIEvidenceRecoveryPlan, RecoveryObservation, diagnostic_excerpt_lines,
    expand_diagnostic_excerpt_lines, plan_ci_evidence_recovery,
)
from .coordination import (
    SUGGESTED_ACTIONS, VALIDATION_STATES, FindingFixEvidence, ResolutionPlan,
    ThreadResolutionEvidence, ValidationCategoryResult, ValidationEvidenceBinding,
    coordinate_resolution, resolution_plan_id, serialize_resolution_plan,
)
from .evidence_assembly import EvidenceAssemblyResult, GitHubEvidenceReader, assemble_prr_evidence
from .models import EvidenceValidationError, NormalizedPRSnapshot, NormalizedReviewThread, canonical_json, deterministic_id
from .normalization import classify_review_thread_payload, normalize_pr_snapshot, normalize_review_thread, normalize_review_threads
from .planning import COMPUTE_ROUTES, FINDING_CLASSIFICATIONS, FindingCandidate, PlannedFinding, RemediationPlan, RemediationTask, plan_remediation
from .preflight import PreflightResult, preflight
from .review_attack_plan import RequiredAttack, ReviewAttackPlan, build_review_attack_plan
from .review_coverage import (
    ALLOWED_ADEQUACY_RECOMMENDATIONS, AdequacyStatus, CoverageStatus,
    ReviewCoverageObservation, ReviewCoverageRecord, TestAdequacyRecord, TestEvidence,
    assess_test_adequacy, normalize_review_coverage,
)
from .review_evidence import (
    ADVERSARIAL_RISKS, FULL_REVIEW_INVALIDATORS, NO_AI_CHANGE_KINDS, ReviewDepth,
    ReviewDepthDecision, ReviewEvidencePacket, ReviewRiskEvidence,
    build_review_evidence_packet, review_invalidation_scope, select_review_depth,
)

__all__ = [
    "ADVERSARIAL_RISKS", "ALLOWED_ADEQUACY_RECOMMENDATIONS", "AdequacyStatus",
    "CIEvidenceIdentity", "CIEvidenceRecoveryPlan", "COMPUTE_ROUTES", "CoverageStatus",
    "DEFAULT_DIAGNOSTIC_EXCERPT_LINES", "DIAGNOSTIC_EXCERPT_EXPANSION_LINES",
    "EvidenceAssemblyResult", "EvidenceValidationError", "FINDING_CLASSIFICATIONS",
    "FULL_REVIEW_INVALIDATORS", "FindingCandidate", "FindingFixEvidence", "GitHubEvidenceReader",
    "MAX_DIAGNOSTIC_EXCERPT_LINES", "MIN_DIAGNOSTIC_EXCERPT_LINES", "NO_AI_CHANGE_KINDS",
    "NormalizedPRSnapshot", "NormalizedReviewThread", "PlannedFinding", "PreflightResult",
    "RECOVERY_FAILURE_REASONS", "RECOVERY_PATHS", "RecoveryObservation", "RemediationPlan",
    "RemediationTask", "RequiredAttack", "ResolutionPlan", "ReviewAttackPlan",
    "ReviewCoverageObservation", "ReviewCoverageRecord", "ReviewDepth", "ReviewDepthDecision",
    "ReviewEvidencePacket", "ReviewRiskEvidence", "SUGGESTED_ACTIONS", "TestAdequacyRecord",
    "TestEvidence", "ThreadResolutionEvidence", "VALIDATION_STATES", "ValidationCategoryResult",
    "ValidationEvidenceBinding", "assemble_prr_evidence", "assess_test_adequacy",
    "build_review_attack_plan", "build_review_evidence_packet", "canonical_json",
    "classify_review_thread_payload", "coordinate_resolution", "deterministic_id",
    "diagnostic_excerpt_lines", "expand_diagnostic_excerpt_lines", "normalize_pr_snapshot",
    "normalize_review_coverage", "normalize_review_thread", "normalize_review_threads",
    "plan_ci_evidence_recovery", "plan_remediation", "preflight", "resolution_plan_id",
    "review_invalidation_scope", "select_review_depth", "serialize_resolution_plan",
]
