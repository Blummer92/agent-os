from __future__ import annotations

from agent_os_execution_service.bulk_repair_facade import classify_bulk_repair_continuation


def candidate(pr, disposition, reason, *, shared=False, attempt=None, boundary=None, mutated=False):
    return {
        "pull_request_number": pr,
        "disposition": disposition,
        "reason_code": reason,
        "shared_blocker": shared,
        "failed_repair_attempt_id": attempt,
        "retry_boundary": boundary,
        "retry_mutation_performed": mutated,
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


def classify(evidence):
    return classify_bulk_repair_continuation(
        repository="Blummer92/agent-os",
        issue_number=2487,
        requested_pull_requests=[2475, 2477, 2479],
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


def test_shared_provider_blocker_halts_parent_batch():
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
