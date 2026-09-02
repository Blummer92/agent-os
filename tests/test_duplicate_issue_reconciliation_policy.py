"""Regression guards for #1616 duplicate-issue reconciliation.

The repository already owns duplicate disposition in the issue lifecycle standard,
continuation/routing in the ChatGPT Orchestrator overlay, and lifecycle mutation
authority in the canonical lifecycle guard. This fixture makes their composition
machine-testable without introducing a second duplicate detector or lifecycle.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "01_Shared_Standards/github/issue-lifecycle-standard.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"
LIFECYCLE_GUARD = ROOT / "scripts/agent_os_issue_acceptance/lifecycle_mutation_guard.py"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    marker = f"## {heading}\n"
    assert marker in text
    body = text.split(marker, 1)[1].split("\n## ", 1)[0]
    return " ".join(body.split())


def test_duplicate_disposition_has_one_canonical_lifecycle_owner() -> None:
    closure = section(LIFECYCLE, "Closure And Supersession")
    assert "Close duplicates with a pointer to the canonical item." in closure
    assert "Preserve links" in closure


def test_duplicate_classification_is_not_a_user_handoff_when_bounded_work_remains() -> None:
    routing = section(ORCHESTRATOR, "Routing Rules")
    assert "route owner transitions internally" in routing
    assert "Preserve internal handoff artifacts and owner accountability" in routing
    assert "Route repository writes only to the GitHub Service Agent." in routing


def test_duplicate_closure_reuses_canonical_authority_guard() -> None:
    guard = normalized(LIFECYCLE_GUARD)
    assert '"close-issue"' in guard
    assert "authorization-not-authorized" in guard
    assert "issue-state-changed" in guard
    assert "LifecycleStateSnapshot" in guard


def test_duplicate_reconciliation_does_not_infer_closure_authority() -> None:
    safe_lane = normalized(SAFE_LANE)
    routing = section(ORCHESTRATOR, "Routing Rules")
    assert "ordinary Safe Implementation Lane" in safe_lane or "Ordinary Safe Implementation Lane" in safe_lane
    assert "does not authorize merge" in safe_lane
    assert "issue closure" in safe_lane
    assert "Mission continuation never widens authority" in routing
    assert "cannot infer merge, issue closure" in routing


def test_1613_to_1611_regression_shape_is_covered_without_second_architecture() -> None:
    """Pin the #1613 -> #1611 failure as a cross-contract composition."""
    all_text = " ".join(normalized(path) for path in (LIFECYCLE, ORCHESTRATOR, SAFE_LANE, LIFECYCLE_GUARD))
    for required in (
        "Close duplicates with a pointer to the canonical item",
        "route owner transitions internally",
        "GitHub Service Agent",
        "close-issue",
        "authorization-not-authorized",
        "issue-state-changed",
    ):
        assert required in all_text
