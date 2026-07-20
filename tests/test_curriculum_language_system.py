from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ID = ROOT / "01_Shared_Standards/instructional-design"
CLS2 = ID / "unit-vocabulary-map-standard.md"
CLS4 = ID / "lesson-vocabulary-planner-response-standard.md"
STUDENT = ID / "student-language-standard.md"
SLIDES = ID / "slide-deck-defaults.md"
WORKFLOWS = ID / "instructional-materials-workflows.md"
RUBRIC = ID / "material-quality-rubric.md"
OVERLAYS = (
    ROOT / "02_Agent_Overlays/unit-alignment-agent.md",
    ROOT / "02_Agent_Overlays/teacher-modeling-coach.md",
    ROOT / "02_Agent_Overlays/instructional-materials-coach.md",
)
CLS2_REF = "01_Shared_Standards/instructional-design/unit-vocabulary-map-standard.md"
CLS4_REF = "01_Shared_Standards/instructional-design/lesson-vocabulary-planner-response-standard.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def assert_values(path: Path, values: tuple[str, ...]) -> None:
    content = read(path)
    for value in values:
        assert value in content, f"{path.name} missing: {value}"


def test_cls2_contract() -> None:
    assert_values(
        CLS2,
        (
            "Review Vocabulary",
            "Teach Vocabulary",
            "Introduce, Don’t Assess Yet",
            "Transfer Vocabulary",
            "Future Vocabulary",
            "Teacher Language Use",
            "Student Language Use",
            "Slide/Worksheet Safe?",
            "Assess This Unit?",
        ),
    )


def test_cls4_contract() -> None:
    assert_values(
        CLS4,
        (
            "Vocabulary Snapshot",
            "Vocabulary Planner Table",
            "Difficulty by Student Group",
            "Assessment Vocabulary",
            "Teach & Use Today",
            "Future Unit Vocabulary",
            "Exact Source Page",
            "Evidence Class",
            "Confirmation State",
            "Instruction or Practice Evidence",
            "Teacher-appropriate does not imply student-facing",
            "material-safe does not imply assessable",
            "canonically `Split` with human review required",
        ),
    )
    assert len(read(CLS4).splitlines()) < 100


def test_overlays_inherit_cls2_and_cls4_once() -> None:
    for overlay in OVERLAYS:
        content = read(overlay)
        assert content.count(CLS2_REF) == 1
        assert content.count(CLS4_REF) == 1


def test_cls5_preserves_vocabulary_decisions() -> None:
    assert_values(
        STUDENT,
        (
            "unit-vocabulary-map-standard.md",
            "lesson-vocabulary-planner-response-standard.md",
            "source location",
            "evidence class",
            "confirmation state",
            "CLS2 category",
            "CLS4 category",
            "practice evidence",
            "teacher language, student language, material safety, and assessment",
            "approved Google Drive destinations, not GitHub storage",
        ),
    )
    assert_values(
        SLIDES,
        (
            "Vocabulary Gate",
            "Slide/Worksheet Safe? = Yes",
            "Slide appearance does not make a term assessable",
        ),
    )
    assert_values(
        WORKFLOWS,
        (
            "Vocabulary Integration Gate",
            "Slide/Worksheet Safe? = Yes",
            "exposure or appearance in material is insufficient",
        ),
    )
    assert_values(
        RUBRIC,
        (
            "Vocabulary integration",
            "assesses only after explicit instruction or practice",
        ),
    )


def test_cls5_docs_are_bounded() -> None:
    for path in (STUDENT, SLIDES, WORKFLOWS, RUBRIC):
        assert len(read(path).splitlines()) < 100


def test_no_parallel_curriculum_hierarchy_exists() -> None:
    assert not (ROOT / "01_Shared_Standards/curriculum").exists()
    assert not (ROOT / "02_Agent_Overlays/curriculum").exists()
