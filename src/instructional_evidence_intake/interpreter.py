"""Pure bounded interpreter for teacher-confirmed class-level evidence summaries."""

from __future__ import annotations

from typing import Any

from instructional_workflow_contracts import (
    FINGERPRINT_ALGORITHM,
    MAX_INPUT_BYTES,
    MAX_RESULT_BYTES,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_size,
    freeze_json,
    sha256_hex,
    validate_and_normalize_json,
    validate_revision,
    validate_stable_id,
    validate_version,
)

from .alignment import build_alignment

CONTRACT_ID = "instructional-evidence-teacher-summary-v1"
MAX_REFS_PER_DIMENSION = 64
MAX_CONTEXT_ITEMS = 32

TOP_LEVEL_FIELDS = frozenset(
    {
        "identity",
        "source_evidence",
        "observed_evidence",
        "current_assignment",
        "interpretation_context",
        "authority",
    }
)
IDENTITY_FIELDS = frozenset({"contract_version", "record_id", "record_revision"})
SOURCE_FIELDS = frozenset(
    {
        "source_ref",
        "source_type",
        "observed_on",
        "privacy_eligible",
        "freshness",
        "measurement_quality",
    }
)
EVIDENCE_FIELDS = frozenset(
    {
        "objective_refs",
        "prerequisite_refs",
        "success_criteria_refs",
        "depth_demands",
        "performance_formats",
        "tools_and_routines",
        "representation_demands",
        "work_modes",
        "evidence_quality",
        "evaluation_basis",
        "response_type",
        "support_conditions",
        "prompting",
        "revision",
        "independence",
    }
)
ASSIGNMENT_FIELDS = frozenset(
    {
        "objective_refs",
        "prerequisite_refs",
        "success_criteria_refs",
        "depth_demands",
        "performance_formats",
        "tools_and_routines",
        "representation_demands",
        "work_modes",
    }
)
CONTEXT_FIELDS = frozenset({"contradictions", "uncertainties", "manual_review_requested"})
AUTHORITY_FIELDS = frozenset(
    {
        "grading_authorized",
        "mastery_authorized",
        "readiness_authorized",
        "learner_classification_authorized",
        "placement_authorized",
        "route_assignment_authorized",
        "pacing_execution_authorized",
        "production_authorized",
        "publication_authorized",
        "external_write_authorized",
    }
)


def _invalid(reason: str, detail: str) -> ValidationResult:
    return ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason,),
        details=(detail,),
    )


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError(
            "handoff-wrong-type", f"{name} must be a built-in mapping"
        )
    return value


def _exact_fields(value: dict[str, Any], expected: frozenset[str], name: str) -> None:
    if set(value) != expected:
        if set(value) - expected:
            raise ContractValidationError(
                "handoff-unknown-field", f"{name} contains unknown fields"
            )
        raise ContractValidationError(
            "handoff-invalid", f"{name} is missing required fields"
        )


def _choice(value: Any, allowed: frozenset[str], name: str) -> str:
    if type(value) is not str or value not in allowed:
        raise ContractValidationError("handoff-invalid", f"{name} is unsupported")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ContractValidationError(
            "handoff-wrong-type", f"{name} must be a built-in Boolean"
        )
    return value


def _strings(value: Any, name: str, maximum: int) -> list[str]:
    if type(value) is not list:
        raise ContractValidationError(
            "handoff-wrong-type", f"{name} must be a built-in list"
        )
    if len(value) > maximum:
        raise ContractValidationError(
            "handoff-oversized", f"{name} exceeds its collection bound"
        )
    checked = [validate_stable_id(item, name) for item in value]
    if len(checked) != len(set(checked)):
        raise ContractValidationError(
            "handoff-duplicate", f"{name} contains duplicate values"
        )
    return sorted(checked)


def _validate_authority(authority: dict[str, Any]) -> None:
    _exact_fields(authority, AUTHORITY_FIELDS, "authority")
    for name, value in authority.items():
        if type(value) is not bool or value is not False:
            raise ContractValidationError(
                "authority-invalid", f"{name} must be built-in false"
            )


