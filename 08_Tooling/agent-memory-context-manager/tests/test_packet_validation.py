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
        current_phase="Memory 1B",
        branch="claude/agent-memory-context-manager-1b-packet-validation-helpers",
        pr_number=0,
        changed_files=[
            "08_Tooling/agent-memory-context-manager/src/agent_memory_context_manager/packet_validation.py",
        ],
        allowed_inspect_first=[
            "08_Tooling/agent-memory-context-manager/README.md",
            "08_Tooling/agent-memory-context-manager/src/agent_memory_context_manager/handoff_packet.py",
        ],
        forbidden_unless_needed=[
            "Workflow Scheduler source",
            "Executor",
            "TaskAdapter",
        ],
        known_facts=[
            "Memory 1A minimal packet generator is merged",
        ],
        prior_decisions=[
            "No Scheduler integration in Memory 1B",
        ],
        acceptance_criteria=[
            "Invalid packets return clear errors",
        ],
        validation_commands=[
            "PYTHONPATH=src python -m pytest tests/test_handoff_packet.py tests/test_packet_validation.py -q",
        ],
        stop_conditions=[
            "Need to inspect unrelated Workflow Scheduler files",
        ],
    )


def test_valid_packet_returns_no_errors():
    assert validate_handoff_packet(sample_packet()) == []


def test_is_valid_handoff_packet_returns_true_for_valid_packet():
    assert is_valid_handoff_packet(sample_packet()) is True


def test_missing_required_field_returns_clear_error():
    packet = sample_packet()
    del packet["objective"]

    errors = validate_handoff_packet(packet)

    assert "missing required field: objective" in errors


def test_non_dict_packet_returns_clear_error():
    errors = validate_handoff_packet(["not", "a", "mapping"])

    assert errors == ["packet must be a dict-like mapping"]


def test_wrong_string_field_type_returns_clear_error():
    packet = sample_packet()
    packet["objective"] = ["not a string"]

    errors = validate_handoff_packet(packet)

    assert "objective must be a string" in errors


def test_wrong_list_field_type_returns_clear_error():
    packet = sample_packet()
    packet["changed_files"] = "not a list"

    errors = validate_handoff_packet(packet)

    assert "changed_files must be a list" in errors


def test_negative_pr_number_returns_clear_error():
    packet = sample_packet()
    packet["pr_number"] = -1

    errors = validate_handoff_packet(packet)

    assert "pr_number must not be negative" in errors


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


def test_assert_valid_handoff_packet_raises_value_error_for_invalid_packet():
    packet = sample_packet()
    del packet["branch"]

    with pytest.raises(ValueError, match="Invalid handoff packet") as exc_info:
        assert_valid_handoff_packet(packet)

    assert "missing required field: branch" in str(exc_info.value)


def test_validation_does_not_mutate_packet():
    packet = sample_packet()
    original_packet = copy.deepcopy(packet)

    validate_handoff_packet(packet)

    assert packet == original_packet
