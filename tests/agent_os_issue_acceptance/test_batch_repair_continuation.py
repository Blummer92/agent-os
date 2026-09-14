from scripts.agent_os_issue_acceptance.batch_repair_continuation import (
    RepairCandidateEvidence,
    RepairDisposition,
    evaluate_bulk_repair_continuation,
)


def ev(pr, disposition, reason, shared=False, attempt=None, lesson_admitted=False):
    return RepairCandidateEvidence(pr, disposition, reason, shared, attempt, lesson_admitted)


def test_item_local_matrix_advances_to_later_independent_candidates():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(1, 2, 3, 4, 5, 6, 7, 8, 9),
        evidence=(
            ev(1, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(2, RepairDisposition.BLOCKED, "red-validation", attempt="attempt-pr2-red-1"),
            ev(3, RepairDisposition.BLOCKED, "merge-conflict"),
            ev(4, RepairDisposition.BLOCKED, "missing-review"),
            ev(5, RepairDisposition.REACQUIRE, "stale-head"),
            ev(6, RepairDisposition.BLOCKED, "needs-decision"),
            ev(7, RepairDisposition.BLOCKED, "external-host-owner"),
            ev(8, RepairDisposition.DEFERRED, "pending-ci"),
        ),
    )
    assert result.visited_pull_requests == (1, 2, 3, 4, 5, 6, 7, 8)
    assert result.lesson_reentry_pull_requests == (2,)
    assert result.remaining_pull_requests == (9,)
    assert result.next_action == "reacquire-next-candidate"
    assert result.finite_admission.completion_admissible is False


def test_failed_repair_retry_cannot_be_marked_repaired_before_ckr6_lesson_admission():
    try:
        ev(
            10,
            RepairDisposition.REPAIRED,
            "retry-repair-succeeded",
            attempt="attempt-pr10-red-1",
            lesson_admitted=False,
        )
    except ValueError as error:
        assert "CKR6 retry lesson boundary admission" in str(error)
    else:
        raise AssertionError("failed repair retry must fail closed before CKR6 lesson admission")


def test_failed_repair_retry_is_admissible_only_when_bound_to_exact_attempt():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(11,),
        evidence=(
            ev(
                11,
                RepairDisposition.REPAIRED,
                "retry-repair-succeeded",
                attempt="attempt-pr11-red-2",
                lesson_admitted=True,
            ),
        ),
    )
    assert result.repaired_pull_requests == (11,)
    assert result.lesson_reentry_pull_requests == (11,)
    assert result.next_action == "report-complete-repair-batch"


def test_lesson_admission_without_failed_attempt_identity_fails_closed():
    try:
        ev(12, RepairDisposition.BLOCKED, "red-validation", lesson_admitted=True)
    except ValueError as error:
        assert "bind to one failed repair attempt" in str(error)
    else:
        raise AssertionError("lesson admission must bind to exact failed attempt")


def test_already_terminal_candidate_is_accounted_without_padding():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(20, 21),
        evidence=(ev(20, RepairDisposition.ALREADY_TERMINAL, "already-closed"),),
    )
    assert result.already_terminal_pull_requests == (20,)
    assert result.remaining_pull_requests == (21,)
    assert len(result.visited_pull_requests) == 1


def test_shared_validation_outage_halts_with_exact_reason():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(30, 31, 32),
        evidence=(
            ev(30, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(31, RepairDisposition.BLOCKED, "shared-validation-outage", True),
        ),
    )
    assert result.next_action == "halt-shared-blocker"
    assert result.finite_admission.completion_admissible is True
    assert "shared-terminal-blocker" in result.finite_admission.reason_codes
    assert result.remaining_pull_requests == (32,)


def test_deferred_and_stale_candidates_are_revisited_before_completion():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(40, 41, 42),
        evidence=(
            ev(40, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(41, RepairDisposition.DEFERRED, "pending-ci"),
            ev(42, RepairDisposition.REACQUIRE, "stale-head"),
        ),
    )
    assert result.remaining_pull_requests == ()
    assert result.next_action == "revisit-deferred-or-stale-candidates"
    assert result.deferred_pull_requests == (41,)
    assert result.reacquire_pull_requests == (42,)


def test_all_final_dispositions_produce_complete_accounting():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(50, 51, 52),
        evidence=(
            ev(50, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(51, RepairDisposition.BLOCKED, "needs-decision"),
            ev(52, RepairDisposition.ALREADY_TERMINAL, "already-merged"),
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
            requested_pull_requests=(60, 61),
            evidence=(
                ev(60, RepairDisposition.BLOCKED, "red-validation", attempt="attempt-pr60-red-1"),
                ev(60, RepairDisposition.REPAIRED, "repair-succeeded"),
            ),
        )
    except ValueError as error:
        assert "at most once" in str(error)
    else:
        raise AssertionError("duplicate evidence must fail")

    try:
        evaluate_bulk_repair_continuation(
            requested_pull_requests=(60, 61),
            evidence=(ev(62, RepairDisposition.BLOCKED, "external-host-owner"),),
        )
    except ValueError as error:
        assert "outside the frozen target set" in str(error)
    else:
        raise AssertionError("out-of-batch evidence must fail")
