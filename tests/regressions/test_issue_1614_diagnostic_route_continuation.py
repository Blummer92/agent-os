"""Regression for #1614: one insufficient diagnostic route does not force a false owner handoff."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def test_diagnostic_route_failure_requires_bounded_alternative_search() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "boundedly inspect another known or discoverable" in text
    assert "Do not retry the same unsupported route indefinitely" in text
    assert "must not be used as a manual copy/paste transport" in text
