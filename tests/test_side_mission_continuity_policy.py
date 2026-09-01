"""Regression guards for #1649 bounded side-mission continuity."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "01_Shared_Standards/github/side-mission-continuity.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"
TOOL_CONTINUATION = ROOT / "01_Shared_Standards/github/tool-discovery-continuation.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_bounded_side_mission_does_not_replace_primary_issue() -> None:
    contract = normalized(CONTRACT)
    for phrase in (
        "A side conversation is not, by itself, a mission switch",
        "preserve primary lineage",
        "reacquire live GitHub state for primary lineage",
        "resume primary lineage",
        "does not complete the primary mission",
    ):
        assert phrase in contract


def test_live_1543_side_bug_reproduction_contract_is_deterministic() -> None:
    contract = normalized(CONTRACT)
    assert "exact issue number and open/closed state" in contract
    assert "canonical PR identity when one exists" in contract
    assert "branch and current head when recoverable" in contract
    assert "Do not silently select unrelated work" in contract
    assert "Do not require the repository owner to restate an unambiguously recoverable primary issue" in contract


def test_side_bug_blocker_returns_to_primary_lineage() -> None:
    contract = normalized(CONTRACT)
    assert "carry that blocker back to the exact primary lineage" in contract
    assert "primary issue with an explicit blocker and clearing condition" in contract
    assert "not silent abandonment" in contract


def test_explicit_reprioritization_replaces_automatic_return() -> None:
    contract = normalized(CONTRACT)
    for phrase in ("switch to", "stop", "work on this instead"):
        assert phrase in contract
    assert "Do not automatically return after an intentional mission switch" in contract


def test_quick_question_retains_primary_continuation_point() -> None:
    contract = normalized(CONTRACT)
    assert "A quick conceptual question" in contract
    assert "does not count as reprioritization by itself" in contract


def test_multiple_side_bugs_resume_original_primary_once() -> None:
    contract = normalized(CONTRACT)
    assert "Several bounded side missions may occur in sequence" in contract
    assert "resume it once after the chain reaches its bounded terminal point" in contract
    assert "Do not emit duplicate return handoffs" in contract


def test_ambiguity_fails_closed() -> None:
    contract = normalized(CONTRACT)
    assert "fail closed with ambiguity when more than one suspended primary lineage is genuinely plausible" in contract


def test_neighboring_contract_ownership_is_preserved() -> None:
    contract = normalized(CONTRACT)
    for issue in ("#1648", "#1647", "#1608", "#1524"):
        assert issue in contract
    assert "These contracts compose" in contract
    assert "does not duplicate their state machines or authority models" in contract
    assert "successful tool/schema/capability discovery" in normalized(TOOL_CONTINUATION)
    assert "Mission continuation never widens authority" in normalized(ORCHESTRATOR)
    assert "discovery of one existing valid issue-linked branch" in normalized(SAFE_LANE)


def test_continuity_never_widens_authority() -> None:
    contract = normalized(CONTRACT)
    for phrase in (
        "merge",
        "issue closure",
        "workflow/protected-setting mutation",
        "credentials/IAM",
        "production",
        "external write",
        "governed-field mutation",
    ):
        assert phrase in contract
    assert "Side-bug evidence capture under #1647 does not consume or widen implementation authorization" in contract


def test_no_persistent_autonomous_task_architecture() -> None:
    contract = normalized(CONTRACT)
    for forbidden in (
        "task manager",
        "queue",
        "hidden mission database",
        "second issue tracker",
        "background worker",
        "Scheduler",
        "authorization model",
    ):
        assert forbidden in contract
    assert "Do not create persistent repository runtime state" in contract
    assert "rather than adding repository runtime persistence or an autonomous task engine" in contract
