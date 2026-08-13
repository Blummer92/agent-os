"""Read-only Agent OS candidate-packet pipeline.

The package composes canonical issue, planning, repository, proposal, approval,
validation, and packet-preparation contracts. Packet preparation remains
separate from runtime execution: importing this package does not import the
Workflow Scheduler executable adapter layer, and no exported result grants
execution, merge, publication, or external-write authority.
"""

from scripts.agent_os_issue_acceptance.acceptance_report_transport import (
    acceptance_report_from_payload,
    acceptance_report_to_payload,
)

from .approval_stage import (
    ApprovalCandidateContext,
    ApprovalDecision,
    ApprovalProjectionStageResult,
    ApprovalProjectionStageStatus,
    approval_projection_stage_result_from_dict,
    approval_projection_stage_result_to_dict,
    prepare_approval_projection,
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
from .post_pr_lane_plan import (
    POST_PR_LANE_PLAN_SCHEMA_NAME,
    POST_PR_LANE_PLAN_SCHEMA_VERSION,
    ConflictFinding,
    LanePlanOutcome,
    PostPrLanePlan,
    deserialize_post_pr_lane_plan,
    plan_post_pr_lane,
    serialize_post_pr_lane_plan,
)
from .implementation_packet_projection import (
    ImplementationPacketProjection,
    ImplementationPacketSourceIdentities,
    project_implementation_packet,
)
from .readiness_stage import prepare_issue_readiness
from .planning_stage import (
    PlanningHandoffStageResult,
    PlanningHandoffStageStatus,
    planning_handoff_stage_result_from_dict,
    planning_handoff_stage_result_to_dict,
    prepare_planning_handoff,
    reconstruct_scheduler_planning_handoff,
)
from .proposal_stage import (
    RepositoryProposalStageResult,
    RepositoryProposalStageStatus,
    draft_task_proposal_from_dict,
    draft_task_proposal_to_dict,
    prepare_repository_and_proposal,
    repository_proposal_stage_result_from_dict,
    repository_proposal_stage_result_to_dict,
)
from .repository_stage import (
    REPOSITORY_OBSERVATION_REJECTED,
    RepositoryObservation,
    RepositoryStageResult,
    RepositoryStageStatus,
    prepare_repository_state_evidence,
    repository_stage_result_from_dict,
    repository_stage_result_to_dict,
    repository_state_evidence_from_dict,
    repository_state_evidence_to_dict,
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
    IssuePlanningContext,
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
from .validation_stage import (
    CandidateRuntimeInputs,
    ValidationStageDisposition,
    ValidationStageResult,
    prepare_validation_stage,
    validation_stage_result_from_dict,
    validation_stage_result_to_dict,
)

__all__ = [
    "ApprovalCandidateContext",
    "ApprovalDecision",
    "ApprovalProjectionStageResult",
    "ApprovalProjectionStageStatus",
    "CandidateRuntimeInputs",
    "DEPENDENCY_IDENTITY_DUPLICATE_COLLAPSED_REASON",
    "DEPENDENCY_IDENTITY_NOT_SUPPLIED",
    "DEPENDENCY_IDENTITY_NOT_SUPPLIED_REASON",
    "EXECUTABLE_LANE_SELECTION_SCHEMA_NAME",
    "EXECUTABLE_LANE_SELECTION_SCHEMA_VERSION",
    "POST_PR_LANE_PLAN_SCHEMA_NAME",
    "POST_PR_LANE_PLAN_SCHEMA_VERSION",
    "ExecutionPacketDisposition",
    "ExecutionPacketStageResult",
    "REPOSITORY_OBSERVATION_REJECTED",
    "STAGE_SCHEMA_VERSION",
    "CandidateIssueEvidence",
    "ConflictFinding",
    "DuplicateClaimFinding",
    "ExecutableLaneSelection",
    "LanePlanOutcome",
    "PostPrLanePlan",
    "ImplementationPacketProjection",
    "ImplementationPacketSourceIdentities",
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
    "IssuePlanningContext",
    "IssueReadinessStageRequest",
    "IssueReadinessStageResult",
    "IssueReadinessStageStatus",
    "IssueSnapshot",
    "IssueSourceReader",
    "IssueSourceStageResult",
    "IssueSourceStageStatus",
    "RepositoryEvidenceReader",
    "RepositoryObservation",
    "RepositoryProposalStageResult",
    "RepositoryProposalStageStatus",
    "RepositoryStageResult",
    "RepositoryStageStatus",
    "ValidationEvidence",
    "ValidationStageDisposition",
    "ValidationStageResult",
    "acceptance_report_from_payload",
    "acceptance_report_to_payload",
    "approval_projection_stage_result_from_dict",
    "approval_projection_stage_result_to_dict",
    "dependency_identity_evidence_from_dict",
    "dependency_identity_evidence_to_dict",
    "deserialize_executable_lane_selection",
    "deserialize_post_pr_lane_plan",
    "draft_task_proposal_from_dict",
    "draft_task_proposal_to_dict",
    "execution_packet_stage_result_from_dict",
    "execution_packet_stage_result_to_dict",
    "issue_readiness_stage_result_from_dict",
    "issue_readiness_stage_result_to_dict",
    "issue_snapshot_from_dict",
    "issue_snapshot_to_dict",
    "issueplan_current_state_evidence_from_dict",
    "issueplan_current_state_evidence_to_dict",
    "plan_post_pr_lane",
    "planning_handoff_stage_result_from_dict",
    "planning_handoff_stage_result_to_dict",
    "prepare_approval_projection",
    "prepare_execution_packet",
    "prepare_issue_readiness",
    "prepare_planning_handoff",
    "prepare_repository_and_proposal",
    "prepare_repository_state_evidence",
    "prepare_validation_stage",
    "project_implementation_packet",
    "reconstruct_scheduler_planning_handoff",
    "readiness_result_from_dict",
    "readiness_result_to_dict",
    "repository_proposal_stage_result_from_dict",
    "repository_proposal_stage_result_to_dict",
    "repository_stage_result_from_dict",
    "repository_stage_result_to_dict",
    "repository_state_evidence_from_dict",
    "repository_state_evidence_to_dict",
    "resolve_issue_snapshot",
    "select_executable_lanes",
    "serialize_executable_lane_selection",
    "serialize_post_pr_lane_plan",
    "validation_stage_result_from_dict",
    "validation_stage_result_to_dict",
]

# Execution-packet construction depends on the execution-service and Workflow
# Scheduler source packages, which are not on every read-only consumer's import
# path. Keep those names lazy so ordinary candidate-packet imports remain pure
# and backward compatible.
_LAZY_EXECUTION_PACKET_EXPORTS = frozenset(
    {
        "ExecutionPacketDisposition",
        "ExecutionPacketStageResult",
        "execution_packet_stage_result_from_dict",
        "execution_packet_stage_result_to_dict",
        "prepare_execution_packet",
    }
)


def __getattr__(name: str) -> object:
    if name in _LAZY_EXECUTION_PACKET_EXPORTS:
        from . import execution_packet_stage as _execution_packet_stage

        value = getattr(_execution_packet_stage, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")