"""Pure-local PR review remediation normalization, preflight, planning, and coordination."""

from .ci_evidence_recovery import (
    RECOVERY_FAILURE_REASONS,
    RECOVERY_PATHS,
    CIEvidenceIdentity,
    CIEvidenceRecoveryPlan,
    RecoveryObservation,
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
from .models import EvidenceValidationError, NormalizedPRSnapshot, NormalizedReviewThread, canonical_json, deterministic_id
from .normalization import classify_review_thread_payload, normalize_pr_snapshot, normalize_review_thread, normalize_review_threads
from .planning import COMPUTE_ROUTES, FINDING_CLASSIFICATIONS, FindingCandidate, PlannedFinding, RemediationPlan, RemediationTask, plan_remediation
from .preflight import PreflightResult, preflight

__all__ = [
    "CIEvidenceIdentity", "CIEvidenceRecoveryPlan", "COMPUTE_ROUTES",
    "EvidenceAssemblyResult", "EvidenceValidationError", "FINDING_CLASSIFICATIONS",
    "FindingCandidate", "FindingFixEvidence", "GitHubEvidenceReader",
    "NormalizedPRSnapshot", "NormalizedReviewThread", "PlannedFinding", "PreflightResult",
    "RECOVERY_FAILURE_REASONS", "RECOVERY_PATHS", "RecoveryObservation", "RemediationPlan",
    "RemediationTask", "ResolutionPlan", "SUGGESTED_ACTIONS", "ThreadResolutionEvidence",
    "VALIDATION_STATES", "ValidationCategoryResult", "ValidationEvidenceBinding",
    "assemble_prr_evidence", "canonical_json", "classify_review_thread_payload",
    "coordinate_resolution", "deterministic_id", "normalize_pr_snapshot",
    "normalize_review_thread", "normalize_review_threads", "plan_ci_evidence_recovery",
    "plan_remediation", "preflight", "resolution_plan_id", "serialize_resolution_plan",
]
