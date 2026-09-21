from scripts.agent_os_issue_acceptance.batch_repair_continuation import (
    RepairCandidateEvidence,
    RepairDisposition,
    RepairRetryBoundaryEvidence,
    evaluate_bulk_repair_continuation,
)


def boundary(attempt, admitted):
    return RepairRetryBoundaryEvidence(
        failed_attempt_id=attempt,
        mutation_admissible=admitted,
        blocking_attempt_id=None if admitted else attempt,
        reason_codes=(
            "retry-ckr6-reentry-consumed" if admitted else "retry-ckr6-reentry-required",
        ),
    )


def ev(
    pr,
    disposition,
    reason,
    shared=False,
    attempt=None,
    retry_boundary=None,
    mutated=False,
    *,
    shared_key=None,
    shared_owner=None,
    repair_available=False,
    repair_completed=False,
):
    return RepairCandidateEvidence(
        pr,
        disposition,
        reason,
        shared,
        attempt,
        retry_boundary,
        mutated,
        shared_key,
        shared_owner,
        repair_available,
        repair_completed,
    )


def test_item_local_matrix_advances_and_marks_failed_attempt_as_lesson_required():
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
    assert result.lesson_reentry_required_pull_requests == (2,)
    assert result.lesson_reentry_admitted_pull_requests == ()
    assert result.remaining_pull_requests == (9,)
    assert result.next_action == "reacquire-next-candidate"


def test_retry_mutation_requires_exact_admitted_ckr6_boundary():
    attempt = "attempt-pr10-red-1"
    for retry_boundary in (None, boundary(attempt, False)):
        try:
            ev(
                10,
                RepairDisposition.BLOCKED,
                "retry-still-red",
                attempt=attempt,
                retry_boundary=retry_boundary,
                mutated=True,
            )
        except ValueError as error:
            assert "retry mutation" in str(error)
        else:
            raise AssertionError("retry mutation must fail closed without admitted CKR6 boundary")


def test_admitted_boundary_allows_retry_even_when_retry_fails_again():
    attempt = "attempt-pr11-red-1"
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(11,),
        evidence=(
            ev(
                11,
                RepairDisposition.BLOCKED,
                "retry-still-red",
                attempt=attempt,
                retry_boundary=boundary(attempt, True),
                mutated=True,
            ),
        ),
    )
    assert result.lesson_reentry_admitted_pull_requests == (11,)
    assert result.blocked_pull_requests == (11,)


def test_failed_retry_can_be_repaired_only_after_admitted_mutation():
    attempt = "attempt-pr12-red-2"
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(12,),
        evidence=(
            ev(
                12,
                RepairDisposition.REPAIRED,
                "retry-repair-succeeded",
                attempt=attempt,
                retry_boundary=boundary(attempt, True),
                mutated=True,
            ),
        ),
    )
    assert result.repaired_pull_requests == (12,)
    assert result.lesson_reentry_admitted_pull_requests == (12,)


def test_boundary_must_bind_to_exact_failed_attempt():
    try:
        ev(
            13,
            RepairDisposition.BLOCKED,
            "red-validation",
            attempt="attempt-pr13-red-2",
            retry_boundary=boundary("attempt-pr13-red-1", True),
        )
    except ValueError as error:
        assert "exact failed repair attempt" in str(error)
    else:
        raise AssertionError("stale retry boundary must not satisfy a newer failed attempt")


def test_blocked_boundary_must_name_exact_blocking_attempt():
    try:
        RepairRetryBoundaryEvidence(
            failed_attempt_id="attempt-pr14-red-2",
            mutation_admissible=False,
            blocking_attempt_id="attempt-pr14-red-1",
            reason_codes=("retry-ckr6-reentry-required",),
        )
    except ValueError as error:
        assert "exact failed attempt" in str(error)
    else:
        raise AssertionError("blocked boundary must identify its exact failed attempt")


def test_already_terminal_candidate_is_accounted_without_padding():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(20, 21),
        evidence=(ev(20, RepairDisposition.ALREADY_TERMINAL, "already-closed"),),
    )
    assert result.already_terminal_pull_requests == (20,)
    assert result.remaining_pull_requests == (21,)


