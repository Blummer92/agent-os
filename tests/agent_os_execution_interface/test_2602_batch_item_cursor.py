"""#2602 regression: item-local blockers must advance the batch cursor.

Fresh reproduction (2026-10-06T00:20Z): an authorized three-item implementation
batch (#3249, #3250, #3297) met an item-local material owner decision on #3250
and returned control at the preflight/checkpoint stage instead of continuing
the independent #3249 and #3297 lanes.

The invariant under test: an item-local decision/capability blocker marks ONLY
that candidate non-admissible and the finite-mission cursor advances to the
next admissible candidate. The batch is terminal only when the requested count
is delivered, the reconciled population is exhausted, or a shared blocker is
proven across ALL remaining candidates. One candidate's blocker claim never
stops the batch.
"""

import pytest

from scripts.agent_os_execution_interface.finite_batch_admission import (
    BatchCandidate,
    BatchCandidateDisposition,
    evaluate_batch_item_cursor,
)


def _candidate(candidate_id, disposition, reason_code="material-owner-decision", key=None):
    return BatchCandidate(
        candidate_id=candidate_id,
        disposition=disposition,
        reason_code=reason_code,
        shared_blocker_key=key,
    )


def test_item_local_decision_blocker_advances_cursor_not_batch():
    # Exact #2602 reproduction: #3250's item-local material owner decision must
    # hold only #3250; the cursor advances to the independent lanes.
    transition = evaluate_batch_item_cursor(
        requested_count=3,
        candidates=(
            _candidate("3249", BatchCandidateDisposition.ADMISSIBLE),
            _candidate("3250", BatchCandidateDisposition.BLOCKED_ITEM_LOCAL),
            _candidate("3297", BatchCandidateDisposition.ADMISSIBLE),
        ),
    )
    assert transition.admission.completion_admissible is False
    assert transition.admission.next_action == "continue-candidate-cursor"
    assert transition.blocked_item_local == ("3250",)
    assert transition.next_candidate_id == "3249"
    assert transition.shared_blocker_proven is False
    assert transition.admission.mutation_authorized is False


def test_delivered_then_item_local_block_still_continues():
    transition = evaluate_batch_item_cursor(
        requested_count=3,
        candidates=(
            _candidate("3249", BatchCandidateDisposition.DELIVERED),
            _candidate("3250", BatchCandidateDisposition.BLOCKED_ITEM_LOCAL),
            _candidate("3297", BatchCandidateDisposition.ADMISSIBLE),
        ),
    )
    assert transition.admission.completion_admissible is False
    assert transition.admission.next_action == "continue-candidate-cursor"
    assert transition.next_candidate_id == "3297"
    assert transition.blocked_item_local == ("3250",)


def test_single_shared_claim_with_admissible_remaining_does_not_stop_batch():
    # A BLOCKED_SHARED claim on one candidate while independent lanes remain
    # admissible is not a proven shared blocker: the cursor continues.
    transition = evaluate_batch_item_cursor(
        requested_count=3,
        candidates=(
            _candidate("3249", BatchCandidateDisposition.ADMISSIBLE),
            _candidate(
                "3250", BatchCandidateDisposition.BLOCKED_SHARED,
                key="owner-decision-cognitive-load",
            ),
            _candidate("3297", BatchCandidateDisposition.ADMISSIBLE),
        ),
    )
    assert transition.admission.completion_admissible is False
    assert transition.admission.next_action == "continue-candidate-cursor"
    assert transition.shared_blocker_proven is False
    assert transition.next_candidate_id == "3249"


def test_shared_blocker_proven_across_all_remaining_is_terminal():
    transition = evaluate_batch_item_cursor(
        requested_count=3,
        candidates=(
            _candidate("3249", BatchCandidateDisposition.BLOCKED_SHARED,
                       key="shared-capability-absence"),
            _candidate("3250", BatchCandidateDisposition.BLOCKED_SHARED,
                       key="shared-capability-absence"),
            _candidate("3297", BatchCandidateDisposition.BLOCKED_SHARED,
                       key="shared-capability-absence"),
        ),
    )
    assert transition.shared_blocker_proven is True
    assert transition.admission.completion_admissible is True
    assert transition.admission.next_action == "report-shared-terminal-blocker-and-shortfall"
    assert "requested-count-shortfall" in transition.admission.reason_codes
    assert transition.next_candidate_id is None


