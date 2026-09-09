from pathlib import Path


def test_bug_discovery_does_not_treat_labels_as_candidate_universe():
    workflow = Path("AGENTS.md").read_text(encoding="utf-8").lower()
    assert "currently open github issues only" in workflow
    assert "reconcile that existing open bug backlog before fresh defect discovery" in workflow
    assert "missing" in workflow or "stale" in workflow
    assert "labels" in workflow
    assert "candidate-local terminal dispositions" in workflow


def test_empty_one_strategy_cannot_end_requested_bug_batch():
    workflow = Path("AGENTS.md").read_text(encoding="utf-8").lower()
    assert "continue until the requested count is worked" in workflow
    assert "reconciled open pool is exhausted" in workflow
