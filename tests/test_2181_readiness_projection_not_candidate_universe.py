from pathlib import Path


def test_bounded_bug_work_reconciles_open_candidates_before_exclusion():
    text = Path("AGENTS.md").read_text(encoding="utf-8").lower()
    assert "reconcile that existing open bug backlog" in text
    assert "exclude stale, duplicate, already-fixed" in text
    assert "use eligible existing bugs first" in text
    assert "do not create issues merely to pad a requested count" in text


def test_item_local_non_actionable_candidate_advances_parent_batch():
    from scripts.agent_os_execution_interface.finite_batch_cursor import advance_finite_batch
    for disposition in ("already-fixed", "duplicate", "external-owner", "separately-gated"):
        result = advance_finite_batch(current_index=0, candidate_count=2, candidate_disposition=disposition)
        assert result.action == "advance-next-candidate"
        assert result.parent_complete is False
