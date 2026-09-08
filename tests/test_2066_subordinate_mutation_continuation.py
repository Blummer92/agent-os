"""Regression fixture for #2066's premature post-mutation stop."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_successful_subordinate_mutation_requires_readback_and_parent_continuation() -> None:
    workflow = normalized(AGENTS)
    assert "Treat every successful subordinate GitHub mutation during an unfinished finite mission" in workflow
    assert "provisional intermediate evidence, never as parent-mission completion by itself" in workflow
    assert "Read back the canonical mutated target to prove persistence/currentness" in workflow
    assert "reacquire the parent issue/PR/branch/head/CI checkpoint" in workflow


def test_multi_target_cursor_continues_after_item_local_success() -> None:
    routing = normalized(ORCHESTRATOR)
    assert "maintain a mission cursor until every requested item has a terminal mission state" in routing
    assert "An item-local blocker does not stop independently actionable later items." in routing
    assert "`untouched` is intermediate only and must be zero before reporting the bounded mission complete" in routing


def test_process_bug_capture_does_not_replace_parent_mission() -> None:
    workflow = normalized(AGENTS)
    assert "treat bug capture as subordinate bookkeeping rather than a terminal outcome" in workflow
    assert "continue the still-authorized parent mission without requiring another user prompt" in workflow
