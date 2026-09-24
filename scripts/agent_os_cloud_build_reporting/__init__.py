"""Cloud Build reporting contracts for #685/#686.

The core remains supplied-evidence-only. #686 adds a pure publication policy
that plans and reconciles canonical GitHub comment operations without owning
transport, credentials, pagination, retries, or external mutation.
"""

from .core import (
    compute_stable_marker,
    evidence_semantic_identity,
    is_same_build,
    normalize_cloud_build_evidence,
    render_comment_projection,
    resolve_pull_request,
    serialize_projection,
)
from .models import (
    CLOUD_BUILD_EVIDENCE_SCHEMA_NAME,
    CLOUD_BUILD_EVIDENCE_SCHEMA_VERSION,
    MAX_PR_CANDIDATES,
    CloudBuildCommentProjection,
    CloudBuildEvidenceError,
    CloudBuildResultEvidence,
    OverallResult,
    PullRequestResolutionCandidate,
    PullRequestResolutionResult,
    PullRequestState,
    ResolutionStatus,
)
from .publication import (
    MAX_COMMENT_SNAPSHOTS,
    ManagedCommentSnapshot,
    PublicationAction,
    PublicationPlan,
    PublicationReconciliation,
    plan_publication,
    reconcile_publication,
)

__all__ = [
    "CLOUD_BUILD_EVIDENCE_SCHEMA_NAME",
    "CLOUD_BUILD_EVIDENCE_SCHEMA_VERSION",
    "MAX_COMMENT_SNAPSHOTS",
    "MAX_PR_CANDIDATES",
    "CloudBuildCommentProjection",
    "CloudBuildEvidenceError",
    "CloudBuildResultEvidence",
    "ManagedCommentSnapshot",
    "OverallResult",
    "PublicationAction",
    "PublicationPlan",
    "PublicationReconciliation",
    "PullRequestResolutionCandidate",
    "PullRequestResolutionResult",
    "PullRequestState",
    "ResolutionStatus",
    "compute_stable_marker",
    "evidence_semantic_identity",
    "is_same_build",
    "normalize_cloud_build_evidence",
    "plan_publication",
    "reconcile_publication",
    "render_comment_projection",
    "resolve_pull_request",
    "serialize_projection",
]
