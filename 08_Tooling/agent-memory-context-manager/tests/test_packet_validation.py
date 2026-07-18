import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_memory_context_manager import (  # noqa: E402
    assert_valid_handoff_packet,
    build_handoff_packet,
    is_valid_handoff_packet,
    validate_handoff_packet,
)


def sample_packet():
    return build_handoff_packet(
        objective="Validate handoff packets before agent use",
        current_phase="Memory H1",
        branch=None,
        pr_number=None,
        changed_files=["packet_validation.py"],
        allowed_inspect_first=["README.md", "handoff_packet.py"],
        forbidden_unless_needed=["Workflow Scheduler source"],
        known_facts=["Memory Manager provides context only"],
        prior_decisions=["No Scheduler integration in Memory H1"],
        acceptance_criteria=["Invalid packets return clear errors"],
        validation_commands=["PYTHONPATH=src python -m pytest tests/test_packet_validation.py -q"],
        stop_conditions=["A second module becomes necessary"],
    )


def test_pre_branch_and_pre_pr_packet_is_valid():
    assert validate_handoff_packet(sample_packet()) == []
    assert is_valid_handoff_packet(sample_packet()) is True


def test_non_empty_branch_and_positive_pr_are_valid():
    packet = sample_packet()
    packet["branch"] = "memory-h1-schema-alignment"
    packet["pr_number"] = 272

    assert validate_handoff_packet(packet) == []


def test_legacy_zero_pr_number_remains_valid():
    packet = sample_packet()
    packet["pr_number"] = 0

    assert validate_handoff_packet(packet) == []


def test_empty_branch_is_rejected():
    packet = sample_packet()
    packet["branch"] = "  "

    assert "branch must be a non-empty string or None" in validate_handoff_packet(packet)


def test_non_string_branch_is_rejected():
    packet = sample_packet()
    packet["branch"] = 10

    assert "branch must be a string or None" in validate_handoff_packet(packet)


def test_negative_pr_number_is_rejected():
    packet = sample_packet()
    packet["pr_number"] = -1

    assert "pr_number must not be negative" in validate_handoff_packet(packet)


def test_non_integer_pr_number_is_rejected():
    packet = sample_packet()
    packet["pr_number"] = "12"

    assert "pr_number must be an integer or None" in validate_handoff_packet(packet)


def test_invalid_compute_limits_return_clear_errors():
    packet = sample_packet()
    packet["compute_limits"] = {
        "max_files_to_inspect": 0,
        "targeted_tests_only": "yes",
        "no_full_scheduler_suite": "yes",
    }

    errors = validate_handoff_packet(packet)

    assert "compute_limits.max_files_to_inspect must be positive" in errors
    assert "compute_limits.targeted_tests_only must be a boolean" in errors
    assert "compute_limits.no_full_scheduler_suite must be a boolean" in errors


def test_assert_valid_handoff_packet_raises_for_invalid_packet():
    packet = sample_packet()
    del packet["branch"]

    with pytest.raises(ValueError, match="missing required field: branch"):
        assert_valid_handoff_packet(packet)


def test_validation_does_not_mutate_packet():
    packet = sample_packet()
    original_packet = copy.deepcopy(packet)

    validate_handoff_packet(packet)

    assert packet == original_packet
