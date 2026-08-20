"""Pure-local PR review remediation normalization, preflight, planning, and coordination."""

from .ci_evidence_recovery import (
    DEFAULT_DIAGNOSTIC_EXCERPT_LINES,
    DIAGNOSTIC_EXCERPT_EXPANSION_LINES,
    MAX_DIAGNOSTIC_EXCERPT_LINES,
    MIN_DIAGNOSTIC_EXCERPT_LINES,
    RECOVERY_FAILURE_REASONS,
    RECOVERY_PATHS,
    CIEvidenceIdentity,
    CIEvidenceRecoveryPlan,
    RecoveryObservation,
    diagnostic_excerpt_lines,
    expand_diagnostic_excerpt_lines,
    plan_ci_evidence_recovery,
)
from .coordination import (
    SUGGESTED_ACTIONS,
    VALIDATION_STATES,
    FindingFixEvidence,
    ResolutionPlan,
    ThreadResolutionEvidence,
    ValidationCategoryResult,
    ValidationEvidenceBinding,
    coordinate_resolution,
    resolution_plan_id,
    serialize_resolution_plan,
)
from .evidence_assembly import EvidenceAssemblyResult, GitHubEvidenceReader, assemble_prr_evidence
from .high_reasoning_proposal import (
    FrozenProposalPlan,
    ProposalOutcome,
    ProposalProviderUnavailable,
    ProposalRequest,
    ProposalResult,
    ProposalType,
    evaluate_plan_currentness,
    propose_high_reasoning_plan,
    serialize_frozen_proposal,
)
from .models import EvidenceValidationError, NormalizedPRSnapshot, NormalizedReviewThread, canonical_json, deterministic_id
from .normalization import classify_review_thread_payload, normalize_pr_snapshot, normalize_review_thread, normalize_review_threads
from .planning import COMPUTE_ROUTES, FINDING_CLASSIFICATIONS, FindingCandidate, PlannedFinding, RemediationPlan, RemediationTask, plan_remediation
from .preflight import PreflightResult, preflight

__all__ = [
    "CIEvidenceIdentity", "CIEvidenceRecoveryPlan", "COMPUTE_ROUTES",
    "DEFAULT_DIAGNOSTIC_EXCERPT_LINES", "DIAGNOSTIC_EXCERPT_EXPANSION_LINES",
    "EvidenceAssemblyResult", "EvidenceValidationError", "FINDING_CLASSIFICATIONS",
    "FindingCandidate", "FindingFixEvidence", "FrozenProposalPlan", "GitHubEvidenceReader",
    "MAX_DIAGNOSTIC_EXCERPT_LINES", "MIN_DIAGNOSTIC_EXCERPT_LINES",
    "NormalizedPRSnapshot", "NormalizedReviewThread", "PlannedFinding", "PreflightResult",
    "ProposalOutcome", "ProposalProviderUnavailable", "ProposalRequest", "ProposalResult",
    "ProposalType", "RECOVERY_FAILURE_REASONS", "RECOVERY_PATHS", "RecoveryObservation",
    "RemediationPlan", "RemediationTask", "ResolutionPlan", "SUGGESTED_ACTIONS",
    "ThreadResolutionEvidence", "VALIDATION_STATES", "ValidationCategoryResult",
    "ValidationEvidenceBinding", "assemble_prr_evidence", "canonical_json",
    "classify_review_thread_payload", "coordinate_resolution", "deterministic_id",
    "diagnostic_excerpt_lines", "evaluate_plan_currentness", "expand_diagnostic_excerpt_lines",
    "normalize_pr_snapshot", "normalize_review_thread", "normalize_review_threads",
    "plan_ci_evidence_recovery", "plan_remediation", "preflight",
    "propose_high_reasoning_plan", "resolution_plan_id", "serialize_frozen_proposal",
    "serialize_resolution_plan",
]