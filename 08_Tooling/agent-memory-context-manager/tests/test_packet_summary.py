import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_memory_context_manager import (  # noqa: E402
    build_handoff_packet,
    summarize_handoff_packet,
)


def sample_packet():
    return build_handoff_packet(
        objective="Summarize packets for lower-compute agent handoffs",
        current_phase="Memory 1C",
        branch="claude/agent-memory-context-manager-1c-packet-summary-helpers",
        pr_number=0,
        changed_files=[
            "file-1.py",
            "file-2.py",
            "file-3.py",
            "file-4.py",
        ],
        allowed_inspect_first=[
            "README.md",
            "handoff_packet.py",
            "packet_validation.py",
            "packet_summary.py",
        ],
        forbidden_unless_needed=[
            "Workflow Scheduler source",
            "Executor",
            "TaskAdapter",
        ],
        known_facts=[
            "Memory 1A packet generator is merged",
            "Memory 1B packet validation is merged",
            "Memory 1C summary helpers are in progress",
            "Broad scans should be avoided",
        ],
        prior_decisions=[
            "No Scheduler integration in Memory 1C",
            "No connector calls in summary helpers",
            "Keep summaries deterministic",
            "Use targeted tests only",
        ],
        acceptance_criteria=[
            "Summary returns a string",
        ],
        validation_commands=[
            "PYTHONPATH=src python -m pytest tests/test_packet_summary.py -q",
            "PYTHONPATH=src python -m pytest tests/test_handoff_packet.py tests/test_packet_validation.py tests/test_packet_summary.py -q",
            "Do not run broad repo tests",
            "Review PR changed files",
        ],
        stop_conditions=[
            "Need to inspect unrelated files",
            "Need Workflow Scheduler integration",
            "Need repo scanning",
            "Need connector calls",
        ],
    )


def test_summary_returns_string_for_valid_packet():
    summary = summarize_handoff_packet(sample_packet())

    assert isinstance(summary, str)


def test_summary_includes_objective_phase_branch_and_pr_number():
    summary = summarize_handoff_packet(sample_packet())

    assert "Objective: Summarize packets for lower-compute agent handoffs" in summary
    assert "Current phase: Memory 1C" in summary
    assert "Branch: claude/agent-memory-context-manager-1c-packet-summary-helpers" in summary
    assert "PR number: 0" in summary


def test_summary_includes_changed_files():
    summary = summarize_handoff_packet(sample_packet())

    assert "Changed files:" in summary
    assert "- file-1.py" in summary


def test_summary_respects_list_limit():
    summary = summarize_handoff_packet(sample_packet(), list_limit=2)

    assert "- file-1.py" in summary
    assert "- file-2.py" in summary
    assert "- file-3.py" not in summary


def test_summary_includes_and_more_when_list_items_are_truncated():
    summary = summarize_handoff_packet(sample_packet(), list_limit=2)

    assert "...and 2 more" in summary


def test_invalid_packet_raises_value_error():
    packet = sample_packet()
    del packet["objective"]

    with pytest.raises(ValueError, match="Invalid handoff packet"):
        summarize_handoff_packet(packet)


def test_summarization_does_not_mutate_packet():
    packet = sample_packet()
    original_packet = copy.deepcopy(packet)

    summarize_handoff_packet(packet)

    assert packet == original_packet
