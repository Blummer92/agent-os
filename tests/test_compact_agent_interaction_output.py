"""Focused contract checks for compact Agent OS output rendering (#1081)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/global-engineering/agent-interaction-output-standard.md"
MATRIX = ROOT / "07_Agent_Tests/interaction-output-profile-matrix.md"
VERSION_MAP = ROOT / "04_Registry/module-version-map.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def read(path: Path) -> str:
    """Return UTF-8 repository text."""
    return path.read_text(encoding="utf-8")


def section(path: Path, heading: str) -> str:
    """Return one Markdown H2 section."""
    text = read(path)
    marker = f"## {heading}\n"
    assert marker in text
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


def case(number: int) -> str:
    """Return one profile-matrix case body."""
    text = read(MATRIX)
    marker = f"## Case {number} -"
    start = text.index(marker)
    body = text[start:]
    return body.split("\n## Case ", 1)[0]


def test_compact_labels_map_to_canonical_evidence() -> None:
    """Compact labels have explicit canonical meanings."""
    text = section(STANDARD, "Compact Operator Rendering")
    for phrase in ("`Completed` = completed named stages", "`Current` = canonical current stage", "`Remaining` = unfinished stages", "distinct from `remaining_risks`", "`Blockers` = Base Report Contract `blockers`"):
        assert phrase in text


def test_progress_and_route_fail_closed() -> None:
    """Bars, routes, and next actions require supporting evidence."""
    text = section(STANDARD, "Compact Operator Rendering")
    assert "only when canonical evidence exposes a bounded named stage sequence" in text
    assert "omit the bar when no bounded sequence exists" in text
    assert "not a percentage" in text
    assert "only when executor-route/capability evidence is material" in text
    assert "only when current canonical evidence supports one" in text
    assert "omit it rather than inventing work" in text


def test_prompt_delivery_preserves_material_constraints() -> None:
    """Compact handoffs may omit only immaterial repeated context."""
    text = section(STANDARD, "Compact Operator Rendering")
    assert "smallest reusable context packet" in text
    for phrase in ("authorization boundary", "owner/source-of-truth constraint", "exact-head requirement", "validation failure"):
        assert phrase in text


def test_existing_percentage_rejection_remains_canonical() -> None:
    """The prior no-invented-percentage rule remains canonical."""
    text = section(STANDARD, "Progress And Evidence Rules")
    assert "Reject percentages unless a canonical contract supplies the completion signal." in text
    assert "parallel progress record" in text


def test_implementation_and_review_cases_are_evidence_conditional() -> None:
    """Cases 3-5 preserve bounded-stage and blocker behavior."""
    implementation, review, blocked = case(3), case(4), case(5)
    assert implementation.index("progress bar") < implementation.index("`Completed`") < implementation.index("Output Summary")
    assert "preferably one `Next` action when canonical evidence supports one" in implementation
    assert review.index("exact-head evidence") < review.index("compact status block") < review.index("handoff")
    assert "never invent merge/closure or a next action" in review
    assert "no bar without bounded stages" in blocked
    assert "no partial-completion claim" in blocked


def test_command_case_has_unambiguous_order_and_no_execution_claim() -> None:
    """Case 6 puts the artifact first and never implies execution."""
    text = case(6)
    assert text.index("context packet or artifact first") < text.index("brief explanation")
    assert "no implied execution" in text
    assert "only when it is not material to safe execution" in text
    assert "immediately before" not in text


def test_short_handoff_fixture_is_minimum_not_exhaustive() -> None:
    """Short handoffs retain controlling constraints when applicable."""
    text = read(MATRIX)
    assert "are a minimum set" in text
    assert "authorization, owner/source-of-truth, and exact-head constraints" in text


def test_version_registration_and_changelog_are_synchronized() -> None:
    """The standard, registry, and release note all register 0.2.0 once."""
    assert section(STANDARD, "Version").strip() == "0.2.0"
    row = "| Agent Interaction Output Standard | 0.2.0 |"
    assert read(VERSION_MAP).count(row) == 1
    changelog = read(CHANGELOG)
    assert "Agent Interaction Output Standard" in changelog and "#1081" in changelog
