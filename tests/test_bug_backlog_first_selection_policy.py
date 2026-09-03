"""Regression guards for #1827 backlog-first bug-work selection."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_bug_work_reconciles_existing_backlog_before_fresh_discovery() -> None:
    workflow = normalized(AGENTS)
    assert "reconcile the existing discovered/open bug backlog before fresh defect discovery" in workflow
    assert "use eligible existing bugs first" in workflow
    assert "discover new bugs only when the reconciled backlog cannot satisfy the requested count" in workflow


def test_bug_work_filters_ineligible_existing_candidates() -> None:
    workflow = normalized(AGENTS)
    for state in (
        "stale",
        "duplicate",
        "already-fixed",
        "active-implementation",
        "non-repository",
        "blocked",
        "unauthorized",
    ):
        assert state in workflow


def test_bug_work_does_not_pad_requested_count_with_new_issues() -> None:
    workflow = normalized(AGENTS)
    assert "Do not create issues merely to pad a requested count." in workflow


def test_backlog_first_rule_reuses_existing_orchestrator_mission_routing() -> None:
    routing = normalized(ORCHESTRATOR)
    assert "explicitly bounded finite multi-item mission" in routing
    assert "maintain a mission cursor" in routing
    assert "Do not silently substitute, omit, or duplicate requested identities." in routing


def test_backlog_first_selection_does_not_expand_authority() -> None:
    workflow = normalized(AGENTS)
    routing = normalized(ORCHESTRATOR)
    assert "stop if authorization or source of truth is unclear" in workflow
    assert "Mission continuation never widens authority" in routing
    assert "cannot infer merge, issue closure" in routing