def test_unrepairable_shared_validation_outage_halts_with_exact_reason():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(30, 31, 32),
        evidence=(
            ev(30, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(31, RepairDisposition.BLOCKED, "shared-validation-outage", True),
        ),
    )
    assert result.next_action == "halt-shared-blocker"
    assert result.finite_admission.completion_admissible is True
    assert result.remaining_pull_requests == (32,)


def test_five_pr_shared_main_health_blocker_routes_one_canonical_repair():
    affected = (2658, 2655, 2653, 2649, 2646)
    evidence = tuple(
        ev(
            pr,
            RepairDisposition.BLOCKED,
            "main-health-validation-blocked",
            True,
            shared_key="exact-current-main-health",
            shared_owner="issue:#2652",
            repair_available=True,
        )
        for pr in affected
    )
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=affected,
        evidence=evidence,
    )
    assert result.shared_blocker_pull_requests == affected
    assert result.shared_blocker_key == "exact-current-main-health"
    assert result.shared_repair_owner == "issue:#2652"
    assert result.shared_repair_available is True
    assert result.next_action == "advance-shared-repair"
    assert result.finite_admission.completion_admissible is False
    assert result.finite_admission.shared_blocker is False
    # The candidates are reconciled but not delivered. Counting them as
    # delivered makes `delivered_count == requested_count` short-circuit the
    # finite-batch admission to `completion_admissible=True` before
    # `population_exhausted` is consulted, reporting a batch that still owes
    # `advance-shared-repair` as complete.
    assert result.finite_admission.reconciled_candidate_count == len(affected)
    assert result.finite_admission.delivered_count == 0


def test_completed_shared_repair_requires_all_affected_prs_to_be_reacquired():
    affected = (2658, 2655, 2653, 2649, 2646)
    evidence = tuple(
        ev(
            pr,
            RepairDisposition.BLOCKED,
            "main-health-validation-blocked",
            True,
            shared_key="exact-current-main-health",
            shared_owner="issue:#2652",
            repair_available=True,
            repair_completed=True,
        )
        for pr in affected
    )
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=affected,
        evidence=evidence,
    )
    assert result.next_action == "reacquire-shared-repair-candidates"
    assert result.finite_admission.completion_admissible is False
    assert result.shared_blocker_pull_requests == affected


def test_shared_candidates_must_agree_on_canonical_repair_identity():
    try:
        evaluate_bulk_repair_continuation(
            requested_pull_requests=(70, 71),
            evidence=(
                ev(
                    70,
                    RepairDisposition.BLOCKED,
                    "main-health-validation-blocked",
                    True,
                    shared_key="main-health",
                    shared_owner="issue:#2652",
                    repair_available=True,
                ),
                ev(
                    71,
                    RepairDisposition.BLOCKED,
                    "main-health-validation-blocked",
                    True,
                    shared_key="main-health",
                    shared_owner="issue:#2651",
                    repair_available=True,
                ),
            ),
        )
    except ValueError as error:
        assert "one canonical blocker and repair state" in str(error)
    else:
        raise AssertionError("conflicting shared repair owners must fail closed")


def test_deferred_and_stale_candidates_are_revisited_before_completion():
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(40, 41, 42),
        evidence=(
            ev(40, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(41, RepairDisposition.DEFERRED, "pending-ci"),
            ev(42, RepairDisposition.REACQUIRE, "stale-head"),
        ),
    )
    assert result.next_action == "revisit-deferred-or-stale-candidates"
    assert result.deferred_pull_requests == (41,)
    assert result.reacquire_pull_requests == (42,)


def test_all_final_dispositions_produce_complete_accounting_without_authority():
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
    assert result.mutation_authorized is False
    assert result.merge_authorized is False
    assert result.side_effects_performed is False


