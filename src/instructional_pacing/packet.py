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

from .adaptation import validate_adaptation_candidates
from .comparability import OBSERVATION_QUALITY_STATES

CONTRACT_VERSION = "1.0"
MAX_EVIDENCE_SOURCES = 20
MAX_INSTRUCTIONAL_FUNCTIONS = 16
MAX_PRIOR_RUNS = 32
MAX_ROUTE_REFERENCES = 3

LIFECYCLE_STAGES = frozenset(
    {"design-only", "shadow-mode", "teacher-advisory", "calibrated-local", "suspended"}
)
PRIVACY_STATES = frozenset({"eligible", "restricted", "blocked", "unknown"})
#: Canonical LP14 observation-quality reason codes (family
#: ``observation-quality`` in ``04_Registry/lp-reason-code-catalog.yaml``).
#: Sourced from that catalog; this module never invents a competing code.
OBSERVATION_QUALITY_REASON_CODES = frozenset(
    {
        "lp-observation-checkpoint-missing",
        "lp-observation-recorded-too-late",
        "lp-observation-observer-disagreement",
        "lp-observation-category-overlap-unresolved",
        "lp-observation-aggregate-counts-contradictory",
        "lp-observation-burden-limit-exceeded",
        "lp-observation-confidence-too-low",
    }
)

#: The subset whose catalog record carries ``manual_review_required: true``,
#: copied by reference from that record rather than redefined here.
OBSERVATION_MANUAL_REVIEW_CODES = frozenset(
    {
        "lp-observation-observer-disagreement",
        "lp-observation-category-overlap-unresolved",
        "lp-observation-aggregate-counts-contradictory",
    }
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


def _validate_observation_quality(value: object) -> dict[str, Any]:
    """Admit one bounded canonical LP14 observation-quality projection.

    LP4 consumes LP14's own status vocabulary and reason-code family; it never
    restates that policy. Limitations arrive as canonical codes and are carried
    into the record rather than discarded.
    """
    if type(value) is not dict:
        raise ContractValidationError("handoff-wrong-type", "observation_quality must be a mapping")
    fields = set(value)
    if fields - {"status", "reason_codes"}:
        raise ContractValidationError("handoff-unknown-field", "observation_quality contains unknown fields")
    if "status" not in fields:
        raise ContractValidationError("handoff-invalid", "observation_quality is missing status")
    if value["status"] not in OBSERVATION_QUALITY_STATES:
        raise ContractValidationError("handoff-invalid", "observation_quality status is unsupported")
    codes = value.get("reason_codes", [])
    if type(codes) is not list or len(codes) > len(OBSERVATION_QUALITY_REASON_CODES):
        raise ContractValidationError("handoff-invalid", "observation_quality reason_codes are outside bounds")
    if any(code not in OBSERVATION_QUALITY_REASON_CODES for code in codes):
        raise ContractValidationError(
            "handoff-unknown-field", "observation_quality reason_codes are not canonical LP14 codes"
        )
    if len(set(codes)) != len(codes):
        raise ContractValidationError("handoff-duplicate", "observation_quality reason_codes contain duplicates")
    return {"status": value["status"], "reason_codes": sorted(codes)}


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

    normalized["observation_quality"] = _validate_observation_quality(normalized["observation_quality"])
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

    if "adaptations" in normalized:
        normalized["adaptations"] = validate_adaptation_candidates(normalized["adaptations"], functions)

    return normalized
