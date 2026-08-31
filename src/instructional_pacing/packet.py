"""LP4 packet admission built on the shared instructional-workflow mechanics."""

from __future__ import annotations

from typing import Any

from instructional_workflow_contracts import (
    ContractValidationError,
    validate_and_normalize_json,
    validate_revision,
    validate_stable_id,
    validate_version,
)

CONTRACT_VERSION = "1.0"
MAX_EVIDENCE_SOURCES = 20
MAX_INSTRUCTIONAL_FUNCTIONS = 16
MAX_PRIOR_RUNS = 32
MAX_ROUTE_REFERENCES = 3

LIFECYCLE_STAGES = frozenset(
    {"design-only", "shadow-mode", "teacher-advisory", "calibrated-local", "suspended"}
)
PRIVACY_STATES = frozenset({"eligible", "restricted", "blocked", "unknown"})
EVIDENCE_DISPOSITIONS = frozenset(
    {"direct-evidence", "partial-evidence", "context-evidence", "not-comparable", "uncertain"}
)

NON_AUTHORITY_FIELDS = {
    "report_only": True,
    "execution_authorized": False,
    "artifact_authorized": False,
    "readiness_authorized": False,
    "grading_authorized": False,
    "student_classification_authorized": False,
    "automatic_placement_authorized": False,
    "route_assignment_authorized": False,
    "production_authorized": False,
    "external_write_authorized": False,
}

_REQUIRED_FIELDS = frozenset(
    {
        "contract_version",
        "record_id",
        "record_revision",
        "objective_ref",
        "success_criteria_ref",
        "period_minutes",
        "operational_minutes",
        "instructional_functions",
        "evidence_sources",
        "prior_runs",
        "observation_quality",
        "privacy_disposition",
        "demand_profile",
        "implementation_stage",
        "continuation_allowed",
    }
)
_OPTIONAL_FIELDS = frozenset(
    {
        "work_mode",
        "route_references",
        "calibration",
        "adaptations",
        "teacher_decision",
        "what_supported",
        "what_remains_unmeasured",
    }
)


def _number(value: object, name: str, *, allow_zero: bool = False) -> float:
    if type(value) not in {int, float}:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in number")
    numeric = float(value)
    if numeric < 0 or (numeric == 0 and not allow_zero):
        raise ContractValidationError("handoff-invalid", f"{name} must be positive")
    return numeric


def _bounded_list(value: object, name: str, maximum: int) -> list[Any]:
    if type(value) is not list:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in list")
    if len(value) > maximum:
        raise ContractValidationError("handoff-oversized", f"{name} exceeds its collection bound")
    return value


def _validate_functions(functions: list[Any]) -> None:
    if not functions:
        raise ContractValidationError("handoff-invalid", "instructional_functions cannot be empty")
    names: set[str] = set()
    for item in functions:
        if type(item) is not dict:
            raise ContractValidationError("handoff-wrong-type", "instructional function must be a mapping")
        if set(item) != {"name", "protected", "lower_minutes", "expected_minutes", "upper_minutes"}:
            raise ContractValidationError("handoff-invalid", "instructional function fields are not canonical")
        name = validate_stable_id(item["name"], "instructional function name")
        if name in names:
            raise ContractValidationError("handoff-duplicate", "instructional function names must be unique")
        names.add(name)
        if type(item["protected"]) is not bool:
            raise ContractValidationError("handoff-wrong-type", "instructional function protected must be bool")
        lower = _number(item["lower_minutes"], "lower_minutes", allow_zero=True)
        expected = _number(item["expected_minutes"], "expected_minutes", allow_zero=True)
        upper = _number(item["upper_minutes"], "upper_minutes", allow_zero=True)
        if not lower <= expected <= upper:
            raise ContractValidationError("lp-pacing-duration-order-invalid", "instructional function duration order is invalid")


def validate_pacing_packet(value: object) -> dict[str, Any]:
    """Normalize and validate one supplied-evidence-only LP4 packet."""
    normalized = validate_and_normalize_json(value)
    if type(normalized) is not dict:
        raise ContractValidationError("handoff-wrong-type", "pacing packet must be a built-in mapping")
    fields = set(normalized)
    missing = _REQUIRED_FIELDS - fields
    unknown = fields - (_REQUIRED_FIELDS | _OPTIONAL_FIELDS)
    if missing:
        raise ContractValidationError("handoff-invalid", "pacing packet is missing required fields")
    if unknown:
        raise ContractValidationError("handoff-unknown-field", "pacing packet contains unknown fields")

    version = validate_version(normalized["contract_version"])
    if version != CONTRACT_VERSION:
        raise ContractValidationError("handoff-version-unsupported", "LP4 contract version is unsupported")
    validate_stable_id(normalized["record_id"], "record_id")
    validate_revision(normalized["record_revision"])
    validate_stable_id(normalized["objective_ref"], "objective_ref")
    validate_stable_id(normalized["success_criteria_ref"], "success_criteria_ref")

    period = _number(normalized["period_minutes"], "period_minutes")
    operational = _number(normalized["operational_minutes"], "operational_minutes", allow_zero=True)
    if operational >= period:
        raise ContractValidationError("lp-pacing-time-budget-missing", "operational minutes consume the period")

    functions = _bounded_list(normalized["instructional_functions"], "instructional_functions", MAX_INSTRUCTIONAL_FUNCTIONS)
    _validate_functions(functions)
    _bounded_list(normalized["evidence_sources"], "evidence_sources", MAX_EVIDENCE_SOURCES)
    _bounded_list(normalized["prior_runs"], "prior_runs", MAX_PRIOR_RUNS)

    if type(normalized["observation_quality"]) is not dict:
        raise ContractValidationError("handoff-wrong-type", "observation_quality must be a mapping")
    privacy = normalized["privacy_disposition"]
    if privacy not in PRIVACY_STATES:
        raise ContractValidationError("handoff-invalid", "privacy_disposition is unsupported")
    stage = normalized["implementation_stage"]
    if stage not in LIFECYCLE_STAGES:
        raise ContractValidationError("handoff-invalid", "implementation_stage is unsupported")
    if type(normalized["continuation_allowed"]) is not bool:
        raise ContractValidationError("handoff-wrong-type", "continuation_allowed must be bool")

    if "route_references" in normalized:
        refs = _bounded_list(normalized["route_references"], "route_references", MAX_ROUTE_REFERENCES)
        for ref in refs:
            validate_stable_id(ref, "route reference")

    return normalized
