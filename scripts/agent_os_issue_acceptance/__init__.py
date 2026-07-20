"""Reusable Agent OS issue acceptance and readiness checks."""

from .approved_execution_projection import (
    APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
    ApprovedExecutionProjection,
    ApprovedExecutionProjectionResult,
    build_approved_execution_projection,
    serialize_approved_execution_projection,
)
from .approval_records import (
    APPROVAL_INVALIDATION_REASON_CODES,
    APPROVAL_RECORD_SCHEMA_VERSION,
    ApprovalApplicabilityResult,
    ApprovalBinding,
    ApprovalKind,
    ApprovalRecord,
    ApprovalState,
    build_approval_candidate,
    evaluate_approval_applicability,
    record_approval_decision,
)
from .batch_checks import (
    BatchConflictRun,
    ForbiddenPathCrossing,
    evaluate_base_batch_conflict_run,
    evaluate_base_batch_conflicts,
)
from .batch_extensions import (
    GraphCheck,
    GraphCheckResult,
    GraphCheckRun,
    run_graph_checks,
)
from .batch_graph import (
    IssueBatchGraph,
    IssueBatchNode,
    build_issue_batch_graph,
    load_issue_batch_fixture,
)
from .batch_identity_checks import entity_id_collision_check
from .batch_planning import (
    BatchPlanningResult,
    PlanningClassification,
    PlanningCohort,
    evaluate_batch_plan,
)
from .batch_scope_checks import (
    evaluate_input_scope_coverage,
    unresolved_dependency_check,
)
from .issueplan_current_state import (
    ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION,
    IssuePlanCurrentStateComparison,
    IssuePlanCurrentStateEvidence,
    IssuePlanCurrentStateOutcome,
    IssuePlanSourceSnapshot,
    build_issueplan_current_state_evidence,
    compare_issueplan_current_state,
    compute_issueplan_current_state_fingerprint,
)
from .parse_issue import (
    parse_issue_metadata,
    project_issue_metadata,
    scan_issue_metadata,
    scanner_manual_review_items,
)
from .policy import evaluate_acceptance
from .readiness import (
    ReadinessOutcome,
    ReadinessResult,
    evaluate_issue_readiness,
    evaluate_issue_readiness_with_labels,
)
from .report import render_report
from .scheduler_handoff import (
    HandoffCohort,
    HandoffValidationOutcome,
    HandoffValidationResult,
    SUPPORTED_CONTRACT_VERSIONS,
    SUPPORTED_PLANNING_RESULT_VERSIONS,
    SchedulerPlanningHandoff,
    compute_graph_digest,
    compute_handoff_digest,
    compute_planning_result_digest,
    serialize_scheduler_planning_handoff,
    validate_scheduler_planning_handoff,
)

__all__ = [
    "APPROVAL_INVALIDATION_REASON_CODES",
    "APPROVAL_RECORD_SCHEMA_VERSION",
    "APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION",
    "ApprovalApplicabilityResult",
    "ApprovalBinding",
    "ApprovalKind",
    "ApprovalRecord",
    "ApprovalState",
    "ApprovedExecutionProjection",
    "ApprovedExecutionProjectionResult",
    "BatchConflictRun",
    "BatchPlanningResult",
    "ForbiddenPathCrossing",
    "GraphCheck",
    "GraphCheckResult",
    "GraphCheckRun",
    "HandoffCohort",
    "HandoffValidationOutcome",
    "HandoffValidationResult",
    "ISSUEPLAN_CURRENT_STATE_SCHEMA_VERSION",
    "IssueBatchGraph",
    "IssueBatchNode",
    "IssuePlanCurrentStateComparison",
    "IssuePlanCurrentStateEvidence",
    "IssuePlanCurrentStateOutcome",
    "IssuePlanSourceSnapshot",
    "PlanningClassification",
    "PlanningCohort",
    "ReadinessOutcome",
    "ReadinessResult",
    "SUPPORTED_CONTRACT_VERSIONS",
    "SUPPORTED_PLANNING_RESULT_VERSIONS",
    "SchedulerPlanningHandoff",
    "build_approval_candidate",
    "build_approved_execution_projection",
    "build_issue_batch_graph",
    "build_issueplan_current_state_evidence",
    "compare_issueplan_current_state",
    "compute_graph_digest",
    "compute_handoff_digest",
    "compute_issueplan_current_state_fingerprint",
    "compute_planning_result_digest",
    "entity_id_collision_check",
    "evaluate_acceptance",
    "evaluate_approval_applicability",
    "evaluate_base_batch_conflict_run",
    "evaluate_base_batch_conflicts",
    "evaluate_batch_plan",
    "evaluate_input_scope_coverage",
    "evaluate_issue_readiness",
    "evaluate_issue_readiness_with_labels",
    "load_issue_batch_fixture",
    "parse_issue_metadata",
    "project_issue_metadata",
    "record_approval_decision",
    "render_report",
    "run_graph_checks",
    "scan_issue_metadata",
    "scanner_manual_review_items",
    "serialize_approved_execution_projection",
    "serialize_scheduler_planning_handoff",
    "unresolved_dependency_check",
    "validate_scheduler_planning_handoff",
]
