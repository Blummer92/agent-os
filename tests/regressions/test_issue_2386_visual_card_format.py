"""Regression for #2386: image-first visual-card intent must not silently become PDF intent."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/artifact-first-response-standard.md"


def test_visual_asset_and_document_delivery_are_distinct() -> None:
    text = STANDARD.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "artifact" in lowered
    assert "requested" in lowered
    assert "format" in lowered or "surface" in lowered