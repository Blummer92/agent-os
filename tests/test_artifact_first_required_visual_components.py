"""Regression guards for #1945 and #2334 required classroom visual components."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_FIRST = ROOT / "01_Shared_Standards/instructional-design/artifact-first-response-standard.md"
ASSET_PICKER = ROOT / "01_Shared_Standards/instructional-design/visual-asset-picker-standard.md"


def normalized(path: Path = ARTIFACT_FIRST) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


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


def test_issue_2334_reuse_precedes_synthetic_fallback() -> None:
    standard = normalized()
    picker = normalized(ASSET_PICKER)
    for phrase in (
        "must run reuse-first resolution before any synthetic fallback",
        "Check usable authorized conversation/project files and supplied export material first",
        "Do not skip those sources merely because a renderer can create a plausible substitute more quickly.",
    ):
        assert phrase in standard
    assert "reuse-first discovery is a required pre-production step rather than optional enrichment" in picker
    assert "check already-authorized conversation/project files and supplied export material" in picker


def test_issue_2334_metadata_only_asset_evidence_is_not_artifact_fulfillment() -> None:
    standard = normalized()
    picker = normalized(ASSET_PICKER)
    assert "Asset metadata is not artifact fulfillment." in standard
    assert (
        "An asset ID, eligible-asset ID, selection decision, or successful metadata read does not prove"
        " that image bytes or another usable source reference were recovered, materialized, embedded, or placed."
        in standard
    )
    assert "metadata-only result that reports an asset ID or eligible asset ID proves discovery/eligibility only" in picker
    assert "distinguish `discovered`, `selected`, `materialized`, and `placed` evidence" in picker


def test_issue_2334_known_eligible_asset_recovery_failure_blocks_instead_of_substituting() -> None:
    standard = normalized()
    picker = normalized(ASSET_PICKER)
    for phrase in (
        "cannot recover/materialize that exact asset, report the artifact as incomplete/preview",
        "Do not convert the recovery failure into permission to omit the visual, draw a placeholder, invent a lookalike, or silently generate a replacement.",
        "Synthetic fallback is eligible only when governed discovery proves no eligible reusable asset is available",
    ):
        assert phrase in standard
    assert "return an explicit unresolved-materialization result" in picker
    assert "Retrieval, materialization, placement, or connector failure is not such proof." in picker


def test_required_order_and_blocked_production_behavior_remain_canonical() -> None:
    text = ARTIFACT_FIRST.read_text(encoding="utf-8")
    assert "## Required Order" in text
    assert "## Requested Format Is Part Of The Artifact" in text
    assert "## Blocked-Production Behavior" in text
    assert "0.1.3" in text.split("## Version", 1)[1]
