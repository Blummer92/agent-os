"""Minimal handoff packet builder for Agent Memory & Context Budget Manager."""

from copy import deepcopy
from typing import Any

DEFAULT_COMPUTE_LIMITS: dict[str, Any] = {
    "max_files_to_inspect": 8,
    "targeted_tests_only": True,
    "no_full_scheduler_suite": True,
}

REQUIRED_PACKET_FIELDS: tuple[str, ...] = (
    "objective",
    "current_phase",
    "branch",
    "pr_number",
    "changed_files",
    "allowed_inspect_first",
    "forbidden_unless_needed",
    "known_facts",
    "prior_decisions",
    "acceptance_criteria",
    "validation_commands",
    "compute_limits",
    "stop_conditions",
)


def build_handoff_packet(
    *,
    objective: str,
    current_phase: str,
    branch: str | None,
    pr_number: int | None,
    changed_files: list[str],
    allowed_inspect_first: list[str],
    forbidden_unless_needed: list[str],
    known_facts: list[str],
    prior_decisions: list[str],
    acceptance_criteria: list[str],
    validation_commands: list[str],
    stop_conditions: list[str],
    compute_limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a local handoff packet from explicit inputs only."""
    merged_compute_limits = deepcopy(DEFAULT_COMPUTE_LIMITS)
    if compute_limits:
        merged_compute_limits.update(deepcopy(compute_limits))

    return {
        "objective": objective,
        "current_phase": current_phase,
        "branch": branch,
        "pr_number": pr_number,
        "changed_files": deepcopy(changed_files),
        "allowed_inspect_first": deepcopy(allowed_inspect_first),
        "forbidden_unless_needed": deepcopy(forbidden_unless_needed),
        "known_facts": deepcopy(known_facts),
        "prior_decisions": deepcopy(prior_decisions),
        "acceptance_criteria": deepcopy(acceptance_criteria),
        "validation_commands": deepcopy(validation_commands),
        "compute_limits": merged_compute_limits,
        "stop_conditions": deepcopy(stop_conditions),
    }
