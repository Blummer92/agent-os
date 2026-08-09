"""Pure-local PR review remediation normalization, preflight, and planning contracts."""

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
    "NormalizedPRSnapshot",
    "NormalizedReviewThread",
    "PlannedFinding",
    "PreflightResult",
    "RemediationPlan",
    "RemediationTask",
    "canonical_json",
    "classify_review_thread_payload",
    "deterministic_id",
    "normalize_pr_snapshot",
    "normalize_review_thread",
    "normalize_review_threads",
    "plan_remediation",
    "preflight",
]
