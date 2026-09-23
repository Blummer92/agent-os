"""Regression fixture for #2065's lessons-preflight miss."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"


def normalized() -> str:
    return " ".join(AGENTS.read_text(encoding="utf-8").split())


def test_first_substantial_hypothesis_requires_completed_lessons_preflight() -> None:
    workflow = normalized()
    assert "Before forming the first substantial investigation, implementation, or repair hypothesis" in workflow
    assert "run the existing ChatGPT Orchestrator Coding Lessons Learned Preflight" in workflow
    assert "Record the bounded CKR6 outcome" in workflow


def test_preflight_is_consumed_not_merely_inspected() -> None:
    workflow = normalized()
    assert "selected lessons remain advisory-only" in workflow
    assert "When a newly discovered blocker, failure, target-path change, or architecture finding materially changes those signals" in workflow
    assert "re-evaluate the existing preflight before forming the next materially different hypothesis" in workflow


def test_failed_repair_uses_retry_specific_lessons_gate() -> None:
    workflow = normalized()
    assert "When a governed implementation or PR repair attempt remains red or otherwise fails" in workflow
    assert "failed-repair-lesson-reentry.md" in workflow
    assert "Every newly failed attempt re-triggers this step" in workflow
