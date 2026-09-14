from pathlib import Path


AGENTS = Path("AGENTS.md")


def test_subordinate_mutation_and_diagnostics_are_not_parent_completion():
    text = AGENTS.read_text(encoding="utf-8")
    assert "Diagnosis alone is never completion" in text
    assert "successful subordinate GitHub mutation" in text
    assert "never as parent-mission completion by itself" in text
    assert "Continue the still-authorized parent mission automatically" in text


def test_recoverable_failure_requires_reentry_not_silent_stop():
    text = AGENTS.read_text(encoding="utf-8")
    assert "When a governed implementation or PR repair attempt remains red or otherwise fails" in text
    assert "failed-repair-lesson-reentry.md" in text
    assert "reacquire mutable GitHub state before continuing" in text


def test_progress_rendering_cannot_be_completion_authority():
    # The authoritative completion rule is repository/mission evidence, not UI state.
    text = AGENTS.read_text(encoding="utf-8")
    assert "current work completed or advanced" in text
    assert "specific authorization/governance/external-capability blocker" in text
    assert "manual review required" in text
