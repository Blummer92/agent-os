from __future__ import annotations

import pytest

from scripts.agent_os_issue_acceptance.batch_post_merge_reconciliation import (
    AdmissionState,
    LifecycleAdmissionEvidence,
    PostMergeCandidateEvidence,
    TerminalLifecycleDisposition,
    evaluate_bulk_post_merge_reconciliation,
    evaluate_post_merge_candidate,
)


SHA = "a" * 40
SNAPSHOT = "lifecycle-state-snapshot:test"
OPERATIONAL = "issue-operational-state:test"


def admission(mutation: str, state: AdmissionState) -> LifecycleAdmissionEvidence:
    if state is AdmissionState.MISSING:
        return LifecycleAdmissionEvidence(mutation, state, None, None)
    return LifecycleAdmissionEvidence(mutation, state, f"result:{mutation}:{state.value}", SNAPSHOT)


def candidate(**overrides) -> PostMergeCandidateEvidence:
    values = {
        "repository": "Blummer92/agent-os",
        "pull_request_number": 2500,
        "issue_number": 2499,
        "pr_merged": True,
        "merge_commit_sha": SHA,
        "current_main_sha": SHA,
        "issue_state": "open",
        "issue_complete": True,
        "issue_kind": "implementation",
        "remaining_scope": False,
        "status_ready_present": True,
        "lifecycle_snapshot_id": SNAPSHOT,
        "operational_state_id": OPERATIONAL,
        "closure_authorization_state": "authorized",
        "close_admission": admission("close-issue", AdmissionState.ADMITTED),
        "ready_cleanup_admission": admission("remove-lifecycle-label", AdmissionState.ADMITTED),
    }
    values.update(overrides)
    return PostMergeCandidateEvidence(**values)


def test_merged_open_ready_projects_separate_admitted_mutations_and_readback() -> None:
    result = evaluate_post_merge_candidate(candidate())
    assert result.disposition is TerminalLifecycleDisposition.CLOSED_COMPLETED
    assert result.publish_final_disposition is True
    assert result.remove_status_ready is True
    assert result.close_issue is True
    assert result.requires_final_readback is True
    assert result.converged is False
    assert result.side_effects_performed is False


def test_merged_open_without_ready_closes_without_label_write() -> None:
    result = evaluate_post_merge_candidate(
        candidate(
            status_ready_present=False,
            ready_cleanup_admission=admission("remove-lifecycle-label", AdmissionState.MISSING),
        )
    )
    assert result.disposition is TerminalLifecycleDisposition.CLOSED_COMPLETED
    assert result.remove_status_ready is False
    assert result.close_issue is True


def test_already_closed_ready_requires_only_admitted_cleanup() -> None:
    result = evaluate_post_merge_candidate(
        candidate(
            issue_state="closed",
            close_admission=admission("close-issue", AdmissionState.MISSING),
        )
    )
    assert result.disposition is TerminalLifecycleDisposition.CLOSED_READY_CLEANUP_REQUIRED
    assert result.remove_status_ready is True
    assert result.close_issue is False
    assert result.requires_final_readback is True


def test_already_converged_closed_is_idempotent() -> None:
    result = evaluate_post_merge_candidate(
        candidate(
            issue_state="closed",
            status_ready_present=False,
            close_admission=admission("close-issue", AdmissionState.MISSING),
            ready_cleanup_admission=admission("remove-lifecycle-label", AdmissionState.MISSING),
            final_disposition_already_published=True,
            final_readback_pr_merged=True,
            final_readback_issue_state="closed",
            final_readback_status_ready_present=False,
        )
    )
    assert result.disposition is TerminalLifecycleDisposition.CLOSED_COMPLETED
    assert result.converged is True
    assert result.publish_final_disposition is False
    assert result.remove_status_ready is False
    assert result.close_issue is False
    assert result.requires_final_readback is False


