"""Regression contract for #1994 initial/investigation Lessons Learned preflight."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_agents_requires_lesson_preflight_before_first_substantial_hypothesis() -> None:
    agents = normalized(AGENTS)
    for phrase in (
        "Before forming the first substantial investigation, implementation, or repair hypothesis",
        "Coding Lessons Learned Preflight",
        "smallest current `CodingKnowledgeRequest`",
        "Record the bounded CKR6 outcome",
        "investigation-only work does not bypass this entry condition",
    ):
        assert phrase in agents


def test_investigation_preflight_has_bounded_not_needed_and_reentry_behavior() -> None:
    agents = normalized(AGENTS)
    for phrase in (
        "`not-needed`",
        "unavailable-safe-fallback",
        "Reuse that preflight while the mission signals remain materially unchanged",
        "materially changes those signals, re-evaluate the existing preflight",
        "do not repeat broad retrieval after every read-only lookup",
    ):
        assert phrase in agents


def test_initial_preflight_preserves_authority_and_does_not_replace_failed_repair_gate() -> None:
    agents = normalized(AGENTS)
    orchestrator = normalized(ORCHESTRATOR)
    assert "GitHub remains authoritative and selected lessons remain advisory-only" in agents
    assert "this initial/investigation preflight never substitutes for #1988 failed-repair re-entry" in agents
    assert "## Coding Lessons Learned Preflight" in orchestrator
    assert "Call `plan_lesson_preflight(...)` first" in orchestrator
    assert "If it returns `retrieval_required=false`, perform zero Lessons Learned lookup" in orchestrator
    assert "orchestrate_lesson_activation(...)" in orchestrator


def test_fix_1683_style_investigation_cannot_skip_initial_lesson_outcome() -> None:
    agents = normalized(AGENTS)
    preflight = agents.index("Before forming the first substantial investigation, implementation, or repair hypothesis")
    target_resolution = agents.index("Resolve ambiguous shorthand against the active unfinished parent mission")
    assert preflight < target_resolution
