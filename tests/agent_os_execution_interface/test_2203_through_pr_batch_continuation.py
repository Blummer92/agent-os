from scripts.agent_os_execution_interface.finite_batch_admission import evaluate_finite_batch_admission
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

    batch = evaluate_finite_batch_admission(
        requested_count=10,
        delivered_count=0,
        reconciled_candidate_count=1,
        population_exhausted=False,
        shared_blocker=False,
    )
    assert batch.completion_admissible is False
    assert batch.next_action == "continue-candidate-cursor"


def test_verified_pr_does_not_finish_ten_item_batch_early():
    completion = evaluate_mission_completion_admission(
        repository="Blummer92/agent-os", issue_number=2203,
        branch_exists=True, implementation_commit_count=2,
        draft_pr_exists=True, canonical_pr_readback_verified=True,
        capable_route_available=True, subordinate_writes_only=False,
    )
    assert completion.completion_admissible is True

    batch = evaluate_finite_batch_admission(
        requested_count=10,
        delivered_count=1,
        reconciled_candidate_count=1,
        population_exhausted=False,
        shared_blocker=False,
    )
    assert batch.completion_admissible is False
    assert batch.next_action == "continue-candidate-cursor"
