"""Immutable, read-only Agent OS execution capability evidence."""

from .approved_projection import (
    GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION,
    GovernedProjectionEvidenceResult,
    consume_approved_projection_evidence,
)
from .models import (
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    CapabilityEvidence,
    CapabilityEvidenceEnvelope,
    CapabilityStatus,
    EvidenceStrength,
    ExecutionDecision,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    RepositoryStateValidationResult,
    WorktreeState,
)
from .repository_state import (
    validate_capability_evidence,
    validate_repository_state_evidence,
)
from .serialization import serialize_capability_evidence

__all__ = [
    "CAPABILITY_EVIDENCE_SCHEMA_NAME",
    "CAPABILITY_EVIDENCE_SCHEMA_VERSION",
    "GOVERNED_PROJECTION_EVIDENCE_SCHEMA_VERSION",
    "CapabilityEvidence",
    "CapabilityEvidenceEnvelope",
    "CapabilityStatus",
    "EvidenceStrength",
    "ExecutionDecision",
    "GovernedProjectionEvidenceResult",
    "RepositoryEvidenceType",
    "RepositoryIdentity",
    "RepositoryStateEvidence",
    "RepositoryStateValidationResult",
    "WorktreeState",
    "consume_approved_projection_evidence",
    "serialize_capability_evidence",
    "validate_capability_evidence",
    "validate_repository_state_evidence",
]
