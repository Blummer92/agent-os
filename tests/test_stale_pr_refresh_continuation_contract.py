from pathlib import Path

AGENTS = Path("AGENTS.md").read_text(encoding="utf-8")
SAFE = Path("01_Shared_Standards/github/safe-implementation-lane.md").read_text(encoding="utf-8")


def test_stale_pr_refresh_is_not_parent_mission_completion():
    assert "branch:behind" in SAFE
    assert "separately governed branch-refresh path" in SAFE
    assert "continue" in SAFE


def test_capability_surface_miss_is_not_terminal_truth():
    assert "Absence of a same-named local tool or command is surface evidence only" in AGENTS
    assert "Navigation Alias Registry" in AGENTS


def test_subordinate_handoff_cannot_finish_parent_mission():
    assert "subordinate GitHub mutation" in AGENTS
    assert "never as parent-mission completion by itself" in AGENTS
    assert "reacquire the parent issue/PR/branch/head/CI checkpoint" in AGENTS
