"""Focused runtime-presentation contract regressions for AOS-RI6 (#1086)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
ORCHESTRATOR_TESTS = ROOT / "07_Agent_Tests/chatgpt-orchestrator.tests.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalized_section(path: Path, heading: str) -> str:
    text = read(path)
    marker = f"## {heading}\n"
    assert marker in text, f"missing section {heading!r} in {path}"
    body = text.split(marker, 1)[1].split("\n## ", 1)[0]
    return " ".join(body.split())


def test_runtime_rule_uses_compact_bounded_progress_without_percentages() -> None:
    ordering = normalized_section(ORCHESTRATOR, "Response Ordering Rule")
    for phrase in (
        "compact operator rendering at runtime",
        "bounded state-based progress bar",
        "`Completed:`",
        "`Current:`",
        "`Remaining:`",
        "`Blockers:`",
        "Omit the bar when no bounded canonical stage sequence exists",
        "never invent completion or percentage state",
    ):
        assert phrase in ordering


def test_common_operator_prompts_have_explicit_runtime_behavior() -> None:
    ordering = normalized_section(ORCHESTRATOR, "Response Ordering Rule")
    for phrase in (
        "`Complete handoff` and `Complete the handoff`",
        "`Next step` leads with the single supported next action",
        "`Work on #<issue>` uses the compact progress labels",
        "PR review leads with exact-head, check, and blocking-review state",
    ):
        assert phrase in ordering


def test_best_execution_and_next_are_evidence_conditional() -> None:
    ordering = normalized_section(ORCHESTRATOR, "Response Ordering Rule")
    assert "Show `Best execution:` only when current executor-route or capability evidence is material" in ordering
    assert "show `Next:` only when canonical evidence supports one concrete next action" in ordering


def test_compaction_preserves_material_handoff_evidence() -> None:
    ordering = normalized_section(ORCHESTRATOR, "Response Ordering Rule")
    for phrase in (
        "material authorization",
        "owner/source-of-truth",
        "blocker",
        "exact-head",
        "validation",
        "final-report constraints",
    ):
        assert phrase in ordering
    assert "Internal routing and audit evidence remains internal unless materially required" in ordering


def test_required_regression_fixtures_cover_ordering_and_omission() -> None:
    fixtures = read(ORCHESTRATOR_TESTS)
    for heading in (
        "Test 29 - Compact Runtime Rendering For Implementation And Handoff",
        "Test 30 - Next Step Leads With One Supported Action",
        "Test 31 - PR Review Leads With Exact-Head State",
        "Test 32 - Compact Rendering Preserves Material Stop Evidence",
        "Test 33 - Progress Bar Requires Bounded Canonical Stages",
        "Test 34 - Best Execution And Next Are Evidence-Conditional",
        "Test 35 - Classroom Presentation Contracts Remain Unchanged",
    ):
        assert f"## {heading}\n" in fixtures

    for phrase in (
        "before internal governance/routing detail",
        "repeated governance prose does not precede the action",
        "exact-head/check/blocking-review state appears first",
        "omits the progress bar rather than inventing completion",
        "`Best execution:` appears only in (a), not (b)",
        "`Next:` appears only in (c), not (d)",
    ):
        assert phrase in fixtures


def test_classroom_profiles_remain_explicitly_unchanged() -> None:
    ordering = normalized_section(ORCHESTRATOR, "Response Ordering Rule")
    assert "Classroom-material responses follow `artifact-first-response-standard.md`" in ordering
    assert "`teacher-decision-studio-standard.md`" in ordering
    assert "These domain standards refine the classroom profile and do not create a competing output schema" in ordering
