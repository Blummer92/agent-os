"""Regression coverage for the bounded handoff-prompt projection path (#2749).

A handoff-prompt request over an existing mission checkpoint must not restart
the parent investigation: projection reuses already-established state and fails
closed on an unestablished checkpoint instead of re-auditing.
"""
from copy import deepcopy

import pytest

from agent_memory_context_manager import (
    MAX_PROMPT_SECTION_ITEMS,
    REQUIRED_REPORT_FIELDS,
    build_handoff_packet,
    project_handoff_prompt,
)


def sample_packet(**overrides):
    kwargs = {
        "objective": "Finish the open-bug audit handoff",
        "current_phase": "audit-checkpoint-3",
        "branch": "agent/2749-handoff-projection",
        "pr_number": None,
        "changed_files": ["handoff_prompt.py"],
        "allowed_inspect_first": ["handoff_packet.py", "packet_validation.py"],
        "forbidden_unless_needed": ["Workflow Scheduler source"],
        "known_facts": ["Checkpoint 3 findings are recorded", "Blocker B-7 is open"],
        "prior_decisions": ["No scheduler changes for this fix"],
        "acceptance_criteria": ["Prompt generation does not re-run the audit"],
        "validation_commands": ["PYTHONPATH=src python -m pytest tests/test_handoff_prompt.py -q"],
        "stop_conditions": ["Blocker B-7 unresolved"],
    }
    kwargs.update(overrides)
    return build_handoff_packet(**kwargs)


def test_projection_contains_checkpoint_findings_lineage_blockers_and_next_action():
    prompt = project_handoff_prompt(sample_packet())

    assert "Finish the open-bug audit handoff" in prompt
    assert "audit-checkpoint-3" in prompt
    assert "agent/2749-handoff-projection" in prompt
    assert "Checkpoint 3 findings are recorded" in prompt
    assert "No scheduler changes for this fix" in prompt
    assert "Blocker B-7 unresolved" in prompt
    assert "Inspect next: handoff_packet.py" in prompt


def test_projection_states_that_no_reaudit_was_performed():
    prompt = project_handoff_prompt(sample_packet())

    assert "No re-audit" in prompt
    assert "reused exactly as" in prompt or "reused, not re-audited" in prompt


def test_projection_lists_required_report_fields():
    prompt = project_handoff_prompt(sample_packet())

    for field in REQUIRED_REPORT_FIELDS:
        assert field in prompt


def test_explicit_next_action_wins_over_allowed_inspect_first():
    packet = sample_packet()
    packet["next_action"] = "Resolve blocker B-7, then re-run the audit gate"

    prompt = project_handoff_prompt(packet)

    assert "Resolve blocker B-7, then re-run the audit gate" in prompt


def test_generate_prompt_performs_no_io_and_does_not_execute_the_mission(monkeypatch):
    # Distinguishes "generate handoff prompt for mission" from
    # "execute/resume mission": if projection ever reaches for the network,
    # a subprocess, or the filesystem, this fails instead of re-auditing.
    def _boom(*args, **kwargs):
        raise AssertionError("projection must not perform I/O")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    monkeypatch.setattr("subprocess.run", _boom)
    monkeypatch.setattr("subprocess.Popen", _boom)
    monkeypatch.setattr("os.system", _boom)

    prompt = project_handoff_prompt(sample_packet())

    assert "Finish the open-bug audit handoff" in prompt


def test_projection_fails_closed_on_unestablished_checkpoint():
    packet = sample_packet()
    del packet["known_facts"]

    with pytest.raises(ValueError, match="Invalid handoff packet"):
        project_handoff_prompt(packet)


def test_projection_fails_closed_on_malformed_next_action():
    packet = sample_packet()
    packet["next_action"] = "   "

    with pytest.raises(ValueError, match="next_action"):
        project_handoff_prompt(packet)


def test_projection_is_bounded_independently_of_audit_size():
    packet = sample_packet(
        known_facts=[f"finding-{index}" for index in range(200)],
    )

    prompt = project_handoff_prompt(packet)

    assert "finding-0" in prompt
    assert f"finding-{MAX_PROMPT_SECTION_ITEMS - 1}" in prompt
    assert f"finding-{MAX_PROMPT_SECTION_ITEMS}" not in prompt
    assert f"(+{200 - MAX_PROMPT_SECTION_ITEMS} more recorded in the checkpoint)" in prompt


def test_projection_is_a_pure_function_of_the_packet():
    packet = sample_packet()
    before = deepcopy(packet)

    first = project_handoff_prompt(packet)
    second = project_handoff_prompt(packet)

    assert first == second
    assert packet == before


def test_pre_branch_and_pre_pr_checkpoints_render_explicitly():
    prompt = project_handoff_prompt(sample_packet(branch=None, pr_number=None))

    assert "none (pre-branch)" in prompt
    assert "none (pre-PR)" in prompt
