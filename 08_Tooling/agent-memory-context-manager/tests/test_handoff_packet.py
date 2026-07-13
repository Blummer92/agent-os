import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_memory_context_manager import (  # noqa: E402
    DEFAULT_COMPUTE_LIMITS,
    REQUIRED_PACKET_FIELDS,
    build_handoff_packet,
)


def sample_packet_kwargs():
    return {
        "objective": "Implement Memory 1A minimal packet generator",
        "current_phase": "Memory 1A",
        "branch": "claude/agent-memory-context-manager-1a-minimal-local-packet-generator",
        "pr_number": 0,
        "changed_files": [
            "08_Tooling/agent-memory-context-manager/src/agent_memory_context_manager/handoff_packet.py",
        ],
        "allowed_inspect_first": [
            "08_Tooling/agent-memory-context-manager/README.md",
            "08_Tooling/agent-memory-context-manager/HANDOFF_PACKET_TEMPLATE.md",
        ],
        "forbidden_unless_needed": [
            "Workflow Scheduler source",
            "Executor",
            "TaskAdapter",
        ],
        "known_facts": [
            "Memory 0A-0F planning track is complete",
        ],
        "prior_decisions": [
            "No Scheduler integration in 1A",
        ],
        "acceptance_criteria": [
            "Packet generator returns a dict",
        ],
        "validation_commands": [
            "PYTHONPATH=src python -m pytest tests/test_handoff_packet.py -q",
        ],
        "stop_conditions": [
            "Need to inspect more than 8 files",
        ],
    }


def test_packet_creation_returns_dict():
    packet = build_handoff_packet(**sample_packet_kwargs())

    assert isinstance(packet, dict)


def test_all_required_fields_are_present():
    packet = build_handoff_packet(**sample_packet_kwargs())

    assert set(REQUIRED_PACKET_FIELDS).issubset(packet.keys())


def test_explicit_values_are_preserved():
    kwargs = sample_packet_kwargs()
    packet = build_handoff_packet(**kwargs)

    assert packet["objective"] == kwargs["objective"]
    assert packet["current_phase"] == "Memory 1A"
    assert packet["pr_number"] == 0
    assert packet["changed_files"] == kwargs["changed_files"]


def test_default_compute_limits_are_applied():
    packet = build_handoff_packet(**sample_packet_kwargs())

    assert packet["compute_limits"] == DEFAULT_COMPUTE_LIMITS
    assert packet["compute_limits"] is not DEFAULT_COMPUTE_LIMITS


def test_provided_compute_limits_override_defaults():
    kwargs = sample_packet_kwargs()
    kwargs["compute_limits"] = {
        "max_files_to_inspect": 4,
        "custom_limit": "allowed",
    }

    packet = build_handoff_packet(**kwargs)

    assert packet["compute_limits"]["max_files_to_inspect"] == 4
    assert packet["compute_limits"]["targeted_tests_only"] is True
    assert packet["compute_limits"]["no_full_scheduler_suite"] is True
    assert packet["compute_limits"]["custom_limit"] == "allowed"


def test_list_and_dict_inputs_are_copied():
    kwargs = sample_packet_kwargs()
    custom_compute_limits = {"max_files_to_inspect": 4}
    kwargs["compute_limits"] = custom_compute_limits

    packet = build_handoff_packet(**kwargs)

    assert packet["changed_files"] is not kwargs["changed_files"]
    assert packet["allowed_inspect_first"] is not kwargs["allowed_inspect_first"]
    assert packet["compute_limits"] is not custom_compute_limits

    kwargs["changed_files"].append("mutated.py")
    custom_compute_limits["max_files_to_inspect"] = 99

    assert "mutated.py" not in packet["changed_files"]
    assert packet["compute_limits"]["max_files_to_inspect"] == 4
