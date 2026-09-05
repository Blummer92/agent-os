"""Regression contract for #1901 failed-repair CKR6 consumer wiring."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "02_Agent_Overlays/_common-overlay-rules.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
STANDARD = ROOT / "01_Shared_Standards/global-engineering/failed-repair-lesson-reentry.md"
REPAIR_CONTRACT = ROOT / "08_Tooling/agent-memory-context-manager/CKR6_REPAIR_ACTIVATION.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_orchestrator_inherits_failed_repair_reentry_standard() -> None:
    orchestrator = normalized(ORCHESTRATOR)
    common = normalized(COMMON)
    assert "See `_common-overlay-rules.md`" in orchestrator
    assert "01_Shared_Standards/global-engineering/failed-repair-lesson-reentry.md" in common


def test_failed_repair_requires_existing_ckr6_activation_before_mutation() -> None:
    text = normalized(STANDARD)
    for phrase in (
        "preserve that attempt as the current `FailedRepairAttempt`",
        "increase diagnostic resolution",
        "activate_repair_retry_lessons(...)` seam",
        "`consumed`, `not-material`, or `unavailable-or-failed`",
        "`RepairRetryBoundaryPlan` to admit mutation",
        "reacquire mutable GitHub issue/PR/head/check state",
        "Every newly failed attempt creates a new CKR6 retry obligation",
    ):
        assert phrase in text


def test_retry_policy_reuses_existing_runtime_and_preserves_github_authority() -> None:
    text = normalized(STANDARD)
    runtime = normalized(REPAIR_CONTRACT)
    assert "Do not build a second lesson selector, Notion reader, retry engine, or repair state model" in text
    assert "repair_lesson_activation.py" in text
    assert "GitHub governance, issue/PR state, authorization, repository code, tests, and exact-head validation remain authoritative" in text
    assert "activate_repair_retry_lessons(...)" in runtime
    assert "Every new failed attempt creates a new retry-specific CKR6 obligation" in runtime


def test_subordinate_bug_capture_does_not_end_parent_repair_mission() -> None:
    text = normalized(STANDARD)
    for phrase in (
        "bookkeeping is subordinate to the active parent repair mission",
        "continue the parent mission from its current retry boundary",
        "Issue creation alone is not a terminal repair state",
    ):
        assert phrase in text
