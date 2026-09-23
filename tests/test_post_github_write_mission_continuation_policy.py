"""Regression guards for #2006 post-GitHub-write mission continuation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_successful_subordinate_github_write_is_not_parent_completion() -> None:
    workflow = normalized(AGENTS)
    assert "successful subordinate GitHub mutation during an unfinished finite mission" in workflow
    assert "provisional intermediate evidence" in workflow
    assert "never as parent-mission completion by itself" in workflow


def test_post_write_readback_and_parent_reacquisition_are_required() -> None:
    workflow = normalized(AGENTS)
    for phrase in (
        "Read back the canonical mutated target",
        "reacquire the parent issue/PR/branch/head/CI checkpoint",
        "Continue the still-authorized parent mission automatically",
    ):
        assert phrase in workflow


def test_orchestrator_routes_post_write_continuation_in_same_lineage() -> None:
    orchestrator = normalized(ORCHESTRATOR)
    for phrase in (
        "successful subordinate GitHub mutation during an unfinished finite mission is also intermediate evidence",
        "Treat the mutation response as provisional",
        "read back the canonical mutated target",
        "Continue to the next admitted operation in the same lineage",
        "Do not emit the parent mission's final report merely because the subordinate write succeeded",
    ):
        assert phrase in orchestrator


def test_1640_2003_reproduction_shape_is_covered() -> None:
    workflow = normalized(AGENTS)
    for mutation_kind in (
        "issue/PR comment",
        "label mutation",
        "handoff record",
        "evidence-persistence write",
    ):
        assert mutation_kind in workflow
    assert "parent issue/PR/branch/head/CI checkpoint" in workflow


def test_post_write_continuation_does_not_widen_authority() -> None:
    workflow = normalized(AGENTS)
    for phrase in (
        "never widens authority",
        "never grants merge",
        "issue-closure",
        "workflow/protected-setting",
        "credential",
        "production",
        "external-write authority",
    ):
        assert phrase in workflow


def test_existing_continuation_architecture_remains_canonical() -> None:
    orchestrator = normalized(ORCHESTRATOR)
    assert "Final finite-mission reconciliation" in orchestrator
    assert "Mission continuation never widens authority" in orchestrator
    assert "Successful tool/schema/capability discovery during an unfinished authorized mission is intermediate evidence" in orchestrator
