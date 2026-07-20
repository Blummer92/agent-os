from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/unit-vocabulary-map-standard.md"
OVERLAYS = (
    ROOT / "02_Agent_Overlays/unit-alignment-agent.md",
    ROOT / "02_Agent_Overlays/teacher-modeling-coach.md",
    ROOT / "02_Agent_Overlays/instructional-materials-coach.md",
)
STANDARD_REF = "01_Shared_Standards/instructional-design/unit-vocabulary-map-standard.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_unit_vocabulary_map_contract_is_complete() -> None:
    content = read(STANDARD)
    required_categories = (
        "Review Vocabulary",
        "Teach Vocabulary",
        "Introduce, Don’t Assess Yet",
        "Transfer Vocabulary",
        "Future Vocabulary",
    )
    required_fields = (
        "Word",
        "Category",
        "Unit",
        "Prior Unit Connection",
        "Student-Friendly Meaning",
        "Teacher Language Use",
        "Student Language Use",
        "Slide/Worksheet Safe?",
        "Assess This Unit?",
        "Notes",
    )

    for value in (*required_categories, *required_fields):
        assert value in content, f"missing CLS2 contract value: {value}"


def test_required_overlays_inherit_the_standard_once() -> None:
    for overlay in OVERLAYS:
        content = read(overlay)
        assert content.count(STANDARD_REF) == 1, (
            f"{overlay.name} must inherit the CLS2 standard exactly once"
        )


def test_standard_fails_closed_on_missing_evidence_and_early_assessment() -> None:
    content = read(STANDARD)
    required_safety_phrases = (
        "never silently invented",
        "Needs source confirmation",
        "return `needs-decision`",
        "after explicit instruction or practice",
        "Block assessment when instruction or practice evidence is missing",
    )

    for phrase in required_safety_phrases:
        assert phrase in content, f"missing CLS2 safety rule: {phrase}"


def test_no_parallel_curriculum_hierarchy_exists() -> None:
    assert not (ROOT / "01_Shared_Standards/curriculum").exists()
    assert not (ROOT / "02_Agent_Overlays/curriculum").exists()
