"""Pure-local PR review remediation normalization, preflight, planning, and coordination."""

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
from .models import (
    EvidenceValidationError,
    NormalizedPRSnapshot,
    NormalizedReviewThread,
    canonical_json,
    deterministic_id,
)
from .normalization import (
    classify_review_thread_payload,
    normalize_pr_snapshot,
    normalize_review_thread,
    normalize_review_threads,
)
from .planning import (
    COMPUTE_ROUTES,
    FINDING_CLASSIFICATIONS,
    FindingCandidate,
    PlannedFinding,
    RemediationPlan,
    RemediationTask,
    plan_remediation,
)
from .preflight import PreflightResult, preflight

__all__ = [
    "COMPUTE_ROUTES",
    "EvidenceValidationError",
    "FINDING_CLASSIFICATIONS",
    "FindingCandidate",
    "FindingFixEvidence",
    "NormalizedPRSnapshot",
    "NormalizedReviewThread",
    "PlannedFinding",
    "PreflightResult",
    "RemediationPlan",
    "RemediationTask",
    "ResolutionPlan",
    "SUGGESTED_ACTIONS",
    "ThreadResolutionEvidence",
    "VALIDATION_STATES",
    "ValidationCategoryResult",
    "ValidationEvidenceBinding",
    "canonical_json",
    "classify_review_thread_payload",
    "coordinate_resolution",
    "deterministic_id",
    "normalize_pr_snapshot",
    "normalize_review_thread",
    "normalize_review_threads",
    "plan_remediation",
    "preflight",
    "resolution_plan_id",
    "serialize_resolution_plan",
]
