"""Regression guards for #1614 false CI diagnostic owner handoff.

Repository policy can make the continuation contract machine-testable, but the
native ChatGPT/GitHub connector remains responsible for actually retrieving
check annotations or equivalent diagnostic detail.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "01_Shared_Standards/github/tool-discovery-continuation.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
RED_CI = ROOT / "08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/red_ci_continuation.py"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_one_insufficient_diagnostic_read_is_not_a_terminal_blocker() -> None:
    contract = normalized(CONTRACT)
    for phrase in (
        "one insufficient diagnostic read + another bounded canonical GitHub evidence route known or discoverable != BLOCKED_DIAGNOSTIC_SURFACE",
        "repository owner must not be used as a manual copy/paste transport",
        "reacquire the exact current PR head",
        "boundedly inspect another already-authorized canonical GitHub evidence route",
        "emit `BLOCKED_DIAGNOSTIC_SURFACE` only after the bounded alternatives are exhausted",
    ):
        assert phrase in contract


def test_live_1582_false_owner_handoff_regression_is_pinned() -> None:
    contract = normalized(CONTRACT)
    for phrase in (
        "PR #1582 reproduction",
        "workflow-job log read returns insufficient step output",
        "exact-head check-run collection remains readable",
        "annotations_count > 0",
        "never ask the repository owner to manually transport evidence still internally retrievable",
    ):
        assert phrase in contract


def test_existing_reroute_red_ci_and_no_progress_owners_are_reused() -> None:
    contract = normalized(CONTRACT)
    orchestrator = normalized(ORCHESTRATOR)
    red_ci = normalized(RED_CI)

    assert "#1237 remains canonical for execution-interface reroute and same-lineage continuation" in contract
    assert "completed #1251 remains canonical for red-CI checkpoint" in contract
    assert "#1200 remains canonical for repeated semantic no-progress recovery loops" in contract
    assert "#1608 remains canonical for silent post-discovery mission abandonment" in contract
    assert "consume #1237 reroute semantics" in orchestrator
    assert "alternate_diagnostic_surface_available" in red_ci
    assert "diagnostic.no-actionable-surface" in red_ci


def test_connector_annotation_gap_stays_external_to_repository_runtime() -> None:
    contract = normalized(CONTRACT)
    assert "cannot force the native ChatGPT product/tool loop to emit another tool call" in contract
    assert "add a connector action that the active GitHub integration does not expose" in contract
    assert "cannot read known failed-check annotations/equivalent detail" in contract
    assert "execution-interface/connector integration work under #1237/#1614" in contract


def test_continuation_does_not_widen_authority_or_create_second_architecture() -> None:
    contract = normalized(CONTRACT)
    for phrase in (
        "Discovery never grants repository write, merge, issue closure",
        "workflow/protected-setting mutation",
        "credentials/IAM",
        "production",
        "external write",
        "second executor router",
        "CI framework",
        "authorization model",
    ):
        assert phrase in contract
