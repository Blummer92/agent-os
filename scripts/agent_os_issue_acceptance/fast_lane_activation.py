"""Pure-local deterministic Fast-Lane terminal-authority activation (#1309-D).

Parses an operator instruction for the exact explicit terminal Fast-Lane
phrase and combines it with caller-supplied Tier/external-write evidence to
decide which `RequestedMode` ceiling (from `operating_mode.py`) the
instruction may request. This module adds no new lifecycle stage,
authorization dimension, merge/closure authority, execution path, router, or
Scheduler. `evaluate_operating_mode(...)` still walks every implementation,
Ready-for-Review, merge, and closure gate against canonical
`IssueOperationalState` evidence before anything proceeds; granting the
`RELEASE` ceiling here only lets that walk be attempted in one turn instead
of requiring a repeated user prompt at each stage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .operating_mode import RequestedMode

FAST_LANE_ACTIVATION_SCHEMA_VERSION = "1.0"

_TERMINAL_PHRASE_RE = re.compile(
    r"^work on #(?P<issue>[1-9][0-9]{0,9}) in fast lane$",
    re.IGNORECASE,
)


class FastLaneActivationReason(str, Enum):
    NO_TERMINAL_PHRASE = "fast-lane.no-terminal-phrase"
    ISSUE_MISMATCH = "fast-lane.issue-mismatch"
    TIER_INELIGIBLE = "fast-lane.tier-ineligible"
    EXTERNAL_WRITE_INELIGIBLE = "fast-lane.external-write-ineligible"
    GRANTED = "fast-lane.granted"


@dataclass(frozen=True, slots=True)
class FastLaneActivationResult:
    schema_version: str
    terminal_phrase_detected: bool
    instruction_issue_number: int | None
    granted: bool
    requested_mode_ceiling: RequestedMode
    reason: FastLaneActivationReason


def parse_fast_lane_instruction(instruction: str) -> tuple[bool, int | None]:
    """Detect the exact explicit terminal Fast-Lane phrase only.

    Returns ``(terminal_phrase_detected, issue_number)``. Ordinary
    ``work on #123``, ``continue``, ``next step``, and ``keep going`` never
    set the first element ``True``; under #1309-D they carry no terminal
    authority regardless of surrounding conversation continuity.
    """
    if not isinstance(instruction, str):
        raise TypeError("instruction must be str")
    normalized = " ".join(instruction.strip().split())
    match = _TERMINAL_PHRASE_RE.match(normalized)
    if match is None:
        return False, None
    return True, int(match.group("issue"))


def evaluate_fast_lane_terminal_activation(
    *,
    instruction: str,
    bound_issue_number: int,
    tier: int,
    external_writes: str,
) -> FastLaneActivationResult:
    """Decide the `RequestedMode` ceiling one instruction may request.

    Only the exact phrase ``work on #<issue> in fast lane``, matching the
    already-bound issue number, on a Tier 0/1 issue declaring
    ``no-external-write`` (``external_writes == "none"``), may request
    ``RequestedMode.RELEASE``. Every other input -- including a mismatched
    issue number, Tier 2, a declared external write, or an ordinary
    continuation phrase such as ``continue`` -- is capped at
    ``RequestedMode.PLANNING`` and grants no terminal authority. This
    function performs no GitHub, network, filesystem, or Scheduler I/O and
    creates no side effect.
    """
    if (
        not isinstance(bound_issue_number, int)
        or isinstance(bound_issue_number, bool)
        or bound_issue_number < 1
    ):
        raise ValueError("bound_issue_number must be a positive int")
    if not isinstance(tier, int) or isinstance(tier, bool):
        raise TypeError("tier must be int")
    if not isinstance(external_writes, str) or not external_writes.strip():
        raise ValueError("external_writes is required")

    terminal_phrase_detected, instruction_issue_number = parse_fast_lane_instruction(
        instruction
    )

    def _result(
        *,
        granted: bool,
        ceiling: RequestedMode,
        reason: FastLaneActivationReason,
    ) -> FastLaneActivationResult:
        return FastLaneActivationResult(
            schema_version=FAST_LANE_ACTIVATION_SCHEMA_VERSION,
            terminal_phrase_detected=terminal_phrase_detected,
            instruction_issue_number=instruction_issue_number,
            granted=granted,
            requested_mode_ceiling=ceiling,
            reason=reason,
        )

    if not terminal_phrase_detected:
        return _result(
            granted=False,
            ceiling=RequestedMode.PLANNING,
            reason=FastLaneActivationReason.NO_TERMINAL_PHRASE,
        )

    if instruction_issue_number != bound_issue_number:
        return _result(
            granted=False,
            ceiling=RequestedMode.PLANNING,
            reason=FastLaneActivationReason.ISSUE_MISMATCH,
        )

    if tier not in (0, 1):
        return _result(
            granted=False,
            ceiling=RequestedMode.PLANNING,
            reason=FastLaneActivationReason.TIER_INELIGIBLE,
        )

    if external_writes != "none":
        return _result(
            granted=False,
            ceiling=RequestedMode.PLANNING,
            reason=FastLaneActivationReason.EXTERNAL_WRITE_INELIGIBLE,
        )

    return _result(
        granted=True,
        ceiling=RequestedMode.RELEASE,
        reason=FastLaneActivationReason.GRANTED,
    )
