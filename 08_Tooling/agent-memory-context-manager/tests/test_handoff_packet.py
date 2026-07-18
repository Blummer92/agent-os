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
        "objective": "Implement a minimal handoff packet update",
        "current_phase": "Memory H1",
        "branch": None,
        "pr_number": None,
        "changed_files": ["handoff_packet.py"],
        "allowed_inspect_first": ["README.md", "handoff_packet.py"],
        "forbidden_unless_needed": ["Workflow Scheduler source"],
        "known_facts": ["Memory Manager provides context only"],
        "prior_decisions": ["No Scheduler integration in Memory H1"],
        "acceptance_criteria": ["Pre-branch and pre-PR packets are valid"],
        "validation_commands": ["PYTHONPATH=src python -m pytest tests/test_handoff_packet.py -q"],
        "stop_conditions": ["A second module becomes necessary"],
    }


def test_packet_creation_returns_required_fields():
    packet = build_handoff_packet(**sample_packet_kwargs())

    assert isinstance(packet, dict)
    assert set(REQUIRED_PACKET_FIELDS).issubset(packet)


def test_pre_branch_and_pre_pr_values_are_preserved():
    packet = build_handoff_packet(**sample_packet_kwargs())

    assert packet["branch"] is None
    assert packet["pr_number"] is None


def test_default_compute_limits_are_copied():
    packet = build_handoff_packet(**sample_packet_kwargs())

    assert packet["compute_limits"] == DEFAULT_COMPUTE_LIMITS
    assert packet["compute_limits"] is not DEFAULT_COMPUTE_LIMITS


def test_provided_compute_limits_extend_canonical_defaults():
    kwargs = sample_packet_kwargs()
    kwargs["compute_limits"] = {
        "max_files_to_inspect": 4,
        "custom_limit": "legacy-extension",
    }

    packet = build_handoff_packet(**kwargs)

    assert packet["compute_limits"]["max_files_to_inspect"] == 4
    assert packet["compute_limits"]["targeted_tests_only"] is True
    assert packet["compute_limits"]["no_full_scheduler_suite"] is True
    assert packet["compute_limits"]["custom_limit"] == "legacy-extension"


def test_list_and_dict_inputs_are_copied():
    kwargs = sample_packet_kwargs()
    custom_compute_limits = {"max_files_to_inspect": 4}
    kwargs["compute_limits"] = custom_compute_limits

    packet = build_handoff_packet(**kwargs)
    kwargs["changed_files"].append("mutated.py")
    custom_compute_limits["max_files_to_inspect"] = 99

    assert "mutated.py" not in packet["changed_files"]
    assert packet["compute_limits"]["max_files_to_inspect"] == 4
