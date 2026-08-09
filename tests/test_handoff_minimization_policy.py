"""Contract tests for continuous governed execution under the Safe Implementation Lane."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"
AGENTS = ROOT / "AGENTS.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
ORCHESTRATOR_TESTS = ROOT / "07_Agent_Tests/chatgpt-orchestrator.tests.md"
EXCLUDED = ROOT / "01_Shared_Standards/github/excluded-surface-baseline.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_safe_lane_treats_owner_transition_as_internal_routing() -> None:
    text = normalized(SAFE_LANE)
    for phrase in (
        "registered-owner transition is internal routing",
        "not by itself a user-visible handoff or stop",
        "continue in the same interaction",
        "without a new user prompt",
        "one consolidated user-facing result",
    ):
        assert phrase in text


def test_continuous_routing_preserves_owner_and_authority_boundaries() -> None:
    text = normalized(SAFE_LANE)
    for phrase in (
        "Ownership and authority do not transfer",
        "GitHub Service Agent stays the sole repository writer",
        "QA / Test Agent retains validation-evidence ownership",
        "never authorizes a previously excluded surface",
    ):
        assert phrase in text


def test_entrypoint_and_orchestrator_do_not_surface_owner_changes_by_default() -> None:
    agents = normalized(AGENTS)
    orchestrator = normalized(ORCHESTRATOR)
    assert "route registered-owner transitions internally" in agents
    assert "do not require a user copy/paste handoff" in agents
    assert "route owner transitions internally" in orchestrator
    assert "same interaction" in orchestrator
    assert "GitHub Service Agent" in orchestrator


def test_continuation_language_does_not_expand_authority() -> None:
    lane = normalized(SAFE_LANE)
    orchestrator = normalized(ORCHESTRATOR)
    for phrase in ("continue", "next step", "keep going"):
        assert phrase in lane
        assert phrase in orchestrator
    assert "never authorizes a previously excluded surface" in lane
    assert "never authorize an excluded surface" in orchestrator


def test_orchestrator_fixtures_cover_continuation_and_stop_boundaries() -> None:
    text = normalized(ORCHESTRATOR_TESTS)
    for title in (
        "Test 9 - Continuous Authorized Repository Work",
        "Test 10 - Real Authorization Boundary Still Stops",
        "Test 11 - Continuation Does Not Create Authority",
        "Test 12 - Source-Of-Truth Conflict Still Stops",
        "Test 13 - Consolidated Completion",
    ):
        assert title in text
    for boundary in ("merge", "issue closure", "credentials", "unapproved external write"):
        assert boundary in text


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
