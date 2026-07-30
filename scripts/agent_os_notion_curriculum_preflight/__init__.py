"""Public surface for the pure-local Notion curriculum preflight."""

from .core import (
    evaluate_notion_curriculum_preflight,
    parse_preflight_evidence,
    serialize_preflight_report,
)
from .models import (
    CONTRACT_VERSION,
    EVIDENCE_TTL_HOURS,
    FINDING_CODES,
    PROPOSED_IMPLEMENTATION_SCOPE,
    SUPPORTED_NOTION_API_VERSION,
    ContractMappingCandidate,
    NotionAuthorizationEvidence,
    NotionCurriculumPreflightError,
    NotionCurriculumPreflightEvidence,
    NotionCurriculumPreflightReport,
    NotionLimitEvidence,
    NotionPropertyEvidence,
    NotionRelationEvidence,
    NotionViewEvidence,
    PreflightStatus,
)

__all__ = [
    "CONTRACT_VERSION",
    "EVIDENCE_TTL_HOURS",
    "FINDING_CODES",
    "PROPOSED_IMPLEMENTATION_SCOPE",
    "SUPPORTED_NOTION_API_VERSION",
    "ContractMappingCandidate",
    "NotionAuthorizationEvidence",
    "NotionCurriculumPreflightError",
    "NotionCurriculumPreflightEvidence",
    "NotionCurriculumPreflightReport",
    "NotionLimitEvidence",
    "NotionPropertyEvidence",
    "NotionRelationEvidence",
    "NotionViewEvidence",
    "PreflightStatus",
    "evaluate_notion_curriculum_preflight",
    "parse_preflight_evidence",
    "serialize_preflight_report",
]
