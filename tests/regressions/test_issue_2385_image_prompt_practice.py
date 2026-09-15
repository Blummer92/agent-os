"""Regression for #2385: prompt-writing practice must not drift to tool-operation practice."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def test_image_prompt_practice_remains_prompt_authoring() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    section = text.split("## Picture Perfect / PPUX Routing", 1)[1]
    assert "image-prompt authoring" in section
    assert "Prompt derivation creates no image-provider execution authority" in section
    assert "Generic image-generation or prompt-authoring requests" in section
    assert "normal generic path" in section
