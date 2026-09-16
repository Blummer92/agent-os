from pathlib import Path

from scripts.agent_os_execution_interface.finite_batch_admission import evaluate_finite_batch_admission


def test_bounded_bug_work_reconciles_open_candidates_before_exclusion():
    text = Path("AGENTS.md").read_text(encoding="utf-8").lower()
    assert "reconcile that existing open bug backlog" in text
    assert "exclude stale, duplicate, already-fixed" in text
    assert "use eligible existing bugs first" in text
    assert "do not create issues merely to pad a requested count" in text


def test_item_local_non_actionable_candidate_does_not_complete_parent_batch():
    result = evaluate_finite_batch_admission(
        requested_count=2,
        delivered_count=0,
        reconciled_candidate_count=1,
        population_exhausted=False,
        shared_blocker=False,
    )
    assert result.completion_admissible is False
    assert result.next_action == "continue-candidate-cursor"
    assert result.reason_codes == (
        "requested-count-not-satisfied",
        "population-not-exhausted",
    )
