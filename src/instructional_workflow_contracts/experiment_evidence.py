"""Pure bounded cross-domain experiment evidence contract for EXH2 (#1504)."""

from __future__ import annotations

from typing import Any

from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_INPUT_BYTES,
    MAX_REFERENCES,
    ContractReference,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    freeze_json,
    sha256_hex,
    validate_and_normalize_json,
    validate_revision,
    validate_stable_id,
    validate_version,
)

CONTRACT_VERSION = "experiment-evidence-v1"
AVAILABILITIES = frozenset({"measured", "unavailable", "lane-unavailable"})
TOP_LEVEL_FIELDS = frozenset(
    {
        "contract_version",
        "record_revision",
        "experiment_id",
        "run_id",
        "observation_id",
        "adapter_id",
        "adapter_version",
        "metric_id",
        "availability",
        "value",
        "baseline_reference",
        "references",
    }
)
REFERENCE_FIELDS = frozenset(
    {"system", "stable_id", "exact_location", "verification_evidence"}
)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError(
            "handoff-wrong-type", f"{name} must be a built-in mapping"
        )
    return value


def _list(value: Any, name: str, maximum: int) -> list[Any]:
    if type(value) is not list:
        raise ContractValidationError(
            "handoff-wrong-type", f"{name} must be a built-in list"
        )
    if len(value) > maximum:
        raise ContractValidationError(
            "handoff-oversized", f"{name} exceeds its collection bound"
        )
    return value


def _exact(value: dict[str, Any], expected: frozenset[str], name: str) -> None:
    if set(value) != expected:
        if set(value) - expected:
            raise ContractValidationError(
                "handoff-unknown-field", f"{name} contains unknown fields"
            )
        raise ContractValidationError(
            "handoff-invalid", f"{name} is missing required fields"
        )


def _reference(value: Any, name: str) -> ContractReference:
    reference = _mapping(value, name)
    _exact(reference, REFERENCE_FIELDS, name)
    return ContractReference(
        system=reference["system"],
        stable_id=reference["stable_id"],
        exact_location=reference["exact_location"],
        verification_evidence=reference["verification_evidence"],
    )


def _reference_dict(reference: ContractReference) -> dict[str, str]:
    return {
        "system": reference.system,
        "stable_id": reference.stable_id,
        "exact_location": reference.exact_location,
        "verification_evidence": reference.verification_evidence,
    }


def validate_experiment_evidence(value: object) -> ValidationResult:
    """Validate one provider-neutral observation without assigning domain meaning."""
    try:
        normalized = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
        payload = _mapping(normalized, "experiment evidence")
        _exact(payload, TOP_LEVEL_FIELDS, "experiment evidence")

        if validate_version(payload["contract_version"]) != CONTRACT_VERSION:
            raise ContractValidationError(
                "handoff-version-unsupported", "contract_version is unsupported"
            )
        revision = validate_revision(payload["record_revision"])
        experiment_id = validate_stable_id(payload["experiment_id"], "experiment_id")
        run_id = validate_stable_id(payload["run_id"], "run_id")
        observation_id = validate_stable_id(payload["observation_id"], "observation_id")
        adapter_id = validate_stable_id(payload["adapter_id"], "adapter_id")
        adapter_version = validate_version(payload["adapter_version"])
        metric_id = validate_stable_id(payload["metric_id"], "metric_id")
        availability = validate_stable_id(payload["availability"], "availability")
        if availability not in AVAILABILITIES:
            raise ContractValidationError(
                "handoff-invalid", "availability is unsupported"
            )

        measured_value = payload["value"]
        if availability == "measured":
            if measured_value is None:
                raise ContractValidationError(
                    "handoff-invalid", "measured observations require value"
                )
        elif measured_value is not None:
            raise ContractValidationError(
                "handoff-invalid", "unavailable observations cannot carry value"
            )

        baseline = None
        if payload["baseline_reference"] is not None:
            baseline = _reference(payload["baseline_reference"], "baseline_reference")

        references = [
            _reference(item, "reference")
            for item in _list(payload["references"], "references", MAX_REFERENCES)
        ]
        reference_payloads = sorted(
            (_reference_dict(reference) for reference in references),
            key=lambda item: (
                item["system"],
                item["stable_id"],
                item["exact_location"],
                item["verification_evidence"],
            ),
        )
        if len({sha256_hex(item) for item in reference_payloads}) != len(reference_payloads):
            raise ContractValidationError(
                "handoff-duplicate", "references must be unique"
            )

        record_payload = {
            "contract_version": CONTRACT_VERSION,
            "record_revision": revision,
            "experiment_id": experiment_id,
            "run_id": run_id,
            "observation_id": observation_id,
            "adapter_id": adapter_id,
            "adapter_version": adapter_version,
            "metric_id": metric_id,
            "availability": availability,
            "value": measured_value,
            "baseline_reference": None if baseline is None else _reference_dict(baseline),
            "references": reference_payloads,
            "execution_authorized": False,
            "external_write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
        }
        fingerprint = sha256_hex(record_payload)
        record = ValidatedRecord(
            contract_version=CONTRACT_VERSION,
            record_id=f"experiment-observation-{fingerprint[:24]}",
            record_revision=revision,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=fingerprint,
            payload=freeze_json(record_payload),
        )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return ValidationResult(
            status=ValidationStatus.INVALID,
            record=None,
            reason_codes=(exc.reason_code,),
            details=(exc.detail,),
        )
