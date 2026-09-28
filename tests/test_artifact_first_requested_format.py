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
    assert "## Required Visual Components" in text
    assert "## Blocked-Production Behavior" in text
    version_block = text.split("## Version", 1)[1]\n    version = version_block.strip().splitlines()[0]\n    major, minor, patch = (int(part) for part in version.split("."))\n    assert (major, minor, patch) >= (0, 1, 4)


def test_2896_content_first_visual_planning_order_is_explicit() -> None:
    text = normalized().lower()
    assert "Content-First Visual Planning For Worksheets" in ARTIFACT_FIRST.read_text(encoding="utf-8")
    assert "student-facing content first and visual selection second" in text
    assert "proposed / needs confirmation" in text
    assert "needed, optional, or unnecessary" in text
    assert "curriculum/learning-target alignment" in text
    assert "decorative availability alone is not instructional justification" in text


def test_2896_content_first_rule_does_not_widen_external_write_authority() -> None:
    text = normalized().lower()
    assert "this sequencing does not change classroom artifact destinations" in text
    assert "authorize drive, notion, publication, or other external writes" in text


def test_2885_requested_artifact_role_survives_candidate_selection() -> None:
    text = normalized().lower()
    for phrase in (
        "requested artifact role is authoritative",
        "student worksheet or worksheet preview",
        "teacher-modeling package",
        "generated illustration",
        "game/activity board",
        "candidate title similarity also does not override the resolved artifact role",
        "verify that its artifact role matches the resolved request",
    ):
        assert phrase in text


def test_2885_look_like_and_with_images_do_not_imply_image_generation() -> None:
    text = normalized().lower()
    assert "look like" in text
    assert "with images" in text
    assert "do not independently change a worksheet request into image generation" in text


def test_2885_mismatch_fails_to_worksheet_specific_preview_or_blocker() -> None:
    text = normalized().lower()
    assert "worksheet-specific blocker" in text
    assert "clearly labeled worksheet preview/content specification" in text
    assert "rather than substituting another artifact role" in text


def test_2885_role_rule_does_not_duplicate_source_order_or_widen_authority() -> None:
    text = normalized().lower()
    assert "downstream of the existing source-order contract" in text
    assert "does not replace or duplicate the notion-first / drive-second retrieval rule" in text
    assert "grants no external-write authority" in text
