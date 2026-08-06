"""AOS-AUTO1A: exact issue snapshot and readiness evidence adapter (#750).

Read-only first stage of the candidate-packet pipeline. Composes the
existing GitHub issue provider, IssuePlan scanner, IssuePlan current-state
evidence, and readiness evaluator into one bounded stage result. Performs no
writes and no network calls itself; ``issue_reader`` and ``repository_reader``
are injected read-only dependencies supplied by the caller.
"""

from scripts.agent_os_issue_acceptance.acceptance_report_transport import (
    acceptance_report_from_payload,
    acceptance_report_to_payload,
)

from .executable_lane_selection import (
    EXECUTABLE_LANE_SELECTION_SCHEMA_NAME,
    EXECUTABLE_LANE_SELECTION_SCHEMA_VERSION,
    CandidateIssueEvidence,
    DuplicateClaimFinding,
    ExecutableLaneSelection,
    Queue,
    QueueClassification,
    RankEvidence,
    ReplacementRecord,
    deserialize_executable_lane_selection,
    select_executable_lanes,
    serialize_executable_lane_selection,
)
from .readiness_stage import prepare_issue_readiness
from .planning_stage import (
    PlanningHandoffStageResult,
    PlanningHandoffStageStatus,
    prepare_planning_handoff,
    reconstruct_scheduler_planning_handoff,
)
from .source_stage import resolve_issue_snapshot
from .stage_models import (
    DEPENDENCY_IDENTITY_DUPLICATE_COLLAPSED_REASON,
    DEPENDENCY_IDENTITY_NOT_SUPPLIED,
    DEPENDENCY_IDENTITY_NOT_SUPPLIED_REASON,
    STAGE_SCHEMA_VERSION,
    DependencyEvidence,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
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
    dependency_identity_evidence_from_dict,
    dependency_identity_evidence_to_dict,
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
    "DEPENDENCY_IDENTITY_DUPLICATE_COLLAPSED_REASON",
    "DEPENDENCY_IDENTITY_NOT_SUPPLIED",
    "DEPENDENCY_IDENTITY_NOT_SUPPLIED_REASON",
    "EXECUTABLE_LANE_SELECTION_SCHEMA_NAME",
    "EXECUTABLE_LANE_SELECTION_SCHEMA_VERSION",
    "STAGE_SCHEMA_VERSION",
    "CandidateIssueEvidence",
    "DuplicateClaimFinding",
    "ExecutableLaneSelection",
    "PlanningHandoffStageResult",
    "PlanningHandoffStageStatus",
    "Queue",
    "QueueClassification",
    "RankEvidence",
    "ReplacementRecord",
    "DependencyEvidence",
    "DependencyIdentityEvidence",
    "DependencyIdentityStatus",
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
    "acceptance_report_from_payload",
    "acceptance_report_to_payload",
    "dependency_identity_evidence_from_dict",
    "dependency_identity_evidence_to_dict",
    "deserialize_executable_lane_selection",
    "issue_readiness_stage_result_from_dict",
    "issue_readiness_stage_result_to_dict",
    "issue_snapshot_from_dict",
    "issue_snapshot_to_dict",
    "issueplan_current_state_evidence_from_dict",
    "issueplan_current_state_evidence_to_dict",
    "prepare_issue_readiness",
    "prepare_planning_handoff",
    "reconstruct_scheduler_planning_handoff",
    "readiness_result_from_dict",
    "readiness_result_to_dict",
    "resolve_issue_snapshot",
    "select_executable_lanes",
    "serialize_executable_lane_selection",
]
