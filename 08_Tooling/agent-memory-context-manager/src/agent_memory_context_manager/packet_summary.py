"""Summary helpers for Agent Memory handoff packets."""

from collections.abc import Mapping, Sequence
from typing import Any

from .packet_validation import assert_valid_handoff_packet

DEFAULT_SUMMARY_LIST_LIMIT = 3


def summarize_handoff_packet(
    packet: Mapping[str, Any],
    *,
    list_limit: int = DEFAULT_SUMMARY_LIST_LIMIT,
) -> str:
    """Return a compact text summary for a validated handoff packet."""
    assert_valid_handoff_packet(packet)

    limit = max(0, list_limit)
    lines = [
        f"Objective: {packet['objective']}",
        f"Current phase: {packet['current_phase']}",
        f"Branch: {packet['branch']}",
        f"PR number: {packet['pr_number']}",
    ]

    _append_list_section(lines, "Changed files", packet["changed_files"], limit)
    _append_list_section(
        lines,
        "Allowed inspect first",
        packet["allowed_inspect_first"],
        limit,
    )
    _append_list_section(lines, "Known facts", packet["known_facts"], limit)
    _append_list_section(lines, "Prior decisions", packet["prior_decisions"], limit)
    _append_list_section(
        lines,
        "Validation commands",
        packet["validation_commands"],
        limit,
    )
    _append_list_section(lines, "Stop conditions", packet["stop_conditions"], limit)

    lines.append("Compute limits:")
    for key, value in packet["compute_limits"].items():
        lines.append(f"- {key}: {value}")

    return "\n".join(lines)


def _append_list_section(
    lines: list[str],
    title: str,
    values: Sequence[Any],
    limit: int,
) -> None:
    lines.append(f"{title}:")
    displayed_values = list(values[:limit])
    for value in displayed_values:
        lines.append(f"- {value}")

    remaining = len(values) - len(displayed_values)
    if remaining > 0:
        lines.append(f"...and {remaining} more")
