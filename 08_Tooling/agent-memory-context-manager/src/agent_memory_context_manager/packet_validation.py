"""Validation helpers for Agent Memory handoff packets."""

from collections.abc import Mapping
from typing import Any

from .handoff_packet import DEFAULT_COMPUTE_LIMITS, REQUIRED_PACKET_FIELDS

STRING_PACKET_FIELDS: tuple[str, ...] = (
    "objective",
    "current_phase",
    "branch",
)

LIST_PACKET_FIELDS: tuple[str, ...] = (
    "changed_files",
    "allowed_inspect_first",
    "forbidden_unless_needed",
    "known_facts",
    "prior_decisions",
    "acceptance_criteria",
    "validation_commands",
    "stop_conditions",
)


def validate_handoff_packet(packet: Mapping[str, Any]) -> list[str]:
    """Return validation errors for a handoff packet."""
    if not isinstance(packet, Mapping):
        return ["packet must be a dict-like mapping"]

    errors: list[str] = []

    for field in REQUIRED_PACKET_FIELDS:
        if field not in packet:
            errors.append(f"missing required field: {field}")

    for field in STRING_PACKET_FIELDS:
        if field in packet and not isinstance(packet[field], str):
            errors.append(f"{field} must be a string")

    if "pr_number" in packet:
        pr_number = packet["pr_number"]
        if not isinstance(pr_number, int):
            errors.append("pr_number must be an integer")
        elif pr_number < 0:
            errors.append("pr_number must not be negative")

    for field in LIST_PACKET_FIELDS:
        if field in packet and not isinstance(packet[field], list):
            errors.append(f"{field} must be a list")

    if "compute_limits" in packet:
        compute_limits = packet["compute_limits"]
        if not isinstance(compute_limits, Mapping):
            errors.append("compute_limits must be a dict-like mapping")
        else:
            _validate_compute_limits(compute_limits, errors)

    return errors


def is_valid_handoff_packet(packet: Mapping[str, Any]) -> bool:
    """Return True when a handoff packet has no validation errors."""
    return not validate_handoff_packet(packet)


def assert_valid_handoff_packet(packet: Mapping[str, Any]) -> None:
    """Raise ValueError when a handoff packet is invalid."""
    errors = validate_handoff_packet(packet)
    if errors:
        raise ValueError("Invalid handoff packet: " + "; ".join(errors))


def _validate_compute_limits(
    compute_limits: Mapping[str, Any],
    errors: list[str],
) -> None:
    for field in DEFAULT_COMPUTE_LIMITS:
        if field not in compute_limits:
            errors.append(f"compute_limits.{field} is missing")

    max_files_to_inspect = compute_limits.get("max_files_to_inspect")
    if not isinstance(max_files_to_inspect, int):
        errors.append("compute_limits.max_files_to_inspect must be an integer")
    elif max_files_to_inspect <= 0:
        errors.append("compute_limits.max_files_to_inspect must be positive")

    for field in ("targeted_tests_only", "no_full_scheduler_suite"):
        value = compute_limits.get(field)
        if not isinstance(value, bool):
            errors.append(f"compute_limits.{field} must be a boolean")
