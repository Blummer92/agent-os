"""Regression guards for #1605 failed-CI diagnostic evidence routing.

The repository cannot manufacture connector capabilities, but the ChatGPT Orchestrator
contract must prefer canonical connected evidence and existing capable execution routes
before shifting CI-log transport onto a mobile user.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
ORCHESTRATOR_TESTS = ROOT / "07_Agent_Tests/chatgpt-orchestrator.tests.md"
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"
TESTING_RELEASE = ROOT / "01_Shared_Standards/global-engineering/testing-and-release.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    marker = f"## {heading}\n"
    assert marker in text
    body = text.split(marker, 1)[1].split("\n## ", 1)[0]
    return " ".join(body.split())


def test_failed_ci_diagnosis_prefers_connected_canonical_evidence_before_manual_shell() -> None:
    preflight = section(ORCHESTRATOR, "Execution-Surface Capability Preflight")
    safe_lane = section(SAFE_LANE, "Validation Loop")
    testing = section(TESTING_RELEASE, "Developer Loop Validation")

    # The existing contracts already establish the governing rule. #1605 makes the
    # cross-contract implication executable for failed-CI diagnosis: use the connected
    # surface when it can satisfy the next evidence action and do not make the user a
    # shell/log transport merely because another local capability is absent.
    assert "Use the connected GitHub surface directly when its available actions are sufficient for the exact next action" in preflight
    assert "Do not assume `git`, `gh`, GitHub authentication" in preflight
    assert "reacquire capability evidence and recompute the route" in preflight
    assert "Do not require the user to copy/paste shell commands solely because the active connector cannot execute them" in safe_lane
    assert "Do not stop or require user copy/paste shell commands solely because the active connector lacks runtime capability" in testing


def test_missing_local_gh_is_a_reroute_signal_not_a_mobile_log_request() -> None:
    fixture = section(ORCHESTRATOR_TESTS, "Test 22 - Missing Local Gh Recomputation")
    for phrase in (
        "local `gh` unavailable",
        "capability mismatch",
        "reacquires capability evidence",
        "recomputes the existing executor route",
    ):
        assert phrase in fixture

    # A missing local CLI cannot justify skipping an already-capable connected route.
    preflight = section(ORCHESTRATOR, "Execution-Surface Capability Preflight")
    assert "A missing tool such as local `gh` is capability-mismatch evidence" in preflight
    assert "not by itself evidence that the governing repository issue or implementation is defective" in preflight


def test_failed_ci_repair_continues_across_internal_capability_reroute() -> None:
    routing = section(ORCHESTRATOR, "Routing Rules")
    preflight = section(ORCHESTRATOR, "Execution-Surface Capability Preflight")

    assert "in-scope repair" in routing
    assert "route owner transitions internally" in routing
    assert "Preserve eligible Safe Implementation Lane work across an internal execution-surface reroute" in preflight
    assert "A route change never widens authority" in preflight


def test_manual_console_is_not_the_primary_architecture_when_governed_routes_exist() -> None:
    safe_lane = section(SAFE_LANE, "Validation Loop")
    testing = section(TESTING_RELEASE, "Developer Loop Validation")

    assert "Required validation must be routed to a capable authorized executor" in safe_lane
    assert "reuse the canonical executor-routing contract" in safe_lane
    assert "existing governed CI route" in safe_lane
    assert "If no capable authorized local, governed-runner, or existing governed CI route exists, stop with `needs-decision`" in safe_lane

    assert "cheapest capable authorized executor" in testing
    assert "reuse the canonical executor-routing contract" in testing
    assert "If neither the active execution surface, the canonical governed runner, nor an existing governed CI route can produce the required evidence, stop with `needs-decision`" in testing


def test_diagnostic_routing_does_not_widen_authority() -> None:
    authority = section(ORCHESTRATOR_TESTS, "Test 26 - Capability Reroute Does Not Widen Authority")
    for phrase in (
        "preserves the existing authorization ceiling",
        "never infers merge",
        "workflow/protected-setting",
        "credential/IAM",
        "production",
        "external-write",
    ):
        assert phrase in authority


def test_1605_regression_shape_is_covered_by_existing_canonical_contracts() -> None:
    """Pin the exact failure shape observed while repairing PR #1599.

    Red CI plus missing local gh must not imply: ask the mobile user to authenticate gh,
    scrape Actions, or manually isolate log text when the connected GitHub surface or an
    existing capable governed route can satisfy the diagnostic next action.
    """
    all_text = " ".join(
        normalized(path)
        for path in (ORCHESTRATOR, ORCHESTRATOR_TESTS, SAFE_LANE, TESTING_RELEASE)
    )
    for required in (
        "connected GitHub surface directly",
        "local `gh` unavailable",
        "recomputes the existing executor route",
        "Do not require the user to copy/paste shell commands",
        "existing governed CI route",
        "route change never widens authority",
    ):
        assert required in all_text
