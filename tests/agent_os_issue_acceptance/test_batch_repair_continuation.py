from scripts.agent_os_issue_acceptance.batch_repair_continuation import (
    RepairCandidateEvidence,
    RepairDisposition,
    evaluate_bulk_repair_continuation,
)


def ev(pr, disposition, reason, shared=False):
    return RepairCandidateEvidence(pr, disposition, reason, shared)


def test_item_local_matrix_advances_to_later_independent_candidates():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(1, 2, 3, 4, 5, 6, 7, 8, 9),
        evidence=(
            ev(1, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(2, RepairDisposition.BLOCKED, "red-validation"),
            ev(3, RepairDisposition.BLOCKED, "merge-conflict"),
            ev(4, RepairDisposition.BLOCKED, "missing-review"),
            ev(5, RepairDisposition.REACQUIRE, "stale-head"),
            ev(6, RepairDisposition.BLOCKED, "needs-decision"),
            ev(7, RepairDisposition.BLOCKED, "external-host-owner"),
            ev(8, RepairDisposition.DEFERRED, "pending-ci"),
        ),
    )
    assert result.visited_pull_requests == (1, 2, 3, 4, 5, 6, 7, 8)
    assert result.remaining_pull_requests == (9,)
    assert result.next_action == "reacquire-next-candidate"
    assert result.finite_admission.completion_admissible is False


def test_already_terminal_candidate_is_accounted_without_padding():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(10, 11),
        evidence=(ev(10, RepairDisposition.ALREADY_TERMINAL, "already-closed"),),
    )
    assert result.already_terminal_pull_requests == (10,)
    assert result.remaining_pull_requests == (11,)
    assert len(result.visited_pull_requests) == 1


def test_shared_validation_outage_halts_with_exact_reason():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(20, 21, 22),
        evidence=(
            ev(20, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(21, RepairDisposition.BLOCKED, "shared-validation-outage", True),
        ),
    )
    assert result.next_action == "halt-shared-blocker"
    assert result.finite_admission.completion_admissible is True
    assert "shared-terminal-blocker" in result.finite_admission.reason_codes
    assert result.remaining_pull_requests == (22,)


def test_deferred_and_stale_candidates_are_revisited_before_completion():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(30, 31, 32),
        evidence=(
            ev(30, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(31, RepairDisposition.DEFERRED, "pending-ci"),
            ev(32, RepairDisposition.REACQUIRE, "stale-head"),
        ),
    )
    assert result.remaining_pull_requests == ()
    assert result.next_action == "revisit-deferred-or-stale-candidates"
    assert result.deferred_pull_requests == (31,)
    assert result.reacquire_pull_requests == (32,)


def test_all_final_dispositions_produce_complete_accounting():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(40, 41, 42),
        evidence=(
            ev(40, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(41, RepairDisposition.BLOCKED, "needs-decision"),
            ev(42, RepairDisposition.ALREADY_TERMINAL, "already-merged"),
        ),
    )
    assert result.remaining_pull_requests == ()
    assert result.next_action == "report-complete-repair-batch"
    assert result.finite_admission.completion_admissible is True
    assert len(result.visited_pull_requests) == len(result.requested_pull_requests)
    assert result.mutation_authorized is False
    assert result.merge_authorized is False
    assert result.side_effects_performed is False


def test_duplicate_or_out_of_batch_evidence_fails_closed():
    try:
        evaluate_bulk_repair_continuation(
            requested_pull_requests=(50, 51),
            evidence=(
                ev(50, RepairDisposition.BLOCKED, "red-validation"),
                ev(50, RepairDisposition.REPAIRED, "repair-succeeded"),
            ),
        )
    except ValueError as error:
        assert "at most once" in str(error)
    else:
        raise AssertionError("duplicate evidence must fail")

    try:
        evaluate_bulk_repair_continuation(
            requested_pull_requests=(50, 51),
            evidence=(ev(52, RepairDisposition.BLOCKED, "external-host-owner"),),
        )
    except ValueError as error:
        assert "outside the frozen target set" in str(error)
    else:
        raise AssertionError("out-of-batch evidence must fail")