def test_duplicate_or_out_of_batch_evidence_fails_closed():
    try:
        evaluate_bulk_repair_continuation(
            requested_pull_requests=(60, 61),
            evidence=(
                ev(60, RepairDisposition.BLOCKED, "red-validation"),
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


# -- #2349: execution loop finished is not requested work delivered ------------


def test_2349_blocked_candidates_are_traversed_not_delivered():
    """The headline case: nothing was repaired, yet the batch reported delivery.

    Three requested PRs, every one blocked item-local. Traversal is complete, so
    the loop is finished -- but no requested work was delivered. Counting
    traversal as delivery made the canonical finite-batch owner answer
    ``requested-count-satisfied``.
    """
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(1, 2, 3),
        evidence=(
            ev(1, RepairDisposition.BLOCKED, "needs-decision"),
            ev(2, RepairDisposition.BLOCKED, "needs-decision"),
            ev(3, RepairDisposition.BLOCKED, "needs-decision"),
        ),
    )
    admission = result.finite_admission

    assert admission.delivered_count == 0
    assert admission.reconciled_candidate_count == 3
    assert "requested-count-shortfall" in admission.reason_codes
    assert admission.next_action == "report-proven-population-exhaustion-and-shortfall"


def test_2349_already_terminal_candidates_are_traversed_not_delivered():
    """An already-merged candidate advances the cursor; it delivers nothing."""
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(1, 2, 3),
        evidence=(
            ev(1, RepairDisposition.ALREADY_TERMINAL, "merged"),
            ev(2, RepairDisposition.ALREADY_TERMINAL, "merged"),
            ev(3, RepairDisposition.ALREADY_TERMINAL, "merged"),
        ),
    )

    assert result.finite_admission.delivered_count == 0
    assert "requested-count-shortfall" in result.finite_admission.reason_codes


def test_2349_deferred_candidates_leave_the_population_unexhausted():
    """A deferred candidate still has an executable next action.

    The loop's own terminal chain already says
    ``revisit-deferred-or-stale-candidates``; before this repair the canonical
    owner disagreed with it and said the requested count was satisfied.
    """
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(1, 2, 3),
        evidence=(
            ev(1, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(2, RepairDisposition.DEFERRED, "pending-ci"),
            ev(3, RepairDisposition.DEFERRED, "pending-ci"),
        ),
    )
    admission = result.finite_admission

    assert admission.delivered_count == 1
    assert admission.population_exhausted is False
    assert admission.completion_admissible is False
    assert admission.next_action == "continue-candidate-cursor"
    assert result.next_action == "revisit-deferred-or-stale-candidates"


def test_2349_reacquire_candidates_leave_the_population_unexhausted():
    """A stale-head candidate awaiting reacquisition is not an exhausted one."""
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(1, 2, 3),
        evidence=(
            ev(1, RepairDisposition.REACQUIRE, "stale-head"),
            ev(2, RepairDisposition.REACQUIRE, "stale-head"),
            ev(3, RepairDisposition.REACQUIRE, "stale-head"),
        ),
    )
    admission = result.finite_admission

    assert admission.delivered_count == 0
    assert admission.population_exhausted is False
    assert admission.completion_admissible is False


def test_2349_genuine_delivery_still_satisfies_the_requested_count():
    """The control. Real repairs must still close the batch cleanly."""
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(1, 2, 3),
        evidence=(
            ev(1, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(2, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(3, RepairDisposition.REPAIRED, "repair-succeeded"),
        ),
    )
    admission = result.finite_admission

    assert admission.delivered_count == 3
    assert admission.completion_admissible is True
    assert admission.next_action == "report-requested-count-delivered"
    assert result.next_action == "report-complete-repair-batch"


def test_2349_loop_completion_and_delivery_shortfall_are_reported_separately():
    """The invariant in one assertion pair.

    The repair loop is finished -- there is nothing left to traverse -- while
    the requested work was not delivered. Both facts must be legible at once.
    """
    result = evaluate_bulk_repair_continuation(
        requested_pull_requests=(1, 2),
        evidence=(
            ev(1, RepairDisposition.REPAIRED, "repair-succeeded"),
            ev(2, RepairDisposition.BLOCKED, "external-host-owner"),
        ),
    )

    assert result.next_action == "report-complete-repair-batch"
    assert result.finite_admission.delivered_count == 1
    assert result.finite_admission.requested_count == 2
    assert "requested-count-shortfall" in result.finite_admission.reason_codes
