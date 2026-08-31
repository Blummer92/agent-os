"""Six-dimensional LP4 diagnosis with no composite learner/task score."""

from __future__ import annotations

from typing import Any

from instructional_workflow_contracts import ContractValidationError, validate_stable_id

DIMENSIONS = (
    "instructional_demand",
    "learner_relative_familiarity",
    "language_and_representation_load",
    "material_induced_load",
    "operational_load",
    "evidence_uncertainty",
)
LEVELS = frozenset({"low", "moderate", "high", "unknown"})
MAX_EVIDENCE_REFS = 8


def diagnose_dimensions(profile: object) -> dict[str, dict[str, Any]]:
    """Validate and return the six canonical dimensions independently."""
    if type(profile) is not dict or set(profile) != set(DIMENSIONS):
        raise ContractValidationError("handoff-invalid", "demand_profile must contain exactly six canonical dimensions")
    result: dict[str, dict[str, Any]] = {}
    for dimension in DIMENSIONS:
        item = profile[dimension]
        if type(item) is not dict or set(item) != {"level", "evidence_refs", "uncertainty"}:
            raise ContractValidationError("handoff-invalid", f"{dimension} fields are not canonical")
        level = item["level"]
        uncertainty = item["uncertainty"]
        if level not in LEVELS or uncertainty not in LEVELS:
            raise ContractValidationError("handoff-invalid", f"{dimension} level is unsupported")
        refs = item["evidence_refs"]
        if type(refs) is not list or len(refs) > MAX_EVIDENCE_REFS:
            raise ContractValidationError("handoff-invalid", f"{dimension} evidence_refs are outside bounds")
        checked: list[str] = []
        for ref in refs:
            checked.append(validate_stable_id(ref, f"{dimension} evidence ref"))
        if len(set(checked)) != len(checked):
            raise ContractValidationError("handoff-duplicate", f"{dimension} evidence_refs contain duplicates")
        result[dimension] = {
            "level": level,
            "evidence_refs": sorted(checked),
            "uncertainty": uncertainty,
        }
    return result
