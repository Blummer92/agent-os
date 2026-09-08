"""Regression fixture for #2064's existing-bug batch cutoff."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_existing_bug_batch_must_exhaust_preexisting_backlog_before_fresh_discovery() -> None:
    workflow = normalized(AGENTS)
    assert "reconcile the existing discovered/open bug backlog before fresh defect discovery" in workflow
    assert "use eligible existing bugs first" in workflow
    assert "discover new bugs only when the reconciled backlog cannot satisfy the requested count" in workflow


def test_same_mission_issue_creation_cannot_pad_existing_bug_count() -> None:
    workflow = normalized(AGENTS)
    assert "Do not create issues merely to pad a requested count." in workflow
    assert "candidate-local terminal dispositions are non-terminal for the parent batch" in workflow
    assert "immediately advance to the next independent candidate without another user prompt" in workflow


def test_existing_primary_lineages_are_reused_and_batch_cursor_stays_live() -> None:
    routing = normalized(ORCHESTRATOR)
    assert "maintain a mission cursor until every requested item has a terminal mission state" in routing
    assert "An item-local blocker does not stop independently actionable later items." in routing
    assert "Do not silently substitute, omit, or duplicate requested identities." in routing
