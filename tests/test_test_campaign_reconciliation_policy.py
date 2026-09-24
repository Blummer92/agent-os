"""Regression contract for #2872 governed test-campaign reconciliation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTING = ROOT / "01_Shared_Standards/global-engineering/testing-and-release.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
QA_OVERLAY = ROOT / "02_Agent_Overlays/qa-test-agent.md"
QA_FIXTURES = ROOT / "07_Agent_Tests/qa-test-agent.tests.md"

def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())

def test_next_test_planning_reconciles_canonical_campaign_history() -> None:
    testing = normalized(TESTING)
    for phrase in (
        "Before recommending another manual, conversational, benchmark, or adversarial test",
        "reacquire the canonical campaign owner and its current result evidence",
        "completed-test matrix",
        "do not create a second test-state store",
    ):
        assert phrase in testing

def test_candidates_use_semantic_three_way_classification() -> None:
    testing = normalized(TESTING)
    for phrase in ("`new condition`", "`intentional repeat`", "`already completed`", "Compare proposed conditions semantically", "Never present an `already completed` condition as new work"):
        assert phrase in testing
    assert "prompt text alone" in testing

def test_intentional_repeat_requires_measurement_purpose() -> None:
    testing = normalized(TESTING)
    assert "An `intentional repeat` must state what changed or what measurement the repetition provides" in testing
    for phrase in ("regression verification", "changed model/configuration", "variance", "changed dependency"):
        assert phrase in testing

def test_conversational_manual_metadata_contract_is_preserved() -> None:
    testing = normalized(TESTING)
    for phrase in ("exact prompt", "model/configuration", "user-visible reasoning/thinking setting", "same-chat or fresh-chat mode", "required prior turns/context", "required attached/project sources", "expected behavior/pass criteria", "failure signals", "result-evidence location", "timestamp/config notes"):
        assert phrase in testing

def test_orchestrator_and_qa_consume_shared_campaign_contract() -> None:
    for content in (normalized(ORCHESTRATOR), normalized(QA_OVERLAY)):
        assert "Governed Test-Campaign Reconciliation" in content
        for phrase in ("`new condition`", "`intentional repeat`", "`already completed`"):
            assert phrase in content

def test_2026_09_23_teacher_ux_reproduction_is_covered() -> None:
    fixtures = normalized(QA_FIXTURES)
    assert 'Prompt: "Shall we do some more tests on the teacher UX issue?"' in fixtures
    for phrase in ("known-context reuse", "ambiguous assent", "correction/reversal", "preserve-unrelated-decisions", "semantically equivalent candidates are classified `already completed`"):
        assert phrase in fixtures

def test_reworded_selective_change_does_not_become_new_condition() -> None:
    fixtures = normalized(QA_FIXTURES)
    assert 'Prompt: "Give me another test where I change one decision and keep the rest."' in fixtures
    assert "Semantic comparison treats the reworded proposal as `already completed`" in fixtures
    assert "exact prompt wording alone cannot make the condition new" in fixtures
