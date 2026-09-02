"""Deterministic LP3 pacing adaptation planning for LP4 (#1630).

The planner consumes only the already-supplied LP4 packet and timing evidence.
It applies the canonical LP3 adaptation hierarchy without changing objectives,
success criteria, authority, learner routes, or external systems.
"""

from __future__ import annotations

from typing import Any

from instructional_workflow_contracts import ContractValidationError, validate_stable_id

ADAPTATION_SECTIONS = (
    "operational_friction",
    "extraneous_material",
    "transitions",
    "repetitions",
    "evidence_formats",
    "optional_polish",
)

MAX_ADAPTATION_CANDIDATES = 24
MAX_SECTION_CANDIDATES = 16
MAX_MINUTES_SAVED = 240.0

_SIMPLE_FIELDS = frozenset({"id", "minutes_saved"})
_REPETITION_FIELDS = frozenset({"id", "function_name", "minutes_saved", "preserves_function"})
_FORMAT_FIELDS = frozenset(
    {
        "id",
        "function_name",
        "minutes_saved",
        "from_format",
        "to_format",
        "preserves_objective",
        "preserves_success_criteria",
        "preserves_accessibility",
    }
)
_POLISH_FIELDS = frozenset({"id", "function_name", "minutes_saved"})


def _minutes(value: object, name: str) -> float:
    if type(value) not in {int, float}:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in number")
    minutes = float(value)
    if minutes <= 0 or minutes > MAX_MINUTES_SAVED:
        raise ContractValidationError("handoff-invalid", f"{name} is outside the allowed range")
    return minutes


def _list(value: object, name: str) -> list[Any]:
    if type(value) is not list:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in list")
    if len(value) > MAX_SECTION_CANDIDATES:
        raise ContractValidationError("handoff-oversized", f"{name} exceeds its collection bound")
    return value


