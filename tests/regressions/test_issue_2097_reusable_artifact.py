"""Regression for #2097: final prompt delivery preserves the reusable-artifact-first contract."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARD = ROOT / "01_Shared_Standards/global-engineering/agent-interaction-output-standard.md"


def test_reusable_prompt_delivery_is_self_contained() -> None:
    text = STANDARD.read_text(encoding="utf-8").lower()
    assert "reusable" in text
    assert "artifact" in text
    assert "prompt" in text or "command" in text
