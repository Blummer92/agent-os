import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_memory_context_manager import (  # noqa: E402
    build_handoff_packet,
    build_handoff_packet_cache_key,
)


def sample_packet():
    return build_handoff_packet(
        objective="Build deterministic cache keys",
        current_phase="Memory 1E",
        branch="claude/agent-memory-context-manager-1e-cache-key-helpers",
        pr_number=0,
        changed_files=["cache_key.py", "test_cache_key.py"],
        allowed_inspect_first=["cache_key.py"],
        forbidden_unless_needed=["Workflow Scheduler source"],
        known_facts=["Memory 1D summary cache helpers are merged"],
        prior_decisions=["Cache keys should use stable handoff fields"],
        acceptance_criteria=["Equivalent packets produce matching keys"],
        validation_commands=["PYTHONPATH=src python -m pytest tests/test_cache_key.py -q"],
        stop_conditions=["Need Scheduler integration"],
    )


def test_valid_packet_returns_string():
    key = build_handoff_packet_cache_key(sample_packet())

    assert isinstance(key, str)


def test_key_starts_with_default_prefix():
    key = build_handoff_packet_cache_key(sample_packet())

    assert key.startswith("handoff-summary:1.0:")


def test_same_packet_produces_same_key():
    packet = sample_packet()

    assert build_handoff_packet_cache_key(packet) == build_handoff_packet_cache_key(packet)


def test_equivalent_packet_with_reordered_compute_limit_keys_produces_same_key():
    packet = sample_packet()
    reordered_packet = copy.deepcopy(packet)
    reordered_packet["compute_limits"] = {
        key: packet["compute_limits"][key]
        for key in reversed(list(packet["compute_limits"].keys()))
    }

    assert build_handoff_packet_cache_key(packet) == build_handoff_packet_cache_key(
        reordered_packet
    )


def test_changing_objective_changes_key():
    packet = sample_packet()
    changed_packet = copy.deepcopy(packet)
    changed_packet["objective"] = "Different objective"

    assert build_handoff_packet_cache_key(packet) != build_handoff_packet_cache_key(
        changed_packet
    )


def test_changing_changed_files_changes_key():
    packet = sample_packet()
    changed_packet = copy.deepcopy(packet)
    changed_packet["changed_files"].append("another-file.py")

    assert build_handoff_packet_cache_key(packet) != build_handoff_packet_cache_key(
        changed_packet
    )


def test_invalid_packet_raises_value_error():
    packet = sample_packet()
    del packet["objective"]

    with pytest.raises(ValueError, match="Invalid handoff packet"):
        build_handoff_packet_cache_key(packet)


def test_function_does_not_mutate_packet():
    packet = sample_packet()
    original_packet = copy.deepcopy(packet)

    build_handoff_packet_cache_key(packet)

    assert packet == original_packet
