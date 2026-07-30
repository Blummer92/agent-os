"""AOS-AUTO1A: exact issue snapshot and readiness evidence adapter (#750).

Read-only first stage of the candidate-packet pipeline. Composes the
existing GitHub issue provider, IssuePlan scanner, IssuePlan current-state
evidence, and readiness evaluator into one bounded stage result. Performs no
writes and no network calls itself; ``issue_reader`` and ``repository_reader``
are injected read-only dependencies supplied by the caller.
"""

from .readiness_stage import prepare_issue_readiness
from .source_stage import resolve_issue_snapshot
from .stage_models import (
    STAGE_SCHEMA_VERSION,
    DependencyEvidence,
    EvidenceStatus,
    IssueReadinessStageRequest,
    IssueReadinessStageResult,
    IssueReadinessStageStatus,
    IssueReadResult,
    IssueReadStatus,
    IssueSnapshot,
    IssueSourceReader,
    IssueSourceStageResult,
    IssueSourceStageStatus,
    RepositoryEvidenceReader,
    ValidationEvidence,
    acceptance_report_from_dict,
    acceptance_report_to_dict,
    issue_readiness_stage_result_from_dict,
    issue_readiness_stage_result_to_dict,
    issue_snapshot_from_dict,
    issue_snapshot_to_dict,
    issueplan_current_state_evidence_from_dict,
    issueplan_current_state_evidence_to_dict,
    readiness_result_from_dict,
    readiness_result_to_dict,
)

__all__ = [
    "STAGE_SCHEMA_VERSION",
    "DependencyEvidence",
    "EvidenceStatus",
    "IssueReadResult",
    "IssueReadStatus",
    "IssueReadinessStageRequest",
    "IssueReadinessStageResult",
    "IssueReadinessStageStatus",
    "IssueSnapshot",
    "IssueSourceReader",
    "IssueSourceStageResult",
    "IssueSourceStageStatus",
    "RepositoryEvidenceReader",
    "ValidationEvidence",
    "acceptance_report_from_dict",
    "acceptance_report_to_dict",
    "issue_readiness_stage_result_from_dict",
    "issue_readiness_stage_result_to_dict",
    "issue_snapshot_from_dict",
    "issue_snapshot_to_dict",
    "issueplan_current_state_evidence_from_dict",
    "issueplan_current_state_evidence_to_dict",
    "prepare_issue_readiness",
    "readiness_result_from_dict",
    "readiness_result_to_dict",
    "resolve_issue_snapshot",
]
