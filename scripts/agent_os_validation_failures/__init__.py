"""Provider-neutral validation-failure projection."""

from .core import (
    VALIDATION_FAILURE_SCHEMA_VERSION,
    EvidenceValueState,
    ObservedFailureFact,
    ValidationFailureError,
    ValidationFailureRecord,
    ValidationFailureSource,
    ValidationFailureStatus,
    ValidationMode,
    build_validation_failure_record,
    serialize_validation_failure_record,
    validation_failure_record_id,
)

__all__ = [
    "VALIDATION_FAILURE_SCHEMA_VERSION",
    "EvidenceValueState",
    "ObservedFailureFact",
    "ValidationFailureError",
    "ValidationFailureRecord",
    "ValidationFailureSource",
    "ValidationFailureStatus",
    "ValidationMode",
    "build_validation_failure_record",
    "serialize_validation_failure_record",
    "validation_failure_record_id",
]
