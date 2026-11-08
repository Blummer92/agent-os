"""Thin PPUX fidelity-evidence adapter for EXH5 (#1645).

The adapter projects supplied #1542 FidelityEvaluationResult evidence into the
shared experiment-evidence contract. PPUX owns the fidelity semantics; this
module adds no fields or reason codes to the shared EXH core.
"""

from __future__ import annotations

import json
from typing import Any

from .common import (
    ContractValidationError,
    ValidationResult,
    ValidationStatus,
    validate_stable_id,
    validate_text,
)
from .experiment_evidence import CONTRACT_VERSION, validate_experiment_evidence

ADAPTER_ID = "ppux-fidelity-evaluation"
ADAPTER_VERSION = "1.0.0"
EXPERIMENT_ID = "ppux-tutorial-image-benchmark"

FIDELITY_OUTCOMES = frozenset({"pass", "warn", "fail", "manual-review"})
CONSTRAINT_OUTCOMES = frozenset({"pass", "fail", "manual-review"})
EXECUTION_OUTCOMES = frozenset({"pass", "fail", "manual-review"})
METRIC_FIELDS = {
    "instructional-state-fidelity": ("instructional_state", FIDELITY_OUTCOMES),
    "interface-fidelity": ("interface_fidelity", FIDELITY_OUTCOMES),
    "artifact-state-fidelity": ("artifact_state_fidelity", FIDELITY_OUTCOMES),
    "negative-constraint-compliance": ("negative_constraints", CONSTRAINT_OUTCOMES),
    "execution-completion": ("execution_completion", EXECUTION_OUTCOMES),
}
SOURCE_FIELDS = frozenset(
    {
        "status",
        "provider",
        "model",
        "prompt_strategy",
        "instructional_state",
        "interface_fidelity",
        "artifact_state_fidelity",
        "negative_constraints",
        "execution_completion",
        "reasons",
        "generated_output_is_source_evidence",
    }
)


def _source(record: object) -> dict[str, Any]:
    if type(record) is not dict:
        raise ContractValidationError(
            "handoff-wrong-type", "PPUX fidelity result must be a built-in mapping"
        )
    if set(record) != SOURCE_FIELDS:
        if set(record) - SOURCE_FIELDS:
            raise ContractValidationError(
                "handoff-unknown-field", "PPUX fidelity result contains unknown fields"
            )
        raise ContractValidationError(
            "handoff-invalid", "PPUX fidelity result is missing required fields"
        )
    if record["generated_output_is_source_evidence"] is not False:
        raise ContractValidationError(
            "source-invalid", "generated PPUX output cannot be source instructional evidence"
        )
    status = record["status"]
    if status not in {"evaluated", "manual-review-required"}:
        raise ContractValidationError("handoff-invalid", "PPUX evaluation status is unsupported")
    provider = validate_text(record["provider"], "PPUX provider")
    model = validate_text(record["model"], "PPUX model")
    prompt_strategy = record["prompt_strategy"]
    if prompt_strategy is not None:
        prompt_strategy = validate_text(prompt_strategy, "PPUX prompt strategy")
    reasons = record["reasons"]
    if type(reasons) is not list or any(type(reason) is not str for reason in reasons):
        raise ContractValidationError("handoff-wrong-type", "PPUX reasons must be a string list")
    for metric_id, (field, allowed) in METRIC_FIELDS.items():
        if record[field] not in allowed:
            raise ContractValidationError(
                "handoff-invalid", f"PPUX {field} outcome is unsupported for {metric_id}"
            )
    return {
        **record,
        "provider": provider,
        "model": model,
        "prompt_strategy": prompt_strategy,
        "reasons": sorted(set(reason.strip() for reason in reasons if reason.strip())),
    }


def adapt_ppux_experiment_evidence(
    record: object,
    *,
    run_id: str,
    observation_id: str,
    metric_id: str,
    source_location: str,
    availability: str = "measured",
    record_revision: int = 1,
) -> ValidationResult:
    """Project one supplied canonical PPUX fidelity dimension into EXH2."""
    try:
        source = _source(record)
        run = validate_stable_id(run_id, "PPUX run_id")
        observation = validate_stable_id(observation_id, "PPUX observation_id")
        metric = validate_stable_id(metric_id, "PPUX metric_id")
        if metric not in METRIC_FIELDS:
            raise ContractValidationError("handoff-invalid", "PPUX metric_id is unsupported")
        location = validate_text(source_location, "PPUX source location")
        field, _ = METRIC_FIELDS[metric]
        value = source[field] if availability == "measured" else None
        provenance = {
            "provider": source["provider"],
            "model": source["model"],
            "prompt_strategy": source["prompt_strategy"],
            "evaluation_status": source["status"],
            "reasons": source["reasons"],
        }
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
                    "stable_id": "issue-1542",
                    "exact_location": location,
                    "verification_evidence": validate_text(
                        json.dumps(
                            provenance,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ),
                        "PPUX evaluation provenance",
                    ),
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
