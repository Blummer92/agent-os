"""Regression guards for #2886 fail-closed Notion-first source order.

Guards the "Fail-Closed Source Order" section of instructional-materials-sources.md:
current instructional evidence must reach a truthful resolution state before
downstream artifact retrieval or composition begins, and Drive must never
silently become curriculum authority.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "01_Shared_Standards/instructional-design/instructional-materials-sources.md"


def normalized() -> str:
    return " ".join(SOURCES.read_text(encoding="utf-8").split())


def test_2886_fail_closed_source_order_section_exists_and_is_current() -> None:
    text = SOURCES.read_text(encoding="utf-8")
    assert "## Fail-Closed Source Order" in text
    version_block = text.split("## Version", 1)[1]
    version = version_block.strip().splitlines()[0]
    major, minor, patch = (int(part) for part in version.split("."))
    assert (major, minor, patch) >= (0, 1, 7)


def test_2886_notion_first_requires_truthful_resolution_before_retrieval() -> None:
    standard = normalized().lower()
    for phrase in (
        '"notion first" means current instructional evidence reaches a truthful resolution state',
        "before downstream artifact retrieval or composition begins",
    ):
        assert phrase in standard, f"missing #2886 rule: {phrase}"


def test_2886_forbids_drive_inference_and_substitutes_before_verdict() -> None:
    standard = normalized().lower()
    for phrase in (
        "drive curriculum inference",
        "memory/prior-chat/library-snapshot substitution",
        "synthetic curriculum",
        "worksheet/classroom-artifact generation",
    ):
        assert phrase in standard, f"missing #2886 prohibition: {phrase}"


def test_2886_drive_cannot_silently_become_curriculum_authority() -> None:
    standard = normalized().lower()
    for phrase in (
        "never silently promote drive to curriculum authority",
        "report the actual failing layer as a source-resolution blocker",
        "governed notion fallback path",
    ):
        assert phrase in standard, f"missing #2886 fail-closed rule: {phrase}"


def test_2886_drive_preview_requires_requested_artifact_role_match() -> None:
    standard = normalized().lower()
    assert (
        "render a drive document into a preview only when it matches the requested"
        " artifact role" in standard
    )


def test_2886_provenance_separates_instructional_intent_from_drive_identity() -> None:
    standard = normalized().lower()
    assert (
        "record instructional-intent source separately from drive asset/file identity"
        in standard
    )


def test_2886_grants_no_external_write_and_introduces_no_new_registry() -> None:
    standard = normalized().lower()
    for phrase in (
        "grants no external-write authority",
        "introduces no new source registry",
    ):
        assert phrase in standard, f"missing #2886 authority boundary: {phrase}"
