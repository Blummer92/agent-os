"""Regression for #2389: Tutorial 0 prompt shorthand stays on the resolved Picture Perfect mission."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def test_tutorial_zero_image_prompt_shorthand_routes_to_ppux() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    section = text.split("## Picture Perfect / PPUX Routing", 1)[1]
    assert "Tutorial 0 image prompts" in section
    assert "existing Picture Perfect package" in section
    assert "before any generic image-prompt authoring" in text
    assert "Unknown or ambiguous tutorials do not produce fabricated PPUX output" in section
