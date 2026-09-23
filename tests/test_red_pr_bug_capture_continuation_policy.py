"""Regression contract for #2635 red-PR bug-capture continuation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "07_Agent_Tests" / "fixtures" / "red-pr-bug-capture-continuation.md"
FAILED_REPAIR = (
    ROOT
    / "01_Shared_Standards"
    / "global-engineering"
    / "failed-repair-lesson-reentry.md"
)
AGENTS = ROOT / "AGENTS.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_2635_exact_red_pr_sequence_is_pinned() -> None:
    fixture = normalized(FIXTURE)
    for phrase in (
        "parent PR: #2630",
        "exact failing head: 452d8c9db2f57f9f0757272849dedd0847eccdfa",
        "persist or link the canonical defect",
        "canonical readback of the persisted defect evidence",
        "reacquire parent PR/head/checkpoint and current check state",
        "complete the strongest still-authorized same-lineage handoff",
    ):
        assert phrase in fixture


def test_diagnosis_and_bug_capture_are_intermediate_not_terminal() -> None:
    fixture = normalized(FIXTURE)
    assert "!= terminal completion" in fixture
    assert "subordinate bug capture still cannot make the parent mission terminal" in fixture
    assert "non-terminal same-lineage action" in fixture


def test_failed_repair_contract_requires_readback_then_parent_reacquisition() -> None:
    contract = normalized(FAILED_REPAIR)
    assert "Canonically read back the persisted defect evidence" in contract
    assert "reacquire the active parent issue/PR/branch/head/checkpoint and current check state" in contract
    assert "A correct diagnosis, bug record, evidence comment, or handoff artifact is intermediate evidence" in contract
    assert "without another user prompt" in contract


def test_existing_2220_continuation_owner_is_reused() -> None:
    fixture = normalized(FIXTURE)
    agents = normalized(AGENTS)
    assert "#2220 mission-completion and continuation semantics" in fixture
    assert "treat bug capture as subordinate bookkeeping rather than a terminal outcome" in agents
    assert "reacquire the parent issue/PR/branch/head checkpoint" in agents
    assert "Do not create another scheduler, queue, retry engine, mission-state model, bug tracker" in fixture


def test_genuine_blockers_still_stop_without_synthesizing_authority() -> None:
    fixture = normalized(FIXTURE)
    for phrase in (
        "authorization",
        "source-of-truth",
        "scope",
        "ownership",
        "excluded-surface",
        "material-decision",
        "capability blocker",
        "merge",
        "issue closure",
        "workflow/protected-setting mutation",
        "credential/IAM",
        "production",
        "external-write",
    ):
        assert phrase in fixture
