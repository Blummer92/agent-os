from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLS2_STANDARD = (
    ROOT / "01_Shared_Standards/instructional-design/unit-vocabulary-map-standard.md"
)
CLS4_STANDARD = ROOT / (
    "01_Shared_Standards/instructional-design/"
    "lesson-vocabulary-planner-response-standard.md"
)
OVERLAYS = (
    ROOT / "02_Agent_Overlays/unit-alignment-agent.md",
    ROOT / "02_Agent_Overlays/teacher-modeling-coach.md",
    ROOT / "02_Agent_Overlays/instructional-materials-coach.md",
)
CLS2_REF = "01_Shared_Standards/instructional-design/unit-vocabulary-map-standard.md"
CLS4_REF = (
    "01_Shared_Standards/instructional-design/"
    "lesson-vocabulary-planner-response-standard.md"
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_unit_vocabulary_map_contract_is_complete() -> None:
    content = read(CLS2_STANDARD)
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


def test_lesson_vocabulary_planner_contract_is_complete() -> None:
    content = read(CLS4_STANDARD)
    required_sections = (
        "Vocabulary Snapshot",
        "Vocabulary Planner Table",
        "Difficulty by Student Group",
        "Issue and Fix",
        "Assessment Vocabulary",
        "Recommendation",
        "Next Action",
    )
    required_categories = (
        "Teach & Use Today",
        "Introduce, Don’t Assess Yet",
        "Future Unit Vocabulary",
    )
    learner_groups = (
        "lowest-performing students",
        "on-grade-level students",
        "advanced students",
    )
    evidence_classes = (
        "`explicit`",
        "`partial`",
        "`inferred`",
        "`missing`",
        "`unavailable`",
    )
    required_fields = (
        "Word",
        "Lesson Category",
        "CLS2 Unit Category",
        "Exact Source Page",
        "Exact Source Section or Property",
        "Evidence Class",
        "Confirmation State",
        "Prior Unit Connection",
        "Student-Friendly Meaning",
        "Teacher Language Use",
        "Student Language Use",
        "Slide/Worksheet Safe?",
        "Assess Today?",
        "Instruction or Practice Evidence",
        "Notes",
    )

    for value in (
        *required_sections,
        *required_categories,
        *learner_groups,
        *evidence_classes,
        *required_fields,
    ):
        assert value in content, f"missing CLS4 contract value: {value}"


def test_required_overlays_inherit_both_vocabulary_standards_once() -> None:
    for overlay in OVERLAYS:
        content = read(overlay)
        assert content.count(CLS2_REF) == 1, (
            f"{overlay.name} must inherit the CLS2 standard exactly once"
        )
        assert content.count(CLS4_REF) == 1, (
            f"{overlay.name} must inherit the CLS4 standard exactly once"
        )


def test_cls4_source_order_and_fail_closed_rules_are_explicit() -> None:
    content = read(CLS4_STANDARD)
    ordered_phrases = (
        "approved CLS2 Unit Vocabulary Map",
        "canonical unit registry record",
        "`Source of Truth` pointer",
        "explicit unit vocabulary tables",
        "approved lesson evidence",
        "Classify evidence",
        "Check instruction or practice evidence",
    )
    positions = [content.index(phrase) for phrase in ordered_phrases]
    assert positions == sorted(positions), "CLS4 source-reading order must stay explicit"

    required_safety_phrases = (
        "return `needs-decision`",
        "Conflicting evidence also returns `needs-decision`",
        "partial evidence that requires confirmation",
        "canonically `Split` with human review required",
        "do not create a vocabulary plan from its broad legacy map",
        "requires explicit instruction or explicit guided or independent practice",
        "Do not diagnose an individual without approved evidence",
    )
    for phrase in required_safety_phrases:
        assert phrase in content, f"missing CLS4 safety rule: {phrase}"


def test_cls4_keeps_language_material_and_assessment_decisions_separate() -> None:
    content = read(CLS4_STANDARD)
    required_boundaries = (
        "Decide Teacher Language Use, Student Language Use, Slide/Worksheet Safe?, and",
        "Assess Today? independently",
        "Teacher-appropriate does not imply student-facing",
        "student-facing does not imply",
        "material-safe does not imply assessable",
        "No role may bypass assessment eligibility or destination rules",
    )
    for phrase in required_boundaries:
        assert phrase in content, f"missing CLS4 decision boundary: {phrase}"


def test_cls4_defines_snapshot_and_assessment_outputs() -> None:
    content = read(CLS4_STANDARD)
    for phrase in (
        "`Vocabulary Snapshot`: summarize category counts and unresolved evidence",
        "`Assessment Vocabulary`: list only `Assess Today? = Yes` rows",
        "with practice evidence, or `None`",
    ):
        assert phrase in content, f"missing CLS4 output rule: {phrase}"


def test_cls4_is_concise_and_does_not_authorize_external_writes() -> None:
    content = read(CLS4_STANDARD)
    assert len(content.splitlines()) < 100
    for phrase in (
        "Do not write to Notion or Drive",
        "generate classroom artifacts",
        "store student-facing materials in GitHub",
        "call live connectors",
        "use credentials",
        "mutate an external system",
    ):
        assert phrase in content, f"missing CLS4 write boundary: {phrase}"


def test_no_parallel_curriculum_hierarchy_exists() -> None:
    assert not (ROOT / "01_Shared_Standards/curriculum").exists()
    assert not (ROOT / "02_Agent_Overlays/curriculum").exists()
