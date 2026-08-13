"""Immutable, read-only Agent OS execution-service contracts."""

from .authorization import ExecutionAuthorizationEvidence
from .command_planning import (
    COMMAND_PLAN_SCHEMA_VERSION,
    COMMAND_REGISTRY_VERSION,
    CommandOperation,
    CommandPlanEntry,
    ValidationCommandPlan,
    build_validation_command_plan,
    serialize_validation_command_plan,
    validate_validation_command_plan,
    validation_command_plan_id,
)
from .executor_routing import (
    EXECUTOR_ROUTING_SCHEMA_VERSION,
    ExecutorCapability,
    ExecutorHandoff,
    ExecutorRoute,
    ExecutorRouteDecision,
    ExecutorRouteReason,
    build_executor_handoff,
    executor_handoff_id,
    executor_route_decision_id,
    select_executor_route,
    serialize_executor_route_decision,
)
from .models import (
    EXECUTION_SERVICE_FINGERPRINT_VERSION,
    EXECUTION_SERVICE_REQUEST_SCHEMA_VERSION,
    EXECUTION_SERVICE_RESULT_SCHEMA_VERSION,
    EXECUTION_SERVICE_VERSION,
    EvidenceVisibilityPolicy,
    ExecutionServiceCapability,
    ExecutionServiceInvalidationCondition,
    ExecutionServiceReason,
    ExecutionServiceRequest,
    ExecutionServiceResult,
    ExecutionServiceStatus,
    InspectedFileEvidence,
    PrivateEvidence,
    RepositoryInspectionObservation,
    execution_service_request_fingerprint,
    execution_service_result_fingerprint,
    reconstruct_execution_service_request,
    serialize_execution_service_request,
)
from .read_only_service import RepositoryInspector, evaluate_read_only_request
from .request_validation import (
    contains_secret_marker,
    project_public_result,
    redact_public_text,
    validate_execution_service_request,
)

__all__ = [
    "COMMAND_PLAN_SCHEMA_VERSION",
    "COMMAND_REGISTRY_VERSION",
    "EXECUTION_COMPOSITION_SCHEMA_VERSION",
    "EXECUTION_SERVICE_FINGERPRINT_VERSION",
    "EXECUTION_SERVICE_REQUEST_SCHEMA_VERSION",
    "EXECUTION_SERVICE_RESULT_SCHEMA_VERSION",
    "EXECUTION_SERVICE_VERSION",
    "EXECUTOR_ROUTING_SCHEMA_VERSION",
    "CommandOperation",
    "CommandPlanEntry",
    "EvidenceVisibilityPolicy",
    "ExecutionAuthorizationEvidence",
    "ExecutionCompositionResult",
    "ExecutionCompositionStatus",
    "ExecutionServiceCapability",
    "ExecutionServiceInvalidationCondition",
    "ExecutionServiceReason",
    "ExecutionServiceRequest",
    "ExecutionServiceResult",
    "ExecutionServiceStatus",
    "ExecutorCapability",
    "ExecutorHandoff",
    "ExecutorRoute",
    "ExecutorRouteDecision",
    "ExecutorRouteReason",
    "InspectedFileEvidence",
    "PrivateEvidence",
    "RepositoryInspectionObservation",
    "RepositoryInspector",
    "ValidationCommandPlan",
    "build_executor_handoff",
    "build_validation_command_plan",
    "compose_and_run_validation",
    "contains_secret_marker",
    "evaluate_read_only_request",
    "execution_service_request_fingerprint",
    "execution_service_result_fingerprint",
    "executor_handoff_id",
    "executor_route_decision_id",
    "project_public_result",
    "reconstruct_execution_service_request",
    "redact_public_text",
    "select_executor_route",
    "serialize_execution_service_request",
    "serialize_executor_route_decision",
    "serialize_validation_command_plan",
    "validate_execution_service_request",
    "validate_validation_command_plan",
    "validation_command_plan_id",
]

# Runtime composition still depends on Workflow Scheduler, which is not on
# ``sys.path`` for every consumer. Only the runtime-composition names remain
# lazy. The authorization evidence contract is imported eagerly from the pure
# module above so package-level authorization imports never load Scheduler.
_LAZY_COMPOSITION_EXPORTS = frozenset(
    (
        "EXECUTION_COMPOSITION_SCHEMA_VERSION",
        "ExecutionCompositionResult",
        "ExecutionCompositionStatus",
        "compose_and_run_validation",
    )
)


def __getattr__(name: str) -> object:
    if name in _LAZY_COMPOSITION_EXPORTS:
        from . import execution_composition as _execution_composition

        return getattr(_execution_composition, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
