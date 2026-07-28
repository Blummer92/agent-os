"""Pure-local, deterministic Cloud Build reporting core.

Supplied-evidence-only: no network, GitHub, Cloud Build, credential,
filesystem, subprocess, environment, or clock access. See README.md for
scope and the owning issue for authorization boundaries.
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

__all__ = [
    "CLOUD_BUILD_EVIDENCE_SCHEMA_NAME",
    "CLOUD_BUILD_EVIDENCE_SCHEMA_VERSION",
    "MAX_PR_CANDIDATES",
    "CloudBuildCommentProjection",
    "CloudBuildEvidenceError",
    "CloudBuildResultEvidence",
    "OverallResult",
    "PullRequestResolutionCandidate",
    "PullRequestResolutionResult",
    "PullRequestState",
    "ResolutionStatus",
    "compute_stable_marker",
    "evidence_semantic_identity",
    "is_same_build",
    "normalize_cloud_build_evidence",
    "render_comment_projection",
    "resolve_pull_request",
    "serialize_projection",
]
