"""Regression guards for #1608 tool-discovery continuation conformance.

The repository cannot force the native ChatGPT product loop to emit another tool
call, but it can make the continuation invariant and its integration boundary
machine-testable.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "01_Shared_Standards/github/tool-discovery-continuation.md"
FIXTURES = ROOT / "07_Agent_Tests/chatgpt-orchestrator.tests.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_discovery_is_intermediate_not_terminal() -> None:
    contract = normalized(CONTRACT)
    for phrase in (
        "successful tool/capability discovery + unfinished authorized mission != terminal state",
        "Discovery is intermediate evidence only",
        "continue to the next currently authorized operation in the same lineage",
        "explicit terminal blocker naming the controlling owner/reason and the clearing condition",
        "A silent stop is not a terminal classification",
    ):
        assert phrase in contract


def test_live_1573_complete_handoff_regression_is_pinned() -> None:
    fixtures = normalized(FIXTURES)
    for phrase in (
        "Complete the handoff",
        "#1573",
        "commit-related GitHub schema successfully loaded",
        "log-related GitHub schema successfully loaded",
        "the next GitHub evidence read occurs without a new user message",
    ):
        assert phrase in fixtures


def test_live_1582_red_pr_diagnostic_regression_is_pinned() -> None:
    fixtures = normalized(FIXTURES)
    for phrase in (
        "Live #1582 Red-PR Diagnostic Regression",
        "failed aggregate run: known",
        "workflow/job/log GitHub capability successfully loaded",
        "authorized actionable diagnostic read of the failed run",
        "the first actionable workflow/job/log diagnostic read executes in the same interaction without another user prompt",
    ):
        assert phrase in fixtures


def test_existing_same_lineage_and_terminal_reconciliation_contracts_are_reused() -> None:
    orchestrator = normalized(ORCHESTRATOR)
    safe_lane = normalized(SAFE_LANE)
    contract = normalized(CONTRACT)

    assert "route owner transitions internally and continue the same interaction" in orchestrator
    assert "Final finite-mission reconciliation must account for every requested identity exactly once" in orchestrator
    assert "discovery of one existing valid issue-linked branch, Draft PR, or checkpoint lineage is normally a resume target" in safe_lane
    assert "#1237 remains canonical for execution-interface reroute and same-lineage continuation" in contract
    assert "#1524 remains canonical for terminal investigation/question reconciliation" in contract
    assert "#1200 remains canonical for repeated semantic no-progress recovery loops" in contract


def test_sequential_schema_discovery_cannot_satisfy_completion() -> None:
    contract = normalized(CONTRACT)
    fixtures = normalized(FIXTURES)

    assert "When several schemas/actions must be discovered sequentially, each discovery remains intermediate" in contract
    assert "Sequential Schema Discovery Is Intermediate" in fixtures
    assert "No schema load is a terminal mission state" in fixtures


def test_continuation_preserves_authority_ceiling() -> None:
    contract = normalized(CONTRACT)
    fixtures = normalized(FIXTURES)

    for phrase in (
        "Discovery never grants repository write, merge, issue closure",
        "workflow/protected-setting mutation",
        "credentials/IAM",
        "production",
        "external write",
    ):
        assert phrase in contract

    assert "Continuation Never Widens Authority" in fixtures
    assert "never synthesize the missing authority" in fixtures


def test_orchestrator_consumes_continuation_contract() -> None:
    orchestrator = normalized(ORCHESTRATOR)
    assert "01_Shared_Standards/github/tool-discovery-continuation.md" in orchestrator


def test_external_integration_boundary_is_explicit() -> None:
    contract = normalized(CONTRACT)
    assert "they cannot force the native ChatGPT product/tool loop to emit another tool call" in contract
    assert "execution-interface integration work under #1237" in contract
    for forbidden in (
        "second executor router",
        "workflow engine",
        "mission store",
        "retry framework",
        "Scheduler",
        "authorization model",
    ):
        assert forbidden in contract
