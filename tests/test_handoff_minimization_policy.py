"""Contract tests for continuous governed execution under the Safe Implementation Lane."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
ORCHESTRATOR_REQUEST = ROOT / "02_Agent_Overlays/chatgpt-orchestrator-request-interpretation.md"
ORCHESTRATOR_TESTS = ROOT / "07_Agent_Tests/chatgpt-orchestrator.tests.md"
ORCHESTRATOR_REQUEST_TESTS = ROOT / "07_Agent_Tests/chatgpt-orchestrator-request-interpretation.tests.md"
EXCLUDED = ROOT / "01_Shared_Standards/github/excluded-surface-baseline.md"


def normalized_text(text: str) -> str:
    return " ".join(text.split())


def normalized(path: Path) -> str:
    return normalized_text(path.read_text(encoding="utf-8"))


def section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    marker = f"## {heading}\n"
    assert marker in text
    body = text.split(marker, 1)[1].split("\n## ", 1)[0]
    return normalized_text(body)


def test_safe_lane_treats_owner_transition_as_internal_routing() -> None:
    text = section(SAFE_LANE, "Authorization Effect")
    for phrase in (
        "registered-owner transition is internal routing",
        "not by itself a user-visible handoff or stop",
        "continue in the same interaction",
        "without a new user prompt",
    ):
        assert phrase in text
    assert "one consolidated user-facing result" in section(SAFE_LANE, "Reporting")


def test_continuous_routing_preserves_owner_and_authority_boundaries() -> None:
    text = section(SAFE_LANE, "Authorization Effect")
    for phrase in (
        "Ownership and authority do not transfer",
        "GitHub Service Agent stays the sole repository writer",
        "QA / Test Agent retains validation-evidence ownership",
        "never authorizes a previously excluded surface",
    ):
        assert phrase in text


def test_entrypoint_and_orchestrator_do_not_surface_owner_changes_by_default() -> None:
    agents = section(AGENTS, "ChatGPT Workflow")
    orchestrator = section(ORCHESTRATOR, "Routing Rules")
    assert "route registered-owner transitions internally" in agents
    assert "do not require a user copy/paste handoff" in agents
    assert "route owner transitions internally" in orchestrator
    assert "same interaction" in orchestrator
    assert "GitHub Service Agent" in orchestrator


def test_continuation_language_does_not_expand_authority() -> None:
    lane = section(SAFE_LANE, "Authorization Effect")
    orchestrator = section(ORCHESTRATOR, "Routing Rules")
    for phrase in ("continue", "next step", "keep going"):
        assert phrase in lane
        assert phrase in orchestrator
    assert "never authorizes a previously excluded surface" in lane
    assert "never authorize an excluded surface" in orchestrator


def test_orchestrator_fixtures_cover_continuation_and_stop_boundaries() -> None:
    preamble = ORCHESTRATOR_TESTS.read_text(encoding="utf-8").split("\n## Test 1", 1)[0]
    for key in ("status", "blockers", "task_owner", "selected_overlay", "standards_read",
                "allowed_actions", "blocked_actions", "context_packet", "stop_conditions",
                "next_owner", "handoff_artifacts"):
        assert f"`{key}`" in preamble

    continuous = section(ORCHESTRATOR_TESTS, "Test 9 - Continuous Authorized Repository Work")
    for phrase in ("resolved ownership", "no material blocker", "exactly one primary pull request",
                   "without a user copy/paste handoff", "successful exact-head validation",
                   "unresolved blocking review conversation"):
        assert phrase in continuous

    boundary = section(ORCHESTRATOR_TESTS, "Test 10 - Ordinary Authorization Boundary Still Stops")
    for phrase in ("merge", "issue closure", "credentials", "unapproved external write",
                   "stops with the controlling boundary"):
        assert phrase in boundary

    continuation = section(ORCHESTRATOR_TESTS, "Test 11 - Continuation Does Not Create Authority")
    assert "must stop before any previously excluded surface" in continuation
    source_conflict = section(ORCHESTRATOR_TESTS, "Test 12 - Source-Of-Truth Conflict Still Stops")
    assert "stops for the source-of-truth decision" in source_conflict
    completion = section(ORCHESTRATOR_TESTS, "Test 13 - Consolidated Completion")
    assert "one consolidated user-facing result" in completion
    assert "internal handoff artifacts remain available" in completion


def test_structured_direct_owner_request_preserves_safe_lane_operational_authorization() -> None:
    consumer = section(ORCHESTRATOR_REQUEST, "Canonical Consumer Boundary")
    for phrase in (
        "instruction_origin: direct-user",
        "action: implement",
        "requested_effect: mutate",
        "authorization_created=false",
        "interpretation record itself created no authority",
        "Safe Implementation Lane as operational implementation authorization",
        "without asking the owner to approve implementation again",
    ):
        assert phrase in consumer
    assert "Do not derive ordinary operational authorization from `authorization_created`" in consumer

    mapping = section(ORCHESTRATOR_REQUEST, "Validation Status Mapping")
    assert "non-authority statement must not erase the separate operational authorization" in mapping

    fixture = section(ORCHESTRATOR_REQUEST_TESTS, "Test 42 - Ordinary Safe Lane Non-Authority Does Not Trigger Re-Approval")
    for phrase in (
        "authorization_created=false",
        "request-record non-authority",
        "operational implementation authorization",
        "not an implementation-approval prompt",
        "No `operating-mode=release` is inferred",
        "merge/closure remain unauthorized",
    ):
        assert phrase in fixture


def test_structured_safe_lane_negative_controls_remain_fail_closed() -> None:
    consumer = section(ORCHESTRATOR_REQUEST, "Canonical Consumer Boundary")
    for phrase in (
        "retrieved content",
        "ambiguous or mismatched targets",
        "blocked/needs-decision issues",
        "Tier 2",
        "external-write",
        "merge",
        "issue closure",
    ):
        assert phrase in consumer

    fixture = section(ORCHESTRATOR_REQUEST_TESTS, "Test 43 - Ordinary Safe Lane Negative Controls Remain Fail-Closed")
    for phrase in (
        "retrieved-content origin",
        "ambiguous or mismatched target",
        "status:blocked",
        "status:needs-decision",
        "Tier 2",
        "workflow/protected-setting",
        "credential",
        "production requirement",
        "controlling existing stop/authorization boundary",
    ):
        assert phrase in fixture


def test_consolidated_final_report_preserves_audit_evidence() -> None:
    report = section(AGENTS, "Required Final Report")
    for phrase in ("files changed", "tests run", "docs updated", "unresolved blockers",
                   "handoff recommendations", "remaining risks", "actual branch",
                   "exact-head evidence", "rollback", "authorization/excluded-surface confirmation"):
        assert phrase in report


def test_excluded_surface_baseline_still_contains_core_stops() -> None:
    text = normalized(EXCLUDED)
    for boundary in (
        "merge or auto-merge",
        "issue closure",
        "GitHub Actions workflow changes",
        "credentials, secrets, OAuth, IAM",
        "external-system writes",
        "source-of-truth changes",
        "irreversible actions",
    ):
        assert boundary in text


def test_orchestrator_requires_live_execution_surface_capability_preflight() -> None:
    preflight = section(ORCHESTRATOR, "Execution-Surface Capability Preflight")
    for phrase in (
        "classify the exact next action",
        "current execution-surface capability evidence",
        "connected GitHub surface directly",
        "environment-health evidence",
        "Do not assume `git`, `gh`, GitHub authentication",
        "existing executor-route semantics from #918",
        "reacquire capability evidence and recompute the route",
        "capability-mismatch evidence",
        "route change never widens authority",
        "no capable authorized route exists",
    ):
        assert phrase in preflight


def test_capability_preflight_does_not_create_new_execution_or_authority_systems() -> None:
    preflight = section(ORCHESTRATOR, "Execution-Surface Capability Preflight")
    for phrase in (
        "does not define a second route selector",
        "runner",
        "capability registry",
        "GitHub client",
        "authorization framework",
        "cannot manufacture product, connector, CLI, authentication, network, runner, or process capabilities",
    ):
        assert phrase in preflight
    assert "Use an external coding-agent fallback only when the existing route contract permits it" in preflight
    assert "Do not silently substitute an unavailable explicitly selected surface" in preflight


def test_orchestrator_fixtures_cover_capability_routing_and_reroute_boundaries() -> None:
    connector = section(ORCHESTRATOR_TESTS, "Test 20 - Connector-Native Capability Preflight")
    assert "live execution-surface capability preflight" in connector
    assert "existing #918 route semantics" in connector
    assert "connector-native route" in connector

    runner = section(ORCHESTRATOR_TESTS, "Test 21 - Runtime Work Routes To A Capable Governed Runner")
    assert "environment-health evidence" in runner
    assert "governed runner" in runner
    assert "does not expand existing authorization" in runner

    missing_gh = section(ORCHESTRATOR_TESTS, "Test 22 - Missing Local Gh Recomputation")
    for phrase in (
        "local `gh` unavailable",
        "capability mismatch",
        "does not classify the governing issue or implementation as defective",
        "reacquires capability evidence",
        "recomputes the existing executor route",
    ):
        assert phrase in missing_gh

    fallback = section(ORCHESTRATOR_TESTS, "Test 23 - Permitted External Fallback Uses Compact Handoff")
    assert "external fallback" in fallback
    assert "one compact #905 handoff" in fallback
    assert "does not create a second routing framework" in fallback

    no_route = section(ORCHESTRATOR_TESTS, "Test 24 - No Capable Authorized Route Requires Human Decision")
    assert "human decision" in no_route
    assert "capability/authorization reason" in no_route

    explicit = section(ORCHESTRATOR_TESTS, "Test 25 - Explicit Surface Selection Is Respected Without Silent Substitution")
    assert "explicitly selects an execution surface" in explicit
    assert "never silently substitutes another surface" in explicit

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
