from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "02_Agent_Overlays/unit-alignment-agent.md"
FIXTURES = ROOT / "07_Agent_Tests/unit-alignment-agent-tests-details.md"
RULES = ROOT / "01_Shared_Standards/instructional-design/unit-alignment-rules.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ux_align1_preserves_canonical_pass_blocked_contract() -> None:
    rules = read(RULES)
    overlay = read(OVERLAY)
    assert "status: `PASS` or `BLOCKED`" in rules
    assert "Formal `PASS`/`BLOCKED` verification" in overlay
    assert "not a second readiness or response schema" in overlay


def test_ux_align1_recommends_smallest_valid_repair_before_detail() -> None:
    overlay = read(OVERLAY)
    recommendation = "lead with one `Recommended` tune-up or smallest valid repair"
    assert recommendation in overlay
    assert overlay.index(recommendation) < overlay.index("Full audit, provenance, and check detail")


def test_ux_align1_repairable_blocked_result_stays_blocked() -> None:
    overlay = read(OVERLAY)
    assert "A repairable `BLOCKED` result stays `BLOCKED`" in overlay
    assert "gives the exact smallest valid repair" in overlay
    assert "without advancing the gate" in overlay


def test_ux_align1_nonrepairable_blocker_fails_closed() -> None:
    overlay = read(OVERLAY)
    assert "A non-repairable blocker or missing source/authority evidence stays blocker-first" in overlay
    assert "names the exact owner or condition required to unblock" in overlay
    assert "never invents a repair" in overlay


def test_ux_align1_reuses_known_context_before_questions() -> None:
    overlay = read(OVERLAY)
    assert "Reuse approved unit, lesson, objective, vocabulary, assessment, source, and prior-decision context" in overlay
    assert "before asking the teacher to repeat information" in overlay
    assert "ask only a material teacher choice" in overlay


def test_ux_align1_preserves_teacher_choice_labels() -> None:
    overlay = read(OVERLAY)
    for label in ("`Recommended`", "`Non-negotiable`", "`Flexible`"):
        assert label in overlay
    assert "without weakening any canonical gate" in overlay


def test_ux_align1_supports_in_place_conversational_revision() -> None:
    overlay = read(OVERLAY)
    assert "revise the current tune-up in place instead of restarting verification" in overlay
    assert "tightening the arc" in overlay
    assert "reducing overload" in overlay
    assert "offering another valid option" in overlay


def test_ux_align1_required_fixture_matrix_is_present() -> None:
    fixtures = read(FIXTURES)
    required = (
        "Unit 0",
        "Photography Foundations",
        "Clean PASS",
        "Repairable BLOCKED",
        "Non-repairable blocker",
        "Known context reuse",
        "One genuine teacher choice",
        "Conversational revision without restart",
        "Full audit on request",
        "Do not overwhelm",
    )
    for phrase in required:
        assert phrase in fixtures


def test_ux_align1_fixture_expectations_keep_authority_and_source_fail_closed() -> None:
    fixtures = read(FIXTURES)
    assert "no invented repair, source identity, or authority" in fixtures
    assert "does not advance readiness" in fixtures
    assert "same verification record" in fixtures


def test_ux_align1_does_not_create_parallel_runtime_systems() -> None:
    forbidden = (
        ROOT / "scripts/unit_alignment_ux",
        ROOT / "src/instructional_workflow_contracts/unit_alignment_ux.py",
        ROOT / "01_Shared_Standards/instructional-design/unit-alignment-response-schema.md",
    )
    assert not any(path.exists() for path in forbidden)
