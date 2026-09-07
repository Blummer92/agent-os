"""Regression guards for #1944 requested classroom artifact format delivery."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_FIRST = ROOT / "01_Shared_Standards/instructional-design/artifact-first-response-standard.md"


def normalized() -> str:
    return " ".join(ARTIFACT_FIRST.read_text(encoding="utf-8").split())


def test_requested_format_is_part_of_the_artifact() -> None:
    assert "## Requested Format Is Part Of The Artifact" in ARTIFACT_FIRST.read_text(
        encoding="utf-8"
    )
    standard = normalized()
    for phrase in (
        "an artifact format such as PDF, DOCX, or PPTX",
        "successful delivery requires an artifact in that requested format",
        "A prose description, outline, page-by-page specification, or chat-only rendering"
        " does not satisfy the request merely because it contains the intended content.",
    ):
        assert phrase in standard


def test_completion_requires_production_render_verification_and_a_usable_reference() -> None:
    standard = normalized()
    for phrase in (
        "produce the requested file when production is authorized",
        "run the format's required render/verification path before delivery",
        "return a usable artifact reference or file link through the active delivery surface",
    ):
        assert phrase in standard


def test_unproduced_format_falls_back_to_blocked_production_behavior() -> None:
    standard = normalized()
    assert (
        "if any of those steps cannot be completed, use Blocked-Production Behavior and label"
        " the result as a preview or content specification rather than a completed artifact"
        in standard
    )
    assert (
        "A response must never report an explicitly requested PDF as complete when no PDF"
        " artifact was actually produced and made available to the teacher." in standard
    )


def test_required_order_and_blocked_production_behavior_remain_canonical() -> None:
    text = ARTIFACT_FIRST.read_text(encoding="utf-8")
    assert "## Required Order" in text
    assert "## Blocked-Production Behavior" in text
    assert "0.1.1" in text.split("## Version", 1)[1]
