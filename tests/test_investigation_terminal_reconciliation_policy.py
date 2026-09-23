from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/global-engineering/investigation-terminal-reconciliation.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def test_terminal_classifications_are_finite_and_untouched_is_nonterminal():
    text = STANDARD.read_text()
    for state in (
        "resolved-supported",
        "resolved-not-supported",
        "blocked-with-owner-and-clearing-condition",
        "not-applicable-after-evidence",
    ):
        assert state in text
    assert "`untouched` and `in-progress` are intermediate states only" in text
    assert "zero material branches are untouched or in-progress" in text


def test_intermediate_finding_cannot_equal_completion():
    text = STANDARD.read_text()
    assert "progress evidence, not completion evidence" in text
    assert "#1237 ownership investigation" in text


def test_existing_reroute_and_no_progress_owners_are_reused():
    text = STANDARD.read_text()
    assert "#1237 reroute semantics" in text
    assert "#1200" in text
    assert "creates no research agent" in text


def test_investigation_completion_never_widens_authority():
    text = STANDARD.read_text()
    assert "grants no repository write" in text
    orchestrator = ORCHESTRATOR.read_text()
    assert "finite multi-item mission" in orchestrator
