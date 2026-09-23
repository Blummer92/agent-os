from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/instructional-design/unit-creation-conversational-contract.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/agent-orchestrator.md"
ALIGNMENT = ROOT / "02_Agent_Overlays/unit-alignment-agent.md"
MODELING = ROOT / "02_Agent_Overlays/teacher-modeling-coach.md"
DETAILS = ROOT / "07_Agent_Tests/agent-orchestrator-tests-details.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_1214_reuses_existing_handoff_surfaces_and_no_new_framework() -> None:
    content = read(STANDARD) + read(ORCHESTRATOR)
    for field in ("context_packet", "reusable_outputs", "blockers", "next_owner", "handoff_artifacts"):
        assert field in content
    for forbidden in ("UnitCreationHandoff", "new packet or field list", "new router, packet, state, readiness, or persistence system"):
        assert forbidden not in content if forbidden == "UnitCreationHandoff" else forbidden in content


def test_1214_advisory_trigger_and_suppression_are_bounded() -> None:
    content = read(STANDARD)
    assert "only when current planning evidence exposes a material question" in content
    assert "Existing adequate modeling evidence suppresses the advisory" in content
    assert "AI use alone never triggers it" in content
    for outcome in ("`no concern`", "`full modeling needs attention later`", "`possible structural issue`"):
        assert outcome in content


def test_1214_unit_alignment_remains_formal_owner() -> None:
    content = read(ALIGNMENT)
    assert "inputs/evidence for verification, never verification themselves" in content
    assert "Unit Alignment alone determines" in content
    assert "cannot substitute for any of the six checks or Tier 2" in content
    assert "do not preserve a stale prior PASS" in content


def test_1214_modeling_advisory_cannot_become_formal_modeling() -> None:
    content = read(MODELING)
    assert "It is not this coach's formal modeling lifecycle" in content
    assert "creates no modeling record, rehearsal, think-aloud, Materials extract, or `READY/BLOCKED`" in content
    assert "Formal Teacher Modeling begins only after canonical Unit Alignment PASS" in content
    assert "does not repair Unit Alignment-owned intent" in content


def test_1214_materials_and_readiness_boundaries_stay_closed() -> None:
    content = read(STANDARD)
    assert "cannot be consumed by Instructional Materials as approved modeling" in content
    assert "Instructional Materials may not infer unresolved teacher intent" in content
    assert "Missing required formal modeling remains blocking" in content
    assert "cannot set Unit Alignment `PASS/BLOCKED`, Teacher Modeling `READY/BLOCKED`, or Materials readiness" in content


def test_1214_reversal_and_current_evidence_do_not_preserve_stale_state() -> None:
    content = read(STANDARD)
    assert "Conversation history never overrides newer canonical evidence" in content
    assert "A prior Unit Alignment PASS, Teacher Modeling READY, or Materials assumption is not current" in content
    assert "preserve unaffected inputs" in content
    assert "Do not create a curriculum dependency graph" in content


def test_1214_decision_studio_and_teacher_choice_routing() -> None:
    content = read(STANDARD) + read(ORCHESTRATOR)
    assert "complex rubric or assessment tradeoffs use Teacher Decision Studio" in content
    assert "simple choices stay conversational" in content
    assert "Teacher rejection or a custom option remains valid input unless it violates a canonical requirement" in content


def test_1214_fixture_matrix_covers_core_scenarios_and_invariants() -> None:
    content = read(DETAILS)
    for fixture in ("AI Movie Poster", "Photography", "Typography", "AI Superhero", "Roller Coaster"):
        assert fixture in content
    for phrase in (
        "Unit Sketch acceptance cannot set Unit Alignment PASS",
        "pre-PASS advisory cannot set Modeling READY/BLOCKED",
        "Materials cannot consume advisory output as approved modeling",
        "current canonical evidence outranks chat memory",
        "no new state, memory, freshness, readiness, packet, router, lifecycle",
    ):
        assert phrase in content
