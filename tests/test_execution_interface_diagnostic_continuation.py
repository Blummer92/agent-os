"""Regression contract for #1673 execution-interface diagnostic continuation.

Repository fixtures cannot force the native ChatGPT product loop to emit a tool call.
They can pin the governed behavior: an insufficient diagnostic surface is route
evidence, not mission completion, and terminal output is allowed only after bounded
same-lineage alternatives are exhausted with an explicit blocker and clearing condition.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
ORCHESTRATOR_TESTS = ROOT / "07_Agent_Tests/chatgpt-orchestrator.tests.md"
TOOL_CONTINUATION = ROOT / "01_Shared_Standards/github/tool-discovery-continuation.md"
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_1673_exact_1615_sequence_requires_same_lineage_continuation() -> None:
    evidence = " ".join(
        normalized(path)
        for path in (ORCHESTRATOR, ORCHESTRATOR_TESTS, TOOL_CONTINUATION, SAFE_LANE)
    )

    # Exact live reproduction signals from #1615 / #1673.
    for phrase in (
        "annotations_count > 0",
        "workflow-job log action returns no actionable step output",
        "another bounded canonical GitHub evidence route",
        "reacquires the current PR/head",
        "continues same-lineage diagnosis",
    ):
        assert phrase in evidence

    # The first insufficient diagnostic read cannot terminate the mission.
    assert "action/surface evidence rather than mission failure" in evidence
    assert "does not emit `BLOCKED_DIAGNOSTIC_SURFACE` from the first insufficient read" in evidence
    assert "continue to the next currently authorized operation in the same lineage" in evidence


def test_1673_capable_same_lineage_route_forbids_owner_handoff() -> None:
    evidence = " ".join(
        normalized(path)
        for path in (ORCHESTRATOR, ORCHESTRATOR_TESTS, TOOL_CONTINUATION, SAFE_LANE)
    )

    assert "Preserve eligible Safe Implementation Lane work across an internal execution-surface reroute" in evidence
    assert "without requiring another user message" in evidence
    assert "must not be used as a manual copy/paste transport" in evidence


def test_1673_terminal_stop_requires_exhaustion_blocker_and_clearing_condition() -> None:
    evidence = " ".join(
        normalized(path)
        for path in (ORCHESTRATOR, ORCHESTRATOR_TESTS, TOOL_CONTINUATION, SAFE_LANE)
    )

    assert "stop only after the bounded authorized alternatives are exhausted" in evidence
    assert "explicit terminal blocker naming the controlling owner/reason and the clearing condition" in evidence
    assert "If all bounded routes are exhausted, returns one explicit integration blocker" in evidence


def test_1673_does_not_create_second_runtime_or_authority_system() -> None:
    tool_contract = normalized(TOOL_CONTINUATION)
    preflight = normalized(ORCHESTRATOR)

    for forbidden_duplicate in (
        "second executor router",
        "workflow engine",
        "mission store",
        "retry framework",
        "Scheduler",
        "authorization model",
    ):
        assert forbidden_duplicate in tool_contract

    assert "This overlay does not define a second route selector" in preflight
    assert "A route change never widens authority" in preflight
