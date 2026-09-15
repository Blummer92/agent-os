"""Regression for #2400: one subordinate delivery cannot terminate an unfinished finite mission."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def test_finite_mission_keeps_cursor_after_subordinate_success() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "preserve the supplied item order and maintain a mission cursor" in text
    assert "An item-local blocker does not stop independently actionable later items" in text
    assert "successful subordinate GitHub mutation" in text
    assert "intermediate evidence, not a terminal result" in text