def test_shared_blocker_after_partial_delivery_is_terminal():
    transition = evaluate_batch_item_cursor(
        requested_count=3,
        candidates=(
            _candidate("3249", BatchCandidateDisposition.DELIVERED),
            _candidate("3250", BatchCandidateDisposition.BLOCKED_SHARED,
                       key="shared-capability-absence"),
            _candidate("3297", BatchCandidateDisposition.BLOCKED_SHARED,
                       key="shared-capability-absence"),
        ),
    )
    assert transition.shared_blocker_proven is True
    assert transition.admission.completion_admissible is True
    assert transition.admission.next_action == "report-shared-terminal-blocker-and-shortfall"
    assert transition.next_candidate_id is None


def test_item_local_blocks_exhausting_population_report_honest_shortfall():
    transition = evaluate_batch_item_cursor(
        requested_count=3,
        candidates=(
            _candidate("3249", BatchCandidateDisposition.DELIVERED),
            _candidate("3250", BatchCandidateDisposition.BLOCKED_ITEM_LOCAL),
            _candidate("3297", BatchCandidateDisposition.BLOCKED_ITEM_LOCAL),
        ),
    )
    assert transition.admission.completion_admissible is True
    assert transition.admission.next_action == "report-proven-population-exhaustion-and-shortfall"
    assert "requested-count-shortfall" in transition.admission.reason_codes
    assert transition.blocked_item_local == ("3250", "3297")
    assert transition.next_candidate_id is None


def test_delivered_count_satisfies_requested_count():
    transition = evaluate_batch_item_cursor(
        requested_count=3,
        candidates=(
            _candidate("3249", BatchCandidateDisposition.DELIVERED),
            _candidate("3250", BatchCandidateDisposition.DELIVERED),
            _candidate("3297", BatchCandidateDisposition.DELIVERED),
        ),
    )
    assert transition.admission.completion_admissible is True
    assert transition.admission.next_action == "report-requested-count-delivered"
    assert transition.next_candidate_id is None


def test_conflicting_shared_blocker_keys_fail_closed():
    with pytest.raises(ValueError):
        evaluate_batch_item_cursor(
            requested_count=3,
            candidates=(
                _candidate("3249", BatchCandidateDisposition.BLOCKED_SHARED,
                           key="blocker-one"),
                _candidate("3250", BatchCandidateDisposition.BLOCKED_SHARED,
                           key="blocker-two"),
            ),
        )


def test_shared_disposition_requires_key_and_key_requires_shared():
    with pytest.raises(ValueError):
        _candidate("3250", BatchCandidateDisposition.BLOCKED_SHARED)
    with pytest.raises(ValueError):
        _candidate("3250", BatchCandidateDisposition.BLOCKED_ITEM_LOCAL,
                   key="owner-decision-cognitive-load")


def test_duplicate_candidate_ids_fail_closed():
    with pytest.raises(ValueError):
        evaluate_batch_item_cursor(
            requested_count=3,
            candidates=(
                _candidate("3249", BatchCandidateDisposition.ADMISSIBLE),
                _candidate("3249", BatchCandidateDisposition.DELIVERED),
            ),
        )


@pytest.mark.parametrize("requested", [0, -1])
def test_non_positive_requested_count_fails_closed(requested):
    with pytest.raises(ValueError):
        evaluate_batch_item_cursor(
            requested_count=requested,
            candidates=(_candidate("3249", BatchCandidateDisposition.ADMISSIBLE),),
        )


def test_empty_candidates_fail_closed():
    with pytest.raises(ValueError):
        evaluate_batch_item_cursor(requested_count=3, candidates=())
