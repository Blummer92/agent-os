from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = [
    ROOT / "02_Agent_Overlays/unit-alignment-agent.md",
    ROOT / "02_Agent_Overlays/teacher-modeling-coach.md",
    ROOT / "02_Agent_Overlays/instructional-materials-coach.md",
]
LP3 = "01_Shared_Standards/instructional-design/lp-pacing-handoff-contract.md"


def test_all_lp3_consumers_inherit_canonical_handoff_contract():
    for path in OVERLAYS:
        assert LP3 in path.read_text()


def test_unit_alignment_preserves_six_check_and_tier2_authority():
    text = OVERLAYS[0].read_text()
    assert "not a seventh Unit Alignment check" in text
    assert "does not replace Tier 2" in text
    assert "cannot independently set Unit Alignment `PASS` or `BLOCKED`" in text


def test_uneven_evidence_stays_multidimensional_not_a_score():
    combined = "\n".join(path.read_text() for path in OVERLAYS)
    for dimension in (
        "instructional demand",
        "learner-relative familiarity",
        "language/representation load",
        "material-induced load",
        "operational load",
        "evidence uncertainty",
    ):
        assert dimension in combined.lower()
    assert "one-dimensional" in combined
    assert "automatic placement" in combined
