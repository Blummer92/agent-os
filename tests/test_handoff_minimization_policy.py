"""Contract tests for continuous governed execution under the Safe Implementation Lane."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
ORCHESTRATOR_TESTS = ROOT / "07_Agent_Tests/chatgpt-orchestrator.tests.md"
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

    boundary = section(ORCHESTRATOR_TESTS, "Test 10 - Real Authorization Boundary Still Stops")
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
