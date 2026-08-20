from __future__ import annotations

import pytest

from scripts.agent_os_issue_acceptance.fast_lane_activation import (
    FastLaneActivationReason,
    evaluate_fast_lane_terminal_activation,
    parse_fast_lane_instruction,
)
from scripts.agent_os_issue_acceptance.operating_mode import RequestedMode


def test_exact_terminal_phrase_is_detected() -> None:
    detected, issue = parse_fast_lane_instruction("work on #123 in fast lane")
    assert detected is True
    assert issue == 123


def test_terminal_phrase_is_case_insensitive_and_whitespace_tolerant() -> None:
    detected, issue = parse_fast_lane_instruction("  Work ON  #45   IN FAST LANE  ")
    assert detected is True
    assert issue == 45


@pytest.mark.parametrize(
    "instruction",
    [
        "work on #123",
        "continue",
        "next step",
        "keep going",
        "please work on #123 in fast lane",
        "work on #123 in fast lane please",
        "work on fast lane",
    ],
)
def test_ordinary_and_near_miss_phrases_never_detected(instruction: str) -> None:
    detected, issue = parse_fast_lane_instruction(instruction)
    assert detected is False
    assert issue is None


def test_granted_for_matching_tier0_no_external_write() -> None:
    result = evaluate_fast_lane_terminal_activation(
        instruction="work on #1309 in fast lane",
        bound_issue_number=1309,
        tier=1,
        external_writes="none",
    )
    assert result.granted is True
    assert result.requested_mode_ceiling is RequestedMode.RELEASE
    assert result.reason is FastLaneActivationReason.GRANTED
    assert result.instruction_issue_number == 1309


@pytest.mark.parametrize(
    "instruction",
    ["work on #1309", "continue", "next step", "keep going"],
)
def test_ordinary_continuation_never_implies_terminal_authority(instruction: str) -> None:
    result = evaluate_fast_lane_terminal_activation(
        instruction=instruction,
        bound_issue_number=1309,
        tier=1,
        external_writes="none",
    )
    assert result.granted is False
    assert result.requested_mode_ceiling is RequestedMode.PLANNING
    assert result.reason is FastLaneActivationReason.NO_TERMINAL_PHRASE


def test_mismatched_issue_number_is_rejected() -> None:
    result = evaluate_fast_lane_terminal_activation(
        instruction="work on #42 in fast lane",
        bound_issue_number=1309,
        tier=1,
        external_writes="none",
    )
    assert result.granted is False
    assert result.reason is FastLaneActivationReason.ISSUE_MISMATCH


def test_tier_2_cannot_enter_terminal_fast_lane() -> None:
    result = evaluate_fast_lane_terminal_activation(
        instruction="work on #1309 in fast lane",
        bound_issue_number=1309,
        tier=2,
        external_writes="none",
    )
    assert result.granted is False
    assert result.requested_mode_ceiling is RequestedMode.PLANNING
    assert result.reason is FastLaneActivationReason.TIER_INELIGIBLE


def test_external_write_issue_cannot_enter_terminal_fast_lane() -> None:
    result = evaluate_fast_lane_terminal_activation(
        instruction="work on #7 in fast lane",
        bound_issue_number=7,
        tier=1,
        external_writes="notion",
    )
    assert result.granted is False
    assert result.reason is FastLaneActivationReason.EXTERNAL_WRITE_INELIGIBLE


def test_bound_issue_number_must_be_positive_int() -> None:
    with pytest.raises(ValueError):
        evaluate_fast_lane_terminal_activation(
            instruction="work on #1 in fast lane",
            bound_issue_number=0,
            tier=1,
            external_writes="none",
        )


def test_instruction_must_be_str() -> None:
    with pytest.raises(TypeError):
        parse_fast_lane_instruction(None)  # type: ignore[arg-type]