def test_missing_closure_authorization_stays_open() -> None:
    result = evaluate_post_merge_candidate(
        candidate(
            closure_authorization_state="not-authorized",
            close_admission=admission("close-issue", AdmissionState.MISSING),
        )
    )
    assert result.disposition is TerminalLifecycleDisposition.MERGED_AWAITING_CLOSURE_AUTHORIZATION
    assert result.close_issue is False
    assert result.remove_status_ready is False


def test_stale_lifecycle_authorization_does_not_mutate() -> None:
    result = evaluate_post_merge_candidate(
        candidate(
            closure_authorization_state="stale",
            close_admission=admission("close-issue", AdmissionState.STALE),
        )
    )
    assert result.disposition is TerminalLifecycleDisposition.MERGED_AWAITING_CLOSURE_AUTHORIZATION
    assert result.close_issue is False


@pytest.mark.parametrize("issue_kind", ["parent", "tracking"])
def test_partial_parent_or_tracking_issue_stays_open(issue_kind: str) -> None:
    result = evaluate_post_merge_candidate(
        candidate(issue_kind=issue_kind, issue_complete=False, remaining_scope=True)
    )
    assert result.disposition is TerminalLifecycleDisposition.MERGED_ISSUE_NOT_COMPLETE
    assert result.close_issue is False
    assert result.remove_status_ready is False


def test_investigation_with_unmet_criteria_stays_open() -> None:
    result = evaluate_post_merge_candidate(
        candidate(issue_kind="investigation", issue_complete=False, remaining_scope=True)
    )
    assert result.disposition is TerminalLifecycleDisposition.MERGED_ISSUE_NOT_COMPLETE


def test_conflicting_issue_pr_lineage_routes_manual_review() -> None:
    result = evaluate_post_merge_candidate(candidate(evidence_conflicting=True))
    assert result.disposition is TerminalLifecycleDisposition.MANUAL_REVIEW
    assert result.close_issue is False
    assert result.remove_status_ready is False


def test_ready_cleanup_is_independently_admitted() -> None:
    result = evaluate_post_merge_candidate(
        candidate(
            ready_cleanup_admission=admission("remove-lifecycle-label", AdmissionState.BLOCKED)
        )
    )
    assert result.disposition is TerminalLifecycleDisposition.MANUAL_REVIEW
    assert result.close_issue is False
    assert result.remove_status_ready is False


def test_final_readback_proves_convergence_and_suppresses_duplicate_writes() -> None:
    result = evaluate_post_merge_candidate(
        candidate(
            final_disposition_already_published=True,
            final_readback_pr_merged=True,
            final_readback_issue_state="closed",
            final_readback_status_ready_present=False,
        )
    )
    assert result.disposition is TerminalLifecycleDisposition.CLOSED_COMPLETED
    assert result.converged is True
    assert result.publish_final_disposition is False
    assert result.close_issue is False
    assert result.remove_status_ready is False
    assert result.requires_final_readback is False


def test_candidate_local_blocker_does_not_stop_later_candidates() -> None:
    blocked = candidate(
        issue_number=1,
        pull_request_number=11,
        closure_authorization_state="not-authorized",
        close_admission=admission("close-issue", AdmissionState.MISSING),
    )
    admitted = candidate(issue_number=2, pull_request_number=12)
    result = evaluate_bulk_post_merge_reconciliation((blocked, admitted))
    assert result.awaiting_closure_issue_numbers == (1,)
    assert result.closed_completed_issue_numbers == (2,)
    assert result.candidates[1].close_issue is True
    assert result.next_action == "perform-admitted-lifecycle-mutations-then-reacquire"
    assert result.side_effects_performed is False


def test_admission_must_bind_current_lifecycle_snapshot() -> None:
    with pytest.raises(ValueError, match="current lifecycle snapshot"):
        candidate(
            close_admission=LifecycleAdmissionEvidence(
                "close-issue", AdmissionState.ADMITTED, "result:close", "other-snapshot"
            )
        )
