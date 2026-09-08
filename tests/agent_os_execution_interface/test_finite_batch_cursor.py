from scripts.agent_os_execution_interface.finite_batch_cursor import advance_finite_batch


def test_pr_then_local_disposition_then_residual_investigation_continues_without_parent_completion():
    first = advance_finite_batch(current_index=0, candidate_count=3, candidate_disposition="pr-created")
    assert first.action == "advance-next-candidate" and first.next_index == 1
    second = advance_finite_batch(current_index=1, candidate_count=3, candidate_disposition="already-fixed")
    assert second.action == "advance-next-candidate" and second.next_index == 2
    third = advance_finite_batch(current_index=2, candidate_count=3, candidate_disposition="needs-residual-gap-proof")
    assert third.action == "investigate-current-candidate" and third.parent_complete is False


def test_last_candidate_local_completion_exhausts_batch():
    result = advance_finite_batch(current_index=2, candidate_count=3, candidate_disposition="no-residual-gap")
    assert result.action == "batch-exhausted"
    assert result.parent_complete is True


def test_genuine_shared_blocker_stops_parent_without_claiming_completion():
    result = advance_finite_batch(current_index=1, candidate_count=4, candidate_disposition="authorization-blocked")
    assert result.action == "stop-parent-batch"
    assert result.parent_complete is False
