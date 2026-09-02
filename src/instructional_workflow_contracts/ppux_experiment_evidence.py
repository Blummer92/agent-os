"""Thin PPUX experiment-evidence adapter for EXH5 (#1645).

The adapter projects supplied canonical Picture Perfect fidelity results into the
shared experiment-evidence contract. PPUX remains the semantic owner; this module
adds no PPUX fields or reason codes to the shared EXH core.
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

ADAPTER_ID = "ppux-tutorial-image-benchmark"
ADAPTER_VERSION = "1.0.0"
EXPERIMENT_ID = "ppux-tutorial-image-fidelity"

SINGLE_FRAME_METRICS = frozenset(
    {
        "instructional-state-fidelity",
        "interface-fidelity",
        "artifact-state-fidelity",
        "negative-constraint-compliance",
        "execution-completion",
    }
)
SEQUENCE_METRIC = "cross-frame-sequence-fidelity"


def _mapping(value: object, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError(
            "handoff-wrong-type", f"{name} must be a built-in mapping"
        )
    return value


def _single_frame_value(record: dict[str, Any], metric_id: str) -> Any:
    field = metric_id.replace("-", "_")
    if field == "negative_constraint_compliance":
        field = "negative_constraints"
    if field not in record:
        raise ContractValidationError(
            "handoff-invalid", f"PPUX single-frame evidence is missing {field}"
        )
    if record.get("status") == "manual-review-required" or record[field] == "manual-review":
        raise ContractValidationError(
            "handoff-manual-review", "PPUX single-frame evidence requires manual review"
        )
    return record[field]


def _sequence_value(record: dict[str, Any]) -> Any:
    status = record.get("status")
    if status not in {"pass", "fail", "manual-review"}:
        raise ContractValidationError(
            "handoff-invalid", "PPUX sequence evidence has unsupported status"
        )
    if status == "manual-review":
        raise ContractValidationError(
            "handoff-manual-review", "PPUX sequence evidence requires manual review"
        )
    return status


def adapt_ppux_experiment_evidence(
    record: object,
    *,
    evidence_kind: str,
    metric_id: str,
    run_id: str,
    observation_id: str,
    evidence_location: str,
    availability: str = "measured",
    record_revision: int = 1,
) -> ValidationResult:
    """Project one supplied canonical PPUX result into EXH2 without reinterpreting it."""
    try:
        source = _mapping(record, "PPUX evidence")
        kind = validate_stable_id(evidence_kind, "PPUX evidence kind")
        metric = validate_stable_id(metric_id, "PPUX metric id")
        run = validate_stable_id(run_id, "PPUX run id")
        observation = validate_stable_id(observation_id, "PPUX observation id")
        location = validate_text(evidence_location, "PPUX evidence location")

        if availability == "measured":
            if kind == "single-frame":
                if metric not in SINGLE_FRAME_METRICS:
                    raise ContractValidationError(
                        "handoff-invalid", "unsupported PPUX single-frame metric"
                    )
                value = _single_frame_value(source, metric)
            elif kind == "sequence":
                if metric != SEQUENCE_METRIC:
                    raise ContractValidationError(
                        "handoff-invalid", "unsupported PPUX sequence metric"
                    )
                value = _sequence_value(source)
            else:
                raise ContractValidationError(
                    "handoff-invalid", "unsupported PPUX evidence kind"
                )
        else:
            value = None

        provider = source.get("provider")
        model = source.get("model")
        provenance = "canonical-ppux-evaluation"
        if kind == "single-frame":
            provider = validate_text(provider, "PPUX provider")
            model = validate_text(model, "PPUX model")
            provenance = f"provider={provider};model={model}"

        payload = {
            "contract_version": CONTRACT_VERSION,
            "record_revision": record_revision,
            "experiment_id": EXPERIMENT_ID,
            "run_id": run,
            "observation_id": observation,
            "adapter_id": ADAPTER_ID,
            "adapter_version": ADAPTER_VERSION,
            "metric_id": metric,
            "availability": availability,
            "value": value,
            "baseline_reference": None,
            "references": [
                {
                    "system": "github",
                    "stable_id": observation,
                    "exact_location": location,
                    "verification_evidence": provenance,
                }
            ],
        }
        return validate_experiment_evidence(payload)
    except ContractValidationError as exc:
        return ValidationResult(
            status=ValidationStatus.INVALID,
            record=None,
            reason_codes=(exc.reason_code,),
            details=(exc.detail,),
        )
