from scripts.agent_os_execution_interface.finite_batch_cursor import advance_finite_batch
from scripts.agent_os_execution_interface.mission_completion_admission import evaluate_mission_completion_admission


def test_code_commit_without_pr_cannot_finish_candidate_or_parent_batch():
    completion = evaluate_mission_completion_admission(
        repository="Blummer92/agent-os", issue_number=2203,
        branch_exists=True, implementation_commit_count=1,
        draft_pr_exists=False, canonical_pr_readback_verified=False,
        capable_route_available=True, subordinate_writes_only=False,
    )
    assert completion.completion_admissible is False
    assert completion.next_action == "continue-same-lineage-on-capable-implementation-route"

    cursor = advance_finite_batch(current_index=0, candidate_count=10, candidate_disposition="needs-residual-gap-proof")
    assert cursor.parent_complete is False
    assert cursor.next_index == 0


def test_verified_pr_advances_but_does_not_finish_ten_item_batch_early():
    completion = evaluate_mission_completion_admission(
        repository="Blummer92/agent-os", issue_number=2203,
        branch_exists=True, implementation_commit_count=2,
        draft_pr_exists=True, canonical_pr_readback_verified=True,
        capable_route_available=True, subordinate_writes_only=False,
    )
    assert completion.completion_admissible is True

    cursor = advance_finite_batch(current_index=0, candidate_count=10, candidate_disposition="pr-created")
    assert cursor.action == "advance-next-candidate"
    assert cursor.next_index == 1
    assert cursor.parent_complete is False