def _mapping(value: object, expected: frozenset[str], name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a mapping")
    if set(value) != expected:
        if set(value) - expected:
            raise ContractValidationError("handoff-unknown-field", f"{name} contains unknown fields")
        raise ContractValidationError("handoff-invalid", f"{name} is missing required fields")
    return value


def validate_adaptation_candidates(
    value: object,
    instructional_functions: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Validate the bounded candidate input used by the ordered LP3 planner."""
    if type(value) is not dict:
        raise ContractValidationError("handoff-wrong-type", "adaptations must be a mapping")
    unknown = set(value) - set(ADAPTATION_SECTIONS)
    if unknown:
        raise ContractValidationError("handoff-unknown-field", "adaptations contains unknown sections")

    function_protection = {item["name"]: bool(item["protected"]) for item in instructional_functions}
    result: dict[str, list[dict[str, Any]]] = {section: [] for section in ADAPTATION_SECTIONS}
    seen_ids: set[str] = set()
    total = 0

    for section in ADAPTATION_SECTIONS:
        items = _list(value.get(section, []), f"adaptations.{section}")
        total += len(items)
        if total > MAX_ADAPTATION_CANDIDATES:
            raise ContractValidationError("handoff-oversized", "adaptation candidates exceed the total bound")

        for index, raw in enumerate(items):
            name = f"adaptations.{section}[{index}]"
            if section in {"operational_friction", "extraneous_material", "transitions"}:
                item = _mapping(raw, _SIMPLE_FIELDS, name)
                candidate_id = validate_stable_id(item["id"], f"{name}.id")
                normalized = {"id": candidate_id, "minutes_saved": _minutes(item["minutes_saved"], f"{name}.minutes_saved")}
            elif section == "repetitions":
                item = _mapping(raw, _REPETITION_FIELDS, name)
                candidate_id = validate_stable_id(item["id"], f"{name}.id")
                function_name = validate_stable_id(item["function_name"], f"{name}.function_name")
                if function_name not in function_protection:
                    raise ContractValidationError("handoff-invalid", "repetition candidate references an unknown function")
                if type(item["preserves_function"]) is not bool:
                    raise ContractValidationError("handoff-wrong-type", "preserves_function must be bool")
                if item["preserves_function"] is not True:
                    raise ContractValidationError(
                        "lp-pacing-required-function-removed",
                        "repetition reduction must preserve the instructional function",
                    )
                normalized = {
                    "id": candidate_id,
                    "function_name": function_name,
                    "minutes_saved": _minutes(item["minutes_saved"], f"{name}.minutes_saved"),
                    "preserves_function": True,
                }
            elif section == "evidence_formats":
                item = _mapping(raw, _FORMAT_FIELDS, name)
                candidate_id = validate_stable_id(item["id"], f"{name}.id")
                function_name = validate_stable_id(item["function_name"], f"{name}.function_name")
                if function_name not in function_protection:
                    raise ContractValidationError("handoff-invalid", "evidence-format candidate references an unknown function")
                flags = (
                    "preserves_objective",
                    "preserves_success_criteria",
                    "preserves_accessibility",
                )
                for flag in flags:
                    if type(item[flag]) is not bool:
                        raise ContractValidationError("handoff-wrong-type", f"{flag} must be bool")
                    if item[flag] is not True:
                        raise ContractValidationError(
                            "handoff-invalid",
                            "evidence-format change must preserve objective, success criteria, and accessibility",
                        )
                normalized = {
                    "id": candidate_id,
                    "function_name": function_name,
                    "minutes_saved": _minutes(item["minutes_saved"], f"{name}.minutes_saved"),
                    "from_format": validate_stable_id(item["from_format"], f"{name}.from_format"),
                    "to_format": validate_stable_id(item["to_format"], f"{name}.to_format"),
                    "preserves_objective": True,
                    "preserves_success_criteria": True,
                    "preserves_accessibility": True,
                }
            else:
                item = _mapping(raw, _POLISH_FIELDS, name)
                candidate_id = validate_stable_id(item["id"], f"{name}.id")
                function_name = validate_stable_id(item["function_name"], f"{name}.function_name")
                if function_name not in function_protection:
                    raise ContractValidationError("handoff-invalid", "optional-polish candidate references an unknown function")
                if function_protection[function_name]:
                    raise ContractValidationError(
                        "lp-pacing-required-function-removed",
                        "a protected instructional function cannot be deferred as optional polish",
                    )
                normalized = {
                    "id": candidate_id,
                    "function_name": function_name,
                    "minutes_saved": _minutes(item["minutes_saved"], f"{name}.minutes_saved"),
                }

            if candidate_id in seen_ids:
                raise ContractValidationError("handoff-duplicate", "adaptation candidate ids must be unique")
            seen_ids.add(candidate_id)
            result[section].append(normalized)

        result[section].sort(key=lambda candidate: candidate["id"])

    return result


def _adapted_range(timing: dict[str, float], savings: float) -> dict[str, float]:
    lower = float(timing["lower"])
    expected = max(lower, float(timing["expected"]) - savings)
    upper = max(expected, float(timing["upper"]) - savings)
    return {"lower": lower, "expected": expected, "upper": upper}


def _split_plan(functions: list[dict[str, Any]], available: float) -> dict[str, Any] | None:
    cumulative = 0.0
    split_after: str | None = None
    for item in functions:
        expected = float(item["expected_minutes"])
        if cumulative + expected > available:
            break
        cumulative += expected
        split_after = item["name"]

    if split_after is None or split_after == functions[-1]["name"]:
        return None

    total = sum(float(item["expected_minutes"]) for item in functions)
    return {
        "split_after": split_after,
        "first_period_expected_minutes": cumulative,
        "continuation_expected_minutes": max(0.0, total - cumulative),
        "teacher_review_required": True,
    }


def plan_lesson_adaptation(
    packet: dict[str, Any],
    timing: dict[str, float],
    available: float,
) -> dict[str, Any]:
    """Apply the canonical LP3 hierarchy and return report-only adaptation evidence."""
    candidates = packet.get("adaptations") or {section: [] for section in ADAPTATION_SECTIONS}
    required_savings = 0.0
    if float(timing["expected"]) > available:
        required_savings = float(timing["expected"]) - available
    elif float(timing["upper"]) > available:
        required_savings = float(timing["upper"]) - available

    compressed: list[dict[str, Any]] = []
    changed_formats: list[dict[str, Any]] = []
    deferred: list[str] = []
    selected_savings = 0.0

    for section in ADAPTATION_SECTIONS:
        if required_savings <= selected_savings:
            break
        for candidate in candidates[section]:
            if required_savings <= selected_savings:
                break
            selected_savings += float(candidate["minutes_saved"])
            if section == "evidence_formats":
                changed_formats.append(
                    {
                        "id": candidate["id"],
                        "function_name": candidate["function_name"],
                        "from_format": candidate["from_format"],
                        "to_format": candidate["to_format"],
                        "minutes_saved": candidate["minutes_saved"],
                    }
                )
            elif section == "optional_polish":
                deferred.append(candidate["function_name"])
            else:
                record = {
                    "id": candidate["id"],
                    "kind": section.replace("_", "-"),
                    "minutes_saved": candidate["minutes_saved"],
                }
                if "function_name" in candidate:
                    record["function_name"] = candidate["function_name"]
                compressed.append(record)

    adapted = _adapted_range(timing, selected_savings)
    split_plan = None
    split_unresolved = False
    if adapted["expected"] > available and packet["continuation_allowed"]:
        split_plan = _split_plan(packet["instructional_functions"], available)
        split_unresolved = split_plan is None

    return {
        "adapted_range": adapted,
        "compressed_instances": compressed,
        "changed_formats": changed_formats,
        "deferred_functions": sorted(set(deferred)),
        "split_plan": split_plan,
        "selected_savings_minutes": selected_savings,
        "split_unresolved": split_unresolved,
        "manual_review_required": bool(compressed or changed_formats or deferred or split_plan or split_unresolved),
    }
