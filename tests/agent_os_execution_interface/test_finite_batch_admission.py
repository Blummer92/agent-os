import pytest

from scripts.agent_os_execution_interface.finite_batch_admission import evaluate_finite_batch_admission


def test_exact_three_of_ten_failure_must_continue_without_exhaustion():
    result = evaluate_finite_batch_admission(
        requested_count=10, delivered_count=3, reconciled_candidate_count=17,
        population_exhausted=False, shared_blocker=False,
    )
    assert result.completion_admissible is False
    assert result.next_action == "continue-candidate-cursor"
    assert result.reason_codes == ("requested-count-not-satisfied", "population-not-exhausted")


def test_requested_count_is_terminal_when_satisfied():
    result = evaluate_finite_batch_admission(requested_count=10, delivered_count=10, reconciled_candidate_count=24, population_exhausted=False, shared_blocker=False)
    assert result.completion_admissible is True
    assert result.next_action == "report-requested-count-delivered"


def test_proven_population_exhaustion_can_report_honest_shortfall():
    result = evaluate_finite_batch_admission(requested_count=10, delivered_count=7, reconciled_candidate_count=40, population_exhausted=True, shared_blocker=False)
    assert result.completion_admissible is True
    assert "requested-count-shortfall" in result.reason_codes


def test_shared_blocker_can_report_honest_shortfall():
    result = evaluate_finite_batch_admission(requested_count=10, delivered_count=3, reconciled_candidate_count=8, population_exhausted=False, shared_blocker=True)
    assert result.completion_admissible is True
    assert result.next_action == "report-shared-terminal-blocker-and-shortfall"


@pytest.mark.parametrize("requested,delivered", [(0, 0), (10, 11), (10, -1)])
def test_invalid_counts_fail_closed(requested, delivered):
    with pytest.raises(ValueError):
        evaluate_finite_batch_admission(requested_count=requested, delivered_count=delivered, reconciled_candidate_count=0, population_exhausted=False, shared_blocker=False)
