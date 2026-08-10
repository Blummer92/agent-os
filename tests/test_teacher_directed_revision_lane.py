from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "01_Shared_Standards/instructional-design/production-gates-and-compute.md"
WORKFLOWS = ROOT / "01_Shared_Standards/instructional-design/instructional-materials-workflows.md"
OVERLAY = ROOT / "02_Agent_Overlays/instructional-materials-coach.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_teacher_directed_revision_lane_is_bounded_and_non_authorizing():
    gates = _read(GATES)
    workflows = _read(WORKFLOWS)
    overlay = _read(OVERLAY)

    assert "## Teacher-Directed Revision Lane" in gates
    assert "teacher-directed routine revision" in gates.lower()
    assert "structural instructional revision" in gates.lower()
    assert "new production / release" in gates.lower()
    assert "without requiring `Production Authorized:" in gates
    assert "Teacher-directed revision authority is artifact-edit authority only" in gates

    for protected_boundary in (
        "protected template or master",
        "no governed readiness, approval, source-of-truth, ownership, or audit field",
        "no sharing, permissions, publication, ownership, or destination change",
        "no unapproved asset, source, vocabulary, or unsafe content",
    ):
        assert protected_boundary in gates

    assert "## Revision Classification" in workflows
    assert "does not require `Production Authorized: Yes` merely" in workflows
    assert "new-production gate instead" in workflows

    assert "bounded revisions" in overlay
    assert "teacher-directed revisions that fail" in overlay
    assert "structural instructional revisions or" in overlay
    assert "Template or master files" in overlay
    assert "sharing or\npermission changes" in overlay


def test_full_production_gate_still_applies_outside_routine_revision():
    gates = _read(GATES)

    assert "For structural instructional revisions and new production/release" in gates
    assert "`Source Confidence` is approved" in gates
    assert "`Unit Readiness` is ready" in gates
    assert "`Modeling Readiness` is ready" in gates
    assert "`Evidence Target` is populated" in gates
    assert "`Blockers` is none" in gates
    assert "If any lane condition fails" in gates
