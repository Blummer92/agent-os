from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = ROOT / "CHANGELOG.md"


def test_changelog_records_current_curriculum_validation_identity() -> None:
    """DEVVAL3 (#1454) requires the new identity to be recorded in the changelog."""
    text = CHANGELOG.read_text(encoding="utf-8")
    assert "#1454" in text
    assert "instructional-materials-current-curriculum-suite" in text
