from __future__ import annotations

from agent_os_execution_service.bulk_repair_facade import classify_bulk_repair_continuation


def candidate(
    pr,
    disposition,
    reason,
    *,
    shared=False,
    attempt=None,
    boundary=None,
    mutated=False,
    shared_key=None,
    shared_owner=None,
    repair_available=False,
    repair_completed=False,
):
    return {
        "pull_request_number": pr,
        "disposition": disposition,
        "reason_code": reason,
        "shared_blocker": shared,
        "failed_repair_attempt_id": attempt,
        "retry_boundary": boundary,
        "retry_mutation_performed": mutated,
        "shared_blocker_key": shared_key,
        "shared_repair_owner": shared_owner,
        "shared_repair_available": repair_available,
        "shared_repair_completed": repair_completed,
    }


def retry_boundary(attempt, admitted):
    return {
        "failed_attempt_id": attempt,
        "mutation_admissible": admitted,
        "blocking_attempt_id": None if admitted else attempt,
        "reason_codes": [
            "retry-ckr6-reentry-consumed" if admitted else "retry-ckr6-reentry-required"
        ],
    }


def classify(evidence, requested=None):
    return classify_bulk_repair_continuation(
        repository="Blummer92/agent-os",
        issue_number=2664,
        requested_pull_requests=requested or [2475, 2477, 2479],
        candidate_evidence=evidence,
    )


def test_2475_item_local_safety_block_advances_to_2477():
    result = classify([
        candidate(2475, "blocked", "github-mutation-safety-blocked"),
    ])
    assert result["blocked_pull_requests"] == (2475,)
    assert result["remaining_pull_requests"] == (2477, 2479)
    assert result["next_action"] == "reacquire-next-candidate"
    assert result["agent_os_continuation"]["action"] == "reacquire-next-candidate"
    assert result["agent_os_continuation"]["terminal"] is False
    assert result["agent_os_continuation"]["blocked"] is False


def test_failed_repair_gate_is_recorded_without_discarding_parent_batch():
    attempt = "attempt-2475-safety-1"
    result = classify([
        candidate(
            2475,
            "blocked",
            "retry-ckr6-reentry-required",
            attempt=attempt,
            boundary=retry_boundary(attempt, False),
        ),
    ])
    assert result["lesson_reentry_blocked_pull_requests"] == (2475,)
    assert result["remaining_pull_requests"] == (2477, 2479)
    assert result["agent_os_continuation"]["terminal"] is False


def test_shared_provider_blocker_without_repair_path_halts_parent_batch():
    result = classify([
        candidate(2475, "blocked", "provider-unavailable", shared=True),
    ])
    assert result["remaining_pull_requests"] == (2477, 2479)
    assert result["next_action"] == "halt-shared-blocker"
    assert result["agent_os_continuation"]["terminal"] is True
    assert result["agent_os_continuation"]["blocked"] is True


def test_parent_authorization_invalidation_is_a_shared_stop():
    result = classify([
        candidate(2475, "blocked", "parent-authorization-invalidated", shared=True),
    ])
    assert result["next_action"] == "halt-shared-blocker"
    assert result["agent_os_continuation"]["action"] == ""


def test_repairable_shared_main_health_blocker_is_nonterminal():
    requested = [2658, 2655, 2653, 2649, 2646]
    result = classify(
        [
            candidate(
                pr,
                "blocked",
                "main-health-validation-blocked",
                shared=True,
                shared_key="exact-current-main-health",
                shared_owner="issue:#2652",
                repair_available=True,
            )
            for pr in requested
        ],
        requested=requested,
    )
    assert result["next_action"] == "advance-shared-repair"
    assert result["shared_blocker_pull_requests"] == tuple(requested)
    assert result["shared_repair_owner"] == "issue:#2652"
    assert result["finite_admission"]["completion_admissible"] is False
    assert result["agent_os_continuation"]["action"] == "advance-shared-repair"
    assert result["agent_os_continuation"]["terminal"] is False
    assert result["agent_os_continuation"]["blocked"] is False


def test_shared_repair_completion_routes_reacquisition_not_terminal_report():
    requested = [2658, 2655, 2653, 2649, 2646]
    result = classify(
        [
            candidate(
                pr,
                "blocked",
                "main-health-validation-blocked",
                shared=True,
                shared_key="exact-current-main-health",
                shared_owner="issue:#2652",
                repair_available=True,
                repair_completed=True,
            )
            for pr in requested
        ],
        requested=requested,
    )
    assert result["next_action"] == "reacquire-shared-repair-candidates"
    assert result["agent_os_continuation"]["action"] == "reacquire-shared-repair-candidates"
    assert result["agent_os_continuation"]["terminal"] is False


