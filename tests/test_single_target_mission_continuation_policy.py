"""Regression contract for #1995 single-target diagnosis continuation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
PREFLIGHT_TEST = ROOT / "tests/test_investigation_lesson_preflight_policy.py"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_single_target_historical_identity_is_routing_evidence_not_completion() -> None:
    agents = normalized(AGENTS)
    for phrase in (
        "direct single-target `Work on <number>` or `Fix <number>` mission",
        "identifier verification, diagnosis, and historical-state classification are routing evidence, not terminal outcomes",
        "merged PR, closed/completed issue, stale historical branch",
        "continue the same bounded mission through current GitHub truth",
        "Diagnosis alone is never completion",
    ):
        assert phrase in agents


def test_single_target_mission_requires_governed_terminal_disposition() -> None:
    agents = normalized(AGENTS)
    for phrase in (
        "current work completed or advanced",
        "an existing current PR resumed",
        "a current actionable successor identified and advanced",
        "current `main` proven to already satisfy the requested contract",
        "a specific authorization/governance/external-capability blocker identified",
        "manual review required after bounded escalation",
    ):
        assert phrase in agents
    for intermediate in ("`I'm checking`", "`I'm tracing`", "`likely mismatch`"):
        assert intermediate in agents


def test_historical_routing_does_not_widen_authority_or_create_new_state_model() -> None:
    agents = normalized(AGENTS)
    assert "Historical classification never reopens an issue, creates a successor, widens scope, or grants excluded-surface authority by itself" in agents
    assert "Reuse the finite-mission continuation semantics already used for bounded bug batches rather than creating another scheduler, queue, or state model" in agents
    assert "always emit the required final report for the terminal disposition" in agents


def test_single_target_continuation_reuses_1994_preflight_and_existing_orchestrator_cursor() -> None:
    agents = normalized(AGENTS)
    orchestrator = normalized(ORCHESTRATOR)
    preflight_test = normalized(PREFLIGHT_TEST)
    assert "Before forming the first substantial investigation, implementation, or repair hypothesis" in agents
    assert "Coding Lessons Learned Preflight" in agents
    assert "Final finite-mission reconciliation" in orchestrator
    assert "test_fix_1683_style_investigation_cannot_skip_initial_lesson_outcome" in preflight_test
