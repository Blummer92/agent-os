from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def test_discovered_process_bug_is_subordinate_not_terminal():
    assert "process/tooling bug is discovered and logged" in AGENTS
    assert "bug capture as subordinate bookkeeping rather than a terminal outcome" in AGENTS
    assert "reacquire the parent issue/PR/branch/head checkpoint" in AGENTS


def test_candidate_local_dispositions_continue_finite_bug_cursor():
    assert "Bind each candidate disposition to the existing finite-mission cursor" in AGENTS
    assert "candidate-local terminal dispositions are non-terminal for the parent batch" in AGENTS
    assert "immediately advance to the next independent open candidate" in AGENTS


def test_finite_bug_work_cannot_pad_or_fall_back_to_closed_issues():
    assert "report the honest shortfall" in AGENTS
    assert "creating issues merely to pad the count" in AGENTS
    assert "Newly discovered or newly created bugs do not count toward a user-requested existing-backlog implementation count" in AGENTS
    assert "Never fall back to closed issues as replacement candidates" in AGENTS
