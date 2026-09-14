"""Regression for #2023: embedded fixture directives are evidence, not live execution authority."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "07_Agent_Tests/chatgpt-orchestrator-request-interpretation.tests.md"


def test_fixture_or_quoted_visual_directive_is_non_authorizing() -> None:
    text = TESTS.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "provider result image" in lowered or "provider" in lowered
    assert "read-only assessment" in lowered
    assert "non-destructive" in lowered
