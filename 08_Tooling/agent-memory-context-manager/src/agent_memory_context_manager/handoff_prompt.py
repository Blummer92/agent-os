"""Bounded handoff-prompt projection for established mission checkpoints (#2749).

A request to *generate a handoff prompt* is a projection of already-established
checkpoint state, not a resumption of the underlying investigation. This module
draws the decision boundary the orchestrator was missing:

- ``project_handoff_prompt`` renders a continuation prompt from a validated
  handoff packet using only the state the packet already carries;
- it performs no network, subprocess, filesystem, or GitHub access and never
  re-runs the underlying audit;
- already-proven findings are reused verbatim (within a fixed per-section
  bound); unresolved blockers and the exact next action are preserved;
- an unestablished or invalid checkpoint fails closed instead of being
  "completed" by a fresh investigation.

Callers that need fresh evidence must resume the mission through the existing
execution path. Prompt generation stays bounded independently of the size of
the parent audit: every rendered list is capped and truncation is explicit.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .packet_validation import assert_valid_handoff_packet

#: Maximum rendered items per prompt section. Generation cost stays flat no
#: matter how large the parent audit grew.
MAX_PROMPT_SECTION_ITEMS = 25

#: Report fields every handoff continuation must produce, so the next
#: execution emits the same evidence the current one would.
REQUIRED_REPORT_FIELDS: tuple[str, ...] = (
    "Files changed",
    "Tests run",
    "Docs updated",
    "Unresolved blockers",
    "Handoff recommendation",
    "Remaining risk",
)


def _render_items(items: Any) -> list[str]:
    """Render one packet list as bounded prompt lines with explicit truncation."""
    if not isinstance(items, list) or not items:
        return ["- (none recorded)"]
    lines = [f"- {item}" for item in items[:MAX_PROMPT_SECTION_ITEMS]]
    overflow = len(items) - MAX_PROMPT_SECTION_ITEMS
    if overflow > 0:
        lines.append(f"- ... (+{overflow} more recorded in the checkpoint)")
    return lines


def _checkpoint_lines(packet: Mapping[str, Any]) -> list[str]:
    branch = packet.get("branch")
    pr_number = packet.get("pr_number")
    return [
        f"- Phase: {packet.get('current_phase')}",
        f"- Branch: {branch if branch else 'none (pre-branch)'}",
        f"- PR: #{pr_number}" if isinstance(pr_number, int) else "- PR: none (pre-PR)",
        f"- Changed files ({len(packet.get('changed_files') or [])}):",
        *_render_items(packet.get("changed_files")),
    ]


def _next_action(packet: Mapping[str, Any]) -> str:
    """Resolve the exact next action without consulting anything but the packet."""
    explicit = packet.get("next_action", None)
    if explicit is not None:
        if not isinstance(explicit, str) or not explicit.strip():
            raise ValueError(
                "Invalid handoff packet for prompt projection: "
                "next_action must be a non-empty string when present"
            )
        return explicit.strip()
    allowed = packet.get("allowed_inspect_first") or []
    if isinstance(allowed, list) and allowed:
        return f"Inspect next: {allowed[0]} (first of the checkpoint's allowed-inspect list)"
    return (
        f"Continue the current phase ({packet.get('current_phase')}) from the "
        "checkpoint above; do not re-run completed investigation steps."
    )


def _compute_limit_lines(packet: Mapping[str, Any]) -> list[str]:
    limits = packet.get("compute_limits") or {}
    if not isinstance(limits, Mapping) or not limits:
        return ["- (none recorded)"]
    return [f"- {key}: {value}" for key, value in sorted(limits.items())]


def project_handoff_prompt(packet: Mapping[str, Any]) -> str:
    """Render a bounded continuation prompt from an established checkpoint.

    This is a pure projection: it reads only the supplied packet mapping and
    performs no I/O of any kind. ``ValueError`` is raised on an invalid packet
    instead of attempting to re-establish the checkpoint by investigating.
    """
    assert_valid_handoff_packet(packet)

    sections = [
        "# Handoff continuation prompt",
        "",
        "> Projected from the established mission checkpoint below. No re-audit",
        "> was performed to generate this prompt: findings are reused exactly as",
        "> recorded, and only the listed blockers and next action govern what",
        "> the next execution may do.",
        "",
        "## Objective",
        "",
        str(packet.get("objective")),
        "",
        "## Current checkpoint (preserved cursor)",
        "",
        *_checkpoint_lines(packet),
        "",
        "## Established findings (reused, not re-audited)",
        "",
        *_render_items(packet.get("known_facts")),
        "",
        "## Lineage (prior decisions)",
        "",
        *_render_items(packet.get("prior_decisions")),
        "",
        "## Exact next action",
        "",
        _next_action(packet),
        "",
        "## Unresolved blockers / stop conditions",
        "",
        *_render_items(packet.get("stop_conditions")),
        "",
        "## Bounds for the next execution",
        "",
        "Inspect first:",
        *_render_items(packet.get("allowed_inspect_first")),
        "Forbidden unless needed:",
        *_render_items(packet.get("forbidden_unless_needed")),
        "Compute limits:",
        *_compute_limit_lines(packet),
        "",
        "## Acceptance criteria",
        "",
        *_render_items(packet.get("acceptance_criteria")),
        "",
        "## Validation commands",
        "",
        *_render_items(packet.get("validation_commands")),
        "",
        "## Required report fields",
        "",
        *[f"- {field}" for field in REQUIRED_REPORT_FIELDS],
    ]
    return "\n".join(sections) + "\n"


__all__ = [
    "MAX_PROMPT_SECTION_ITEMS",
    "REQUIRED_REPORT_FIELDS",
    "project_handoff_prompt",
]
