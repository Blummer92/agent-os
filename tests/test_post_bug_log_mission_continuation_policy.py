"""Regression guards for #1720 post-bug-log mission continuation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_bug_capture_is_subordinate_to_unfinished_authorized_mission() -> None:
    workflow = normalized(AGENTS)
    assert "treat bug capture as subordinate bookkeeping rather than a terminal outcome" in workflow
    assert "continue the still-authorized parent mission without requiring another user prompt" in workflow


def test_parent_checkpoint_is_reacquired_after_bug_persistence() -> None:
    workflow = normalized(AGENTS)
    for required in (
        "reacquire the parent issue/PR/branch/head checkpoint",
        "bounded bug write or alternate canonical persistence route",
        "unfinished authorized mission",
    ):
        assert required in workflow


def test_bug_logging_does_not_widen_parent_authority() -> None:
    workflow = normalized(AGENTS)
    assert "still-authorized parent mission" in workflow
    assert "shared authorization" in workflow
    assert "excluded-surface" in workflow
    assert "material-decision blocker" in workflow


def test_existing_orchestrator_continuation_contract_remains_canonical() -> None:
    orchestrator = normalized(ORCHESTRATOR)
    assert "route owner transitions internally" in orchestrator
    assert "Mission continuation never widens authority" in orchestrator
    assert "continue to the next admitted operation in the same lineage" in orchestrator


def test_regression_does_not_introduce_new_execution_architecture() -> None:
    workflow = normalized(AGENTS)
    forbidden = (
        "second scheduler",
        "new persistence system",
        "background daemon",
        "new authorization model",
    )
    for phrase in forbidden:
        assert phrase not in workflow.lower()
