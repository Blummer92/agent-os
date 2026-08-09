"""Pure-local PR review remediation normalization and preflight contract."""

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
from .preflight import PreflightResult, preflight

__all__ = [
    "EvidenceValidationError",
    "NormalizedPRSnapshot",
    "NormalizedReviewThread",
    "PreflightResult",
    "canonical_json",
    "classify_review_thread_payload",
    "deterministic_id",
    "normalize_pr_snapshot",
    "normalize_review_thread",
    "normalize_review_threads",
    "preflight",
]
