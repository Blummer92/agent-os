from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "07_Agent_Tests" / "video-production-instructional-reasoning.tests.md"


def _fixture_text() -> str:
    return FIXTURES.read_text(encoding="utf-8")


def test_alternate_take_is_checked_before_reshoot() -> None:
    text = _fixture_text()

    assert "## VP-1 — Existing Alternate Take vs. Reshoot" in text
    assert "replace selected take B with already-existing alternate take B2" in text
    assert "bad selected take -> automatically reshoot" in text
    assert "B2 already existed before the recommendation" in text


def test_continuity_contradiction_rejects_usable_alternate() -> None:
    text = _fixture_text()

    assert "## VP-2 — Alternate Exists but Breaks Continuity" in text
    assert "technically usable != automatically role-and-continuity compatible" in text
    assert "B2 therefore cannot safely replace B in this sequence" in text
    assert "targeted reshoot of the required Door X handle close-up is justified" in text


def test_usable_required_action_prefers_trim_over_replacement() -> None:
    text = _fixture_text()

    assert "## VP-3 — Usable Action Inside a Partially Unusable Take" in text
    assert "trim selected source take B to retain its complete usable required action" in text
    assert "alternate exists -> automatically replace" in text


def test_wrong_sequence_prefers_reorder_without_source_replacement() -> None:
    text = _fixture_text()

    assert "## VP-4 — Correct Coverage, Wrong Sequence Order" in text
    assert "reorder the existing A, B, and C occurrences to A -> B -> C" in text
    assert "Reordering changes sequence position, not which recorded source take fulfills each role" in text
