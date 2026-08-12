"""Focused contract checks for compact Agent OS output rendering (#1081)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/global-engineering/agent-interaction-output-standard.md"
MATRIX = ROOT / "07_Agent_Tests/interaction-output-profile-matrix.md"
VERSION_MAP = ROOT / "04_Registry/module-version-map.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(path: Path, heading: str) -> str:
    text = read(path)
    marker = f"## {heading}\n"
    assert marker in text, f"missing section {heading!r} in {path}"
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


def test_compact_operator_rendering_uses_named_status_labels() -> None:
    text = section(STANDARD, "Compact Operator Rendering")
    for label in ("`Completed`", "`Current`", "`Remaining`", "`Blockers`"):
        assert label in text
    assert "state-based progress bar" in text
    assert "bounded named stage sequence" in text
    assert "omit the progress bar" in text
    assert "not a percentage" in text


def test_compact_rendering_keeps_one_material_route_and_next_action() -> None:
    text = section(STANDARD, "Compact Operator Rendering")
    assert "`Best execution` only when the executor route is material" in text
    assert "Prefer one `Next` action" in text
    assert "smallest concrete action" in text
    assert "canonical executor-route or capability evidence" in text


def test_prompt_delivery_uses_smallest_reusable_context() -> None:
    text = section(STANDARD, "Compact Operator Rendering")
    assert "smallest reusable context packet" in text
    assert "Do not repeat governance, source-of-truth, architecture, or" in text
    assert "already available to the target agent or tool" in text


def test_compactness_never_hides_material_evidence() -> None:
    text = section(STANDARD, "Compact Operator Rendering")
    for phrase in (
        "controlling blocker",
        "authorization boundary",
        "exact-head requirement",
        "validation failure",
        "required final-report evidence",
    ):
        assert phrase in text


def test_existing_percentage_rejection_remains_canonical() -> None:
    text = section(STANDARD, "Progress And Evidence Rules")
    assert "Reject percentages unless a canonical contract supplies the completion signal." in text
    assert "Never persist a" in text
    assert "parallel progress record" in text


def test_profile_matrix_covers_compact_regressions() -> None:
    text = read(MATRIX)
    assert "Compact Operator Rendering Regression Fixtures (#1081)" in text
    for phrase in (
        "Bounded implementation stages",
        "No bounded stage sequence",
        "PR review with exact head",
        "Blocked work",
        "Short execution handoff",
        "Material route escalation",
    ):
        assert phrase in text


def test_focused_standard_version_is_registered() -> None:
    assert section(STANDARD, "Version").strip() == "0.2.0"
    assert "| Agent Interaction Output Standard | 0.2.0 |" in read(VERSION_MAP)
