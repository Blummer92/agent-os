from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/teacher-modeling-standards.md"
WORKFLOWS = ROOT / "01_Shared_Standards/instructional-design/teacher-modeling-workflows.md"
TEMPLATE = ROOT / "03_Templates/prompts/teacher-talk-rehearsal.md"
OVERLAY = ROOT / "02_Agent_Overlays/teacher-modeling-coach.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def all_contract_text() -> str:
    return "\n".join(read(path) for path in (STANDARD, WORKFLOWS, TEMPLATE, OVERLAY))


def test_cls8_default_rehearsal_view_orders_usable_language_before_analysis() -> None:
    content = read(STANDARD)
    ordered = (
        "Lesson goal.",
        "Immediate student task.",
        "Play-by-play model.",
        "Highest-impact improvements.",
        "Primary misconception",
        "Bounded Materials extract.",
        "Active blockers.",
    )
    positions = [content.index(value) for value in ordered]
    assert positions == sorted(positions)


def test_cls8_play_by_play_separates_each_semantic_element() -> None:
    content = read(TEMPLATE)
    assert "| Moment | Teacher says | Teacher does | Students do or notice | Check |" in content
    assert "observable evidence of student understanding or successful performance" in content


@pytest.mark.parametrize(
    "field",
    ("Problem:", "Why it matters:", "Say or do this instead:", "Expected improvement:"),
)
def test_cls8_improvement_guidance_includes_exact_replacement_move(field: str) -> None:
    assert field in read(TEMPLATE)


def test_cls8_views_share_one_underlying_modeling_record() -> None:
    content = read(STANDARD)
    for view in ("`rehearsal`", "`audit`", "`materials-extract`"):
        assert view in content
    assert "One underlying modeling record supports three presentation views" in content
    assert "views over one modeling record, not separate schemas" in read(TEMPLATE)


def test_cls8_numeric_ranges_are_defaults_not_validity_limits() -> None:
    content = all_contract_text()
    assert "Numeric ranges are defaults" in content
    assert "justified shorter or longer models are allowed" in read(STANDARD)


def test_cls8_optional_missing_artifacts_warn_or_omit() -> None:
    for path in (STANDARD, WORKFLOWS):
        content = read(path)
        assert "Optional enhancements may be omitted or returned as warnings" in content


def test_cls8_required_missing_artifacts_route_back_by_exact_name() -> None:
    content = all_contract_text()
    for phrase in (
        "set `status: BLOCKED`",
        "name the exact missing artifact",
        "route to Teacher Modeling Coach",
        "prevent silent reconstruction",
    ):
        assert phrase in content


def test_cls8_materials_extract_is_bounded_and_non_authorizing() -> None:
    content = read(TEMPLATE)
    for phrase in (
        "selected approved teacher language",
        "confirmed material-safe vocabulary references",
        "Use references plus only the excerpts needed",
        "`execution_authorized: false`",
        "Do not embed a full unit history, vocabulary map, or source document",
        "do not imply production, assessment, readiness, source-of-truth, or write authorization",
    ):
        assert phrase in content


def test_cls8_preserves_existing_rehearsal_output_shapes() -> None:
    content = read(TEMPLATE)
    for heading in (
        "### Replacement Language",
        "### Talk Track With Moves",
        "### Rehearsal Coaching",
    ):
        assert heading in content
    assert content.index("## Default Rehearsal View") < content.index("## Output Shapes")


def test_cls8_does_not_introduce_parallel_runtime_systems() -> None:
    content = all_contract_text()
    assert "Do not create a new packet, schema, cache, router, database, or service" in content
    forbidden_paths = (
        ROOT / "scripts/teacher_modeling",
        ROOT / "scripts/teacher_modeling_renderer",
        ROOT / "01_Shared_Standards/instructional-design/teacher-modeling-schema.md",
    )
    assert not any(path.exists() for path in forbidden_paths)
