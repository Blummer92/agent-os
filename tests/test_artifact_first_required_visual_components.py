"""Regression guards for #1945 required classroom visual components."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_FIRST = ROOT / "01_Shared_Standards/instructional-design/artifact-first-response-standard.md"


def normalized() -> str:
    return " ".join(ARTIFACT_FIRST.read_text(encoding="utf-8").split())


def test_required_visual_slots_are_part_of_completion() -> None:
    standard = normalized()
    assert "## Required Visual Components" in ARTIFACT_FIRST.read_text(encoding="utf-8")
    for phrase in (
        "images, icons, diagrams, or other visual support",
        "part of completion rather than optional polish",
        "every required visual slot is either populated by an approved visual path"
        " or explicitly reported as blocked",
    ):
        assert phrase in standard


def test_unavailable_visual_asset_sync_never_authorizes_silent_removal() -> None:
    standard = normalized()
    for phrase in (
        "If a connected visual-asset source such as Visual Asset Sync is unavailable or"
        " not authorized, do not interpret that absence as permission to silently remove"
        " required visuals.",
        "Use an approved non-connected/generated/local fallback when current policy permits it.",
        "label the artifact as incomplete/preview, identify the visual-assets blocker, and do"
        " not claim classroom-ready completion",
    ):
        assert phrase in standard


def test_render_qa_covers_visual_presence_and_zero_visual_artifacts_fail_closed() -> None:
    standard = normalized()
    assert (
        "Render QA for a visually required artifact must verify both layout integrity and"
        " presence of the required visual components." in standard
    )
    assert (
        "A file whose required visual slots resolve to zero images/icons cannot receive a"
        " complete/classroom-ready claim." in standard
    )


def test_required_order_and_blocked_production_behavior_remain_canonical() -> None:
    text = ARTIFACT_FIRST.read_text(encoding="utf-8")
    assert "## Required Order" in text
    assert "## Blocked-Production Behavior" in text
    assert "0.1.1" in text.split("## Version", 1)[1]
