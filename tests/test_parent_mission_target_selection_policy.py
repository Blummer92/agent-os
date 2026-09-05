from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def test_active_pr_cleanup_wins_over_ambiguous_backlog_shorthand() -> None:
    assert "Resolve ambiguous shorthand against the active unfinished parent mission" in AGENTS
    assert "active mission is current-PR cleanup or repair" in AGENTS
    assert "rank and reacquire that current PR queue before considering unrelated backlog issues" in AGENTS


def test_explicit_backlog_request_still_selects_backlog() -> None:
    assert "explicit requests to work or discover the issue backlog still select the backlog normally" in AGENTS


def test_process_bug_capture_still_continues_parent_mission() -> None:
    assert "treat bug capture as subordinate bookkeeping rather than a terminal outcome" in AGENTS
    assert "reacquire the parent issue/PR/branch/head checkpoint" in AGENTS
