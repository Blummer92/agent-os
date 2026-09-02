"""Regression guards for #1605/#1614 failed-CI diagnostic evidence routing.

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


def test_1614_insufficient_log_read_cannot_be_the_only_blocker_evidence() -> None:
    preflight = section(ORCHESTRATOR, "Execution-Surface Capability Preflight")
    fixture = section(ORCHESTRATOR_TESTS, "Test 41 - Insufficient CI Log Read Uses Alternate Canonical Evidence")

    for phrase in (
        "insufficient evidence",
        "action/surface evidence rather than mission failure",
        "another known or discoverable already-authorized canonical GitHub evidence route",
        "Before returning `BLOCKED_DIAGNOSTIC_SURFACE`",
    ):
        assert phrase in preflight

    assert "does not emit `BLOCKED_DIAGNOSTIC_SURFACE` from the first insufficient read" in fixture
    assert "does not ask the repository owner to copy logs" in fixture


def test_1614_owner_is_not_manual_transport_for_internally_retrievable_ci_evidence() -> None:
    preflight = section(ORCHESTRATOR, "Execution-Surface Capability Preflight")
    assert "must not be used as a manual copy/paste transport for CI logs, check annotations, or equivalent diagnostic evidence" in preflight
    assert "the connected GitHub surface can retrieve itself" in preflight


def test_1614_annotation_read_gap_is_named_as_integration_capability() -> None:
    preflight = section(ORCHESTRATOR, "Execution-Surface Capability Preflight")
    fixture = section(ORCHESTRATOR_TESTS, "Test 42 - Failed Check Annotation Gap Is An Integration Blocker Not Owner Transport")

    assert "proves that actionable evidence exists but exposes no supported read action" in preflight
    assert "missing connector/integration capability" in preflight
    assert "missing connector/integration annotation-read capability" in fixture
    assert "repository owner is not assigned ordinary log/annotation copy-paste transport" in fixture


def test_1614_diagnostic_reroute_reacquires_head_and_is_bounded() -> None:
    preflight = section(ORCHESTRATOR, "Execution-Surface Capability Preflight")
    fixture = section(ORCHESTRATOR_TESTS, "Test 43 - Diagnostic Route Transition Preserves Authority And Terminates")

    assert "Reacquire the current PR/head or other operation identity before consuming head-bound evidence after a route transition" in preflight
    assert "Do not retry the same unsupported route indefinitely" in preflight
    assert "reacquires the current PR/head before consuming diagnostics" in fixture
    assert "never retries the same unsupported route indefinitely" in fixture
    assert "If all bounded routes are exhausted, returns one explicit integration blocker" in fixture
