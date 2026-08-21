from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/unit-creation-conversational-contract.md"
OVERLAY = ROOT / "02_Agent_Overlays/agent-orchestrator.md"
DETAILS = ROOT / "07_Agent_Tests/agent-orchestrator-tests-details.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_1213_conversation_is_useful_before_process_and_questions_are_material() -> None:
    content = read(STANDARD)
    assert "Respond to the teacher's idea before exposing process or governance" in content
    assert "Do useful planning work between questions" in content
    assert "Routine turns should usually contain zero or one material question" in content


@pytest.mark.parametrize("phrase", [
    "does not confirm all proposals",
    "a follow-up question is not confirmation",
    "acceptance with modification confirms only the modified choice",
    "later correction or rejection supersedes the working teacher choice",
])
def test_1213_confirmation_fails_closed_on_ambiguous_assent(phrase: str) -> None:
    assert phrase in read(STANDARD)


def test_1213_unit_sketch_is_provisional_and_non_authorizing() -> None:
    content = read(STANDARD)
    for field in ("What this unit is about", "Students are learning to...", "They'll show it by...", "Likely arc"):
        assert field in content
    assert "not a persisted canonical unit schema" in content
    assert "must never imply Unit Alignment PASS, Modeling READY, Production Authorized" in content


def test_1213_advisory_has_exactly_three_bounded_meanings() -> None:
    content = read(STANDARD)
    for outcome in ("`no concern`", "`full modeling needs attention later`", "`possible structural issue`"):
        assert outcome in content
    assert "Creative, digital, project-based, or AI-assisted work alone is not a trigger" in content


def test_1213_context_reuse_and_reversal_do_not_create_new_state_system() -> None:
    content = read(STANDARD)
    assert "exact current match: use naturally without asking the teacher to repeat it" in content
    assert "Conversation history never overrides newer canonical evidence" in content
    assert "preserve unaffected inputs" in content
    assert "Do not create a curriculum dependency graph" in content
    assert "no new state, memory, freshness, readiness, choice, or orchestration subsystem" in content


def test_1213_orchestrator_consumes_shared_contract_by_reference() -> None:
    content = read(OVERLAY)
    assert "unit-creation-conversational-contract.md" in content
    assert "exploratory new-unit planning" in content
    assert "does not replace formal Unit Alignment" in content


def test_1213_fixture_matrix_covers_required_golden_and_adversarial_cases() -> None:
    content = read(DETAILS)
    for fixture in ("Color", "AI Movie Poster", "Photography", "Roller Coaster"):
        assert fixture in content
    for phrase in ("multiple-proposal assent", "follow-up question", "start fresh", "one-word mobile", "controlling blocker"):
        assert phrase in content
