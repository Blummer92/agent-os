from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def _normalized() -> str:
    return " ".join(OVERLAY.read_text(encoding="utf-8").split())


def test_head_movement_is_reacquired_and_classified_before_stopping() -> None:
    text = _normalized()
    assert "do not classify head movement alone as foreign-active work or a terminal blocker" in text
    assert "Reacquire the exact PR, new head, base, authorization, scope, changed-path evidence" in text
    assert "canonical Scheduler lease evidence" in text
    assert "HEAD_ADVANCED" in text
    assert "ResumePlan" in text


def test_compatible_concurrent_work_continues_without_user_restart() -> None:
    text = _normalized()
    assert "Continue automatically when the new head is the same authorized lineage" in text
    assert "concurrent change is non-conflicting" in text
    assert "already satisfies the intended repair" in text
    assert "bounded repair to be replayed on the new head" in text


def test_stale_or_conflicting_concurrent_work_remains_fail_closed() -> None:
    text = _normalized()
    for phrase in (
        "Never write against the stale head",
        "force-replace the newer head",
        "reuse stale exact-head validation",
        "Same-file or same-invariant conflict",
        "unknown lineage",
        "active/ambiguous conflicting lease",
    ):
        assert phrase in text


def test_concurrent_collision_is_item_local_in_finite_campaign() -> None:
    text = _normalized()
    assert "item-local in a finite campaign" in text
    assert "independently actionable later items continue" in text


def test_changed_head_is_not_a_stop_condition_by_itself() -> None:
    text = _normalized()
    assert "A changed PR head by itself is not such a stop" in text
    assert "first reacquire and classify it" in text
    assert "Scheduler lease/currentness contracts" in text
