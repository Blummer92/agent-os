"""Regression for #2387: reusable prompt text does not imply provider execution."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def test_prompt_text_and_image_execution_are_separate_authority() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    section = text.split("## Picture Perfect / PPUX Routing", 1)[1]
    assert "Prompt derivation creates no image-provider execution authority" in section
    assert "Provider execution requires a separate explicit request" in section
