"""Regression fixture for #2067's read-only false completion."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_lineage_reconciliation_is_routing_evidence_not_implementation_completion() -> None:
    workflow = normalized(AGENTS)
    assert "identifier verification, diagnosis, and historical-state classification are routing evidence, not terminal outcomes" in workflow
    assert "Diagnosis alone is never completion." in workflow
    assert "current work completed or advanced" in workflow


def test_existing_open_pr_is_resume_target_not_reason_to_stop() -> None:
    lane = normalized(ROOT / "01_Shared_Standards/github/safe-implementation-lane.md")
    assert "existing valid issue-linked branch, Draft PR, or checkpoint lineage is normally a resume target, not a stop condition" in lane
    assert "continue from the newest valid checkpoint" in lane


def test_bounded_mission_requires_terminal_state_for_every_selected_lineage() -> None:
    routing = normalized(ORCHESTRATOR)
    assert "maintain a mission cursor until every requested item has a terminal mission state" in routing
    assert "`untouched` is intermediate only and must be zero before reporting the bounded mission complete" in routing
    assert "Do not silently substitute, omit, or duplicate requested identities." in routing
