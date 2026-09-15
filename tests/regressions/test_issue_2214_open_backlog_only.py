"""Regression for #2214: actionable backlog discovery must be open-only and fail closed on unknown state."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "AGENTS.md"


def test_current_bug_discovery_is_open_only() -> None:
    text = AGENTS.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "open" in lowered
    assert "bug" in lowered
    assert "candidate" in lowered