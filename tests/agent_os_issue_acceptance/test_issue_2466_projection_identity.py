import pytest

from scripts.agent_os_issue_acceptance.batch_merge_execution import BatchMergeAction, BatchMergeCursor, apply_lifecycle_readback, apply_post_merge_reconciliation, expected_lifecycle_mutations, record_lifecycle_mutations
from scripts.agent_os_issue_acceptance.batch_post_merge_reconciliation import PostMergeCandidateProjection, TerminalLifecycleDisposition


def _projection(snapshot="snap", operational="ops", *, converged=False):
    return PostMergeCandidateProjection(11, 101, TerminalLifecycleDisposition.CLOSED_COMPLETED, ("test",), False, True, True, not converged, converged, snapshot, operational)


def _cursor():
    return BatchMergeCursor((11,), ((11, 101),), current_main_sha="m1", current_head_sha="h11", pending_merged_main_sha="m2", action=BatchMergeAction.POST_MERGE)


def test_matching_projection_identity_survives_mutation_and_readback():
    p = _projection()
    cursor = apply_post_merge_reconciliation(_cursor(), p)
    assert expected_lifecycle_mutations(cursor, p) == (101, True, True)
    cursor = record_lifecycle_mutations(cursor, issue_number=101, accepted=True)
    cursor = apply_lifecycle_readback(cursor, _projection(converged=True))
    assert cursor.action is BatchMergeAction.COMPLETE


def test_swapped_projection_identity_is_rejected_before_mutation():
    cursor = apply_post_merge_reconciliation(_cursor(), _projection())
    with pytest.raises(ValueError):
        expected_lifecycle_mutations(cursor, _projection(snapshot="other"))


def test_swapped_projection_identity_fails_closed_at_readback():
    cursor = apply_post_merge_reconciliation(_cursor(), _projection())
    cursor = record_lifecycle_mutations(cursor, issue_number=101, accepted=True)
    cursor = apply_lifecycle_readback(cursor, _projection(operational="other", converged=True))
    assert cursor.action is BatchMergeAction.HALT