def test_unattached_git_objects_are_not_completion_evidence():
    result = classify([
        candidate(2475, "blocked", "unattached-git-objects-created"),
    ])
    assert result["repaired_pull_requests"] == ()
    assert result["blocked_pull_requests"] == (2475,)
    assert result["remaining_pull_requests"] == (2477, 2479)
    assert result["finite_admission"]["completion_admissible"] is False


def test_final_report_distinguishes_completed_blocked_and_remaining_candidates():
    result = classify([
        candidate(2475, "blocked", "github-mutation-safety-blocked"),
        candidate(2477, "repaired", "repair-succeeded"),
    ])
    assert result["repaired_pull_requests"] == (2477,)
    assert result["blocked_pull_requests"] == (2475,)
    assert result["remaining_pull_requests"] == (2479,)
    assert result["agent_os_continuation"]["terminal"] is False


def test_complete_accounting_is_terminal_only_after_all_candidates_are_dispositioned():
    result = classify([
        candidate(2475, "blocked", "github-mutation-safety-blocked"),
        candidate(2477, "repaired", "repair-succeeded"),
        candidate(2479, "already-terminal", "already-merged"),
    ])
    assert result["remaining_pull_requests"] == ()
    assert result["next_action"] == "report-complete-repair-batch"
    assert result["agent_os_continuation"]["terminal"] is True
    assert result["agent_os_continuation"]["blocked"] is False


# -- #2349 call-path proof: what the execution-service host is actually told ---


def test_2349_host_is_told_the_shortfall_not_that_the_count_was_satisfied():
    """The user-visible end of the chain.

    Three requested PRs, every one blocked item-local, nothing repaired. The
    repair loop is finished, so the projection is terminal -- but the reason
    codes the host receives must say the requested count fell short. Before the
    repair this same call emitted ``requested-count-satisfied``.
    """
    payload = classify_bulk_repair_continuation(
        repository="Blummer92/agent-os",
        issue_number=2349,
        requested_pull_requests=[1, 2, 3],
        candidate_evidence=[
            candidate(1, "blocked", "needs-decision"),
            candidate(2, "blocked", "needs-decision"),
            candidate(3, "blocked", "external-host-owner"),
        ],
    )

    continuation = payload["agent_os_continuation"]
    reason_codes = tuple(continuation["reason_codes"])

    assert continuation["terminal"] is True
    assert "requested-count-shortfall" in reason_codes
    assert "requested-count-satisfied" not in reason_codes
    assert payload["finite_admission"]["delivered_count"] == 0
    assert payload["finite_admission"]["reconciled_candidate_count"] == 3


def test_2349_host_is_not_told_a_deferred_batch_is_terminal():
    """A deferred candidate leaves the population unexhausted end to end."""
    payload = classify_bulk_repair_continuation(
        repository="Blummer92/agent-os",
        issue_number=2349,
        requested_pull_requests=[1, 2],
        candidate_evidence=[
            candidate(1, "repaired", "repair-succeeded"),
            candidate(2, "deferred", "pending-ci"),
        ],
    )

    continuation = payload["agent_os_continuation"]

    assert continuation["terminal"] is False
    assert payload["next_action"] == "revisit-deferred-or-stale-candidates"
    assert payload["finite_admission"]["population_exhausted"] is False
    assert payload["finite_admission"]["delivered_count"] == 1


def test_2349_host_still_sees_a_genuinely_delivered_batch_as_satisfied():
    """Control: real delivery must still read as delivery at the boundary."""
    payload = classify_bulk_repair_continuation(
        repository="Blummer92/agent-os",
        issue_number=2349,
        requested_pull_requests=[1, 2],
        candidate_evidence=[
            candidate(1, "repaired", "repair-succeeded"),
            candidate(2, "repaired", "repair-succeeded"),
        ],
    )

    continuation = payload["agent_os_continuation"]

    assert continuation["terminal"] is True
    assert tuple(continuation["reason_codes"]) == ("requested-count-satisfied",)
    assert payload["finite_admission"]["delivered_count"] == 2
