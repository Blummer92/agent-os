"""Thin Assessment portability-evidence adapter for EXH4 (#1506).

The adapter projects supplied #846 synthetic/noncanonical regression evidence into
the shared experiment-evidence contract. Assessment semantics remain owned by
#846; this module adds no fields or reason codes to the shared EXH core.
"""

from __future__ import annotations

from typing import Any

from .common import (
    ContractValidationError,
    ValidationResult,
    ValidationStatus,
    validate_stable_id,
    validate_text,
)
from .experiment_evidence import CONTRACT_VERSION, validate_experiment_evidence

ADAPTER_ID = "assessment-cross-unit-portability"
ADAPTER_VERSION = "1.0.0"
EXPERIMENT_ID = "assessment-cross-unit-validation"
METRIC_ID = "assessment-portability-observation"


def _fixture_identity(record: object) -> tuple[str, str]:
    if type(record) is not dict:
        raise ContractValidationError(
            "handoff-wrong-type", "assessment fixture must be a built-in mapping"
        )
    if record.get("synthetic_noncanonical") is not True:
        raise ContractValidationError(
            "source-invalid", "assessment evidence must be explicitly synthetic/noncanonical"
        )
    case = validate_stable_id(record.get("case"), "assessment fixture case")
    target = validate_stable_id(
        record.get("synthetic_target_id"), "assessment synthetic target id"
    )
    return case, target


def adapt_assessment_experiment_evidence(
    record: object,
    *,
    fixture_path: str,
    availability: str,
    value: Any,
    record_revision: int = 1,
) -> ValidationResult:
    """Project one supplied #846 fixture observation into EXH2 without reinterpreting it."""
    try:
        case, target = _fixture_identity(record)
        source_path = validate_text(fixture_path, "assessment fixture path")
        payload = {
            "contract_version": CONTRACT_VERSION,
            "record_revision": record_revision,
            "experiment_id": EXPERIMENT_ID,
            "run_id": f"assessment-fixture-{target}",
            "observation_id": case,
            "adapter_id": ADAPTER_ID,
            "adapter_version": ADAPTER_VERSION,
            "metric_id": METRIC_ID,
            "availability": availability,
            "value": value,
            "baseline_reference": None,
            "references": [
                {
                    "system": "github",
                    "stable_id": target,
                    "exact_location": source_path,
                    "verification_evidence": case,
                }
            ],
        }
        return validate_experiment_evidence(payload)
    except ContractValidationError as exc:
        # Preserve the shared finite validation/result shape; do not add an EXH or
        # Assessment-specific reason namespace.
        return ValidationResult(
            status=ValidationStatus.INVALID,
            record=None,
            reason_codes=(exc.reason_code,),
            details=(exc.detail,),
        )
