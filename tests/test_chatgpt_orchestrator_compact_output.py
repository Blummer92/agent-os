"""Focused runtime-presentation contract regressions for AOS-RI6 (#1086)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
CANONICAL = ROOT / "01_Shared_Standards/global-engineering/agent-interaction-output-standard.md"
DETAILS = ROOT / "07_Agent_Tests/chatgpt-orchestrator-tests-details.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(path: Path, heading: str) -> str:
    text = read(path)
    marker = f"## {heading}\n"
    assert marker in text, f"missing section {heading!r} in {path}"
    return " ".join(text.split(marker, 1)[1].split("\n## ", 1)[0].split())


def test_shared_standard_owns_compact_rendering_semantics() -> None:
    compact = section(CANONICAL, "Compact Operator Rendering")
    for phrase in (
        "`Completed`", "`Current`", "`Remaining`", "`Blockers`",
        "state-based progress bar", "omit the bar when no bounded sequence exists",
        "`Best execution` only when", "one `Next` action only when",
        "smallest reusable context packet", "Compact rendering never hides",
    ):
        assert phrase in compact


def test_orchestrator_maps_common_prompts_without_redefining_shared_rules() -> None:
    ordering = section(ORCHESTRATOR, "Response Ordering Rule")
    assert "compact operator rendering at runtime" in ordering
    for phrase in (
        "`Complete handoff` and `Complete the handoff`",
        "`Next step` leads with the single supported next action",
        "`Work on #<issue>` selects the issue-implementation profile",
        "PR review leads with exact-head, check, and blocking-review state",
    ):
        assert phrase in ordering
    assert "bounded state-based progress bar" not in ordering
    assert "Show `Best execution:`" not in ordering
    assert "smallest reusable packet" not in ordering


def test_required_fixtures_cover_ordering_omission_and_stop_evidence() -> None:
    fixtures = read(DETAILS)
    for heading in (
        "Test 29 - Compact Runtime Rendering For Implementation And Handoff",
        "Test 30 - Next Step Leads With One Supported Action",
        "Test 31 - PR Review Leads With Exact-Head State",
        "Test 32 - Compact Rendering Preserves Material Stop Evidence",
        "Test 33 - Progress Bar Requires a Bounded Canonical Stage Sequence",
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
        "controlling blocker and exact unblock condition first",
    ):
        assert phrase in fixtures


def test_classroom_profiles_remain_explicitly_unchanged() -> None:
    ordering = section(ORCHESTRATOR, "Response Ordering Rule")
    assert "Classroom-material responses follow `artifact-first-response-standard.md`" in ordering
    assert "`teacher-decision-studio-standard.md`" in ordering
    assert "do not create a competing output schema" in ordering