def interpret_teacher_summary(value: object) -> ValidationResult:
    """Validate and interpret one teacher-confirmed class-level evidence summary."""
    try:
        normalized = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
        payload = _mapping(normalized, "teacher summary")
        _exact_fields(payload, TOP_LEVEL_FIELDS, "teacher summary")

        identity = _mapping(payload["identity"], "identity")
        source = _mapping(payload["source_evidence"], "source_evidence")
        observed = _mapping(payload["observed_evidence"], "observed_evidence")
        assignment = _mapping(payload["current_assignment"], "current_assignment")
        context = _mapping(
            payload["interpretation_context"], "interpretation_context"
        )
        authority = _mapping(payload["authority"], "authority")

        _exact_fields(identity, IDENTITY_FIELDS, "identity")
        _exact_fields(source, SOURCE_FIELDS, "source_evidence")
        _exact_fields(observed, EVIDENCE_FIELDS, "observed_evidence")
        _exact_fields(assignment, ASSIGNMENT_FIELDS, "current_assignment")
        _exact_fields(context, CONTEXT_FIELDS, "interpretation_context")
        _validate_authority(authority)

        if validate_version(identity["contract_version"]) != CONTRACT_ID:
            raise ContractValidationError(
                "handoff-version-unsupported", "contract_version is unsupported"
            )
        record_id = validate_stable_id(identity["record_id"], "record_id")
        revision = validate_revision(identity["record_revision"])

        validate_stable_id(source["source_ref"], "source_ref")
        _choice(
            source["source_type"],
            frozenset({"teacher-summary", "structured-artifact-summary"}),
            "source_type",
        )
        if type(source["observed_on"]) is not str:
            raise ContractValidationError(
                "handoff-wrong-type", "observed_on must be a built-in string"
            )
        _bool(source["privacy_eligible"], "privacy_eligible")
        _choice(
            source["freshness"],
            frozenset({"current", "stale", "unknown"}),
            "freshness",
        )
        _choice(
            source["measurement_quality"],
            frozenset({"sufficient", "limited", "unknown"}),
            "measurement_quality",
        )

        dimension_fields = (
            "objective_refs",
            "prerequisite_refs",
            "success_criteria_refs",
            "depth_demands",
            "performance_formats",
            "tools_and_routines",
            "representation_demands",
            "work_modes",
        )
        for field in dimension_fields:
            observed[field] = _strings(
                observed[field],
                f"observed_evidence.{field}",
                MAX_REFS_PER_DIMENSION,
            )
            assignment[field] = _strings(
                assignment[field],
                f"current_assignment.{field}",
                MAX_REFS_PER_DIMENSION,
            )

        observed["support_conditions"] = _strings(
            observed["support_conditions"], "support_conditions", MAX_CONTEXT_ITEMS
        )
        _choice(
            observed["evidence_quality"],
            frozenset({"sufficient", "limited", "insufficient"}),
            "evidence_quality",
        )
        _choice(
            observed["evaluation_basis"],
            frozenset({"teacher-confirmed", "structured-rule", "none"}),
            "evaluation_basis",
        )
        _choice(
            observed["response_type"],
            frozenset({"closed", "open-ended", "observational"}),
            "response_type",
        )
        _choice(
            observed["prompting"],
            frozenset({"none", "some", "substantial", "unknown"}),
            "prompting",
        )
        _choice(
            observed["revision"],
            frozenset({"none", "available", "used", "unknown"}),
            "revision",
        )
        _choice(
            observed["independence"],
            frozenset({"independent", "supported", "unknown"}),
            "independence",
        )

        context["contradictions"] = _strings(
            context["contradictions"], "contradictions", MAX_CONTEXT_ITEMS
        )
        context["uncertainties"] = _strings(
            context["uncertainties"], "uncertainties", MAX_CONTEXT_ITEMS
        )
        _bool(context["manual_review_requested"], "manual_review_requested")

        alignment = build_alignment(payload)
        output = {
            "identity": {
                "contract_version": CONTRACT_ID,
                "record_id": record_id,
                "record_revision": revision,
            },
            "source_evidence": source,
            "alignment": alignment,
            "authority": {name: False for name in sorted(AUTHORITY_FIELDS)},
        }
        if canonical_size(output) > MAX_RESULT_BYTES:
            raise ContractValidationError(
                "handoff-oversized", "normalized result exceeds its byte bound"
            )

        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=record_id,
            record_revision=revision,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(output),
            payload=freeze_json(output),
        )

        if alignment["overall_disposition"] == "uncertain":
            return ValidationResult(
                status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
                record=record,
                reason_codes=("quality-manual-review",),
                details=(),
            )
        if source["freshness"] == "stale":
            return ValidationResult(
                status=ValidationStatus.STALE,
                record=record,
                reason_codes=("source-stale",),
                details=(),
            )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return _invalid(exc.reason_code, exc.detail)
    except (TypeError, ValueError):
        return _invalid("handoff-invalid", "teacher summary validation failed")
