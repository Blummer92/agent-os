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
    "AUTHORIZED_VALIDATION_PERMITTED_OPERATION",
    "AUTHORIZED_VALIDATION_POLICY_SCHEMA_VERSION",
    "AUTHORIZED_VALIDATION_SCHEMA_VERSION",
    "COMMAND_PLAN_SCHEMA_VERSION",
    "COMMAND_REGISTRY_VERSION",
    "EXECUTION_COMPOSITION_SCHEMA_VERSION",
    "EXECUTION_SERVICE_FINGERPRINT_VERSION",
    "EXECUTION_SERVICE_REQUEST_SCHEMA_VERSION",
    "EXECUTION_SERVICE_RESULT_SCHEMA_VERSION",
    "EXECUTION_SERVICE_VERSION",
    "EXECUTOR_ROUTING_SCHEMA_VERSION",
    "AuthorizedValidationAdmissionResult",
    "AuthorizedValidationAdmissionStatus",
    "AuthorizedValidationLifecyclePolicy",
    "AuthorizedValidationLifecycleRequest",
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
    "POST_ADMISSION_TERMINAL_STATUS_PRECEDENCE",
    "VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION",
    "EvidenceAvailability",
    "EvidenceAvailabilityRecord",
    "ValidationCommandPlan",
    "ValidationLifecycleEvidenceBundle",
    "ValidationLifecycleEvidenceError",
    "ValidationLifecycleResult",
    "ValidationLifecycleTerminalStatus",
    "build_authorized_validation_lifecycle_request",
    "build_executor_handoff",
    "build_validation_command_plan",
    "build_validation_lifecycle_evidence_bundle",
    "compose_and_run_validation",
    "contains_secret_marker",
    "evaluate_read_only_request",
    "execution_service_request_fingerprint",
    "execution_service_result_fingerprint",
    "executor_handoff_id",
    "executor_route_decision_id",
    "project_public_result",
    "project_validation_lifecycle_result",
    "reconstruct_authorized_validation_lifecycle_request",
    "reconstruct_execution_service_request",
    "reconstruct_validation_lifecycle_evidence_bundle",
    "reconstruct_validation_lifecycle_result",
    "redact_public_text",
    "select_executor_route",
    "serialize_authorized_validation_lifecycle_request",
    "serialize_execution_service_request",
    "serialize_executor_route_decision",
    "serialize_validation_command_plan",
    "serialize_validation_lifecycle_evidence_bundle",
    "serialize_validation_lifecycle_result",
    "validate_execution_service_request",
    "validate_validation_command_plan",
    "validation_command_plan_id",
    "verify_authorized_validation_admission",
]

# Runtime composition and #757 admission depend on Workflow Scheduler or the
# candidate-packet package, which are not on ``sys.path`` for every consumer.
# Keep those exports lazy so importing the pure Execution Service core does not
# make runtime-capable modules reachable or create a packaging dependency.
_LAZY_COMPOSITION_EXPORTS = frozenset(
    (
        "EXECUTION_COMPOSITION_SCHEMA_VERSION",
        "ExecutionCompositionResult",
        "ExecutionCompositionStatus",
        "compose_and_run_validation",
    )
)
_LAZY_AUTHORIZED_VALIDATION_EXPORTS = frozenset(
    (
        "AUTHORIZED_VALIDATION_PERMITTED_OPERATION",
        "AUTHORIZED_VALIDATION_POLICY_SCHEMA_VERSION",
        "AUTHORIZED_VALIDATION_SCHEMA_VERSION",
        "AuthorizedValidationAdmissionResult",
        "AuthorizedValidationAdmissionStatus",
        "AuthorizedValidationLifecyclePolicy",
        "AuthorizedValidationLifecycleRequest",
        "build_authorized_validation_lifecycle_request",
        "reconstruct_authorized_validation_lifecycle_request",
        "serialize_authorized_validation_lifecycle_request",
        "verify_authorized_validation_admission",
    )
)
# The unified validation-lifecycle evidence bundle (#761) composes #757
# admission evidence with #758/#759/#760 lower-level Workflow Scheduler
# evidence, so it carries the same Workflow Scheduler packaging dependency as
# the composition and authorized-validation exports above and stays lazy for
# the identical reason: importing the pure Execution Service core must not by
# itself make runtime-capable modules reachable.
_LAZY_VALIDATION_LIFECYCLE_EVIDENCE_EXPORTS = frozenset(
    (
        "POST_ADMISSION_TERMINAL_STATUS_PRECEDENCE",
        "VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION",
        "EvidenceAvailability",
        "EvidenceAvailabilityRecord",
        "ValidationLifecycleEvidenceBundle",
        "ValidationLifecycleEvidenceError",
        "ValidationLifecycleResult",
        "ValidationLifecycleTerminalStatus",
        "build_validation_lifecycle_evidence_bundle",
        "project_validation_lifecycle_result",
        "reconstruct_validation_lifecycle_evidence_bundle",
        "reconstruct_validation_lifecycle_result",
        "serialize_validation_lifecycle_evidence_bundle",
        "serialize_validation_lifecycle_result",
    )
)


def __getattr__(name: str) -> object:
    if name in _LAZY_COMPOSITION_EXPORTS:
        from . import execution_composition as _execution_composition

        return getattr(_execution_composition, name)
    if name in _LAZY_AUTHORIZED_VALIDATION_EXPORTS:
        from . import authorized_validation as _authorized_validation

        return getattr(_authorized_validation, name)
    if name in _LAZY_VALIDATION_LIFECYCLE_EVIDENCE_EXPORTS:
        from . import validation_lifecycle_evidence as _validation_lifecycle_evidence

        return getattr(_validation_lifecycle_evidence, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
