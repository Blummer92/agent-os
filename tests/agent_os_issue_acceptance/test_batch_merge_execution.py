from scripts.agent_os_issue_acceptance.batch_merge_execution import (
    BatchItemDisposition, BatchMergeAction, CurrentPrEvidence, ItemAdmissionEvidence,
    MergeReadbackEvidence, apply_current_state, apply_merge_authorization,
    apply_merge_readback, apply_refresh_readback, apply_validation, expected_merge,
    final_batch_report, record_merge_attempt, start_batch_execution,
)
from scripts.agent_os_issue_acceptance.pr_batch_merge_plan import PrBatchItemEvidence, build_pr_batch_merge_plan


def plan(*prs):
    return build_pr_batch_merge_plan(repository="Blummer92/agent-os", base_revision="a" * 40,
        requested_pull_requests=prs,
        evidence=[PrBatchItemEvidence(p, f"h{p}", "main", "open", "applicable") for p in prs])


def current(pr, main, head, freshness="current", **kw):
    return CurrentPrEvidence(pr, main, head, "open", freshness, **kw)


def admit(pr, main, head, validation="passed", authorization="authorized"):
    return ItemAdmissionEvidence(pr, main, head, validation, authorization)


def drive_to_merge(cursor, pr, main, head):
    cursor = apply_current_state(cursor, current(pr, main, head))
    cursor = apply_validation(cursor, admit(pr, main, head))
    cursor = apply_merge_authorization(cursor, admit(pr, main, head))
    assert expected_merge(cursor) == (pr, head)
    return cursor


def test_two_clean_prs_reacquire_after_first_merge():
    c = start_batch_execution(plan(11, 12))
    c = drive_to_merge(c, 11, "m1", "h11")
    c = record_merge_attempt(c, pull_request_number=11, expected_head_sha="h11", accepted=True)
    c = apply_merge_readback(c, MergeReadbackEvidence(11, "h11", True, "m2"))
    assert c.action is BatchMergeAction.REACQUIRE and c.current_pull_request == 12
    c = drive_to_merge(c, 12, "m2", "h12b")
    c = record_merge_attempt(c, pull_request_number=12, expected_head_sha="h12b", accepted=True)
    c = apply_merge_readback(c, MergeReadbackEvidence(12, "h12b", True, "m3"))
    assert [r.disposition for r in final_batch_report(c)] == [BatchItemDisposition.MERGED] * 2


def test_stale_second_pr_routes_through_existing_refresh_action():
    c = start_batch_execution(plan(11, 12))
    c = drive_to_merge(c, 11, "m1", "h11")
    c = record_merge_attempt(c, pull_request_number=11, expected_head_sha="h11", accepted=True)
    c = apply_merge_readback(c, MergeReadbackEvidence(11, "h11", True, "m2"))
    c = apply_current_state(c, current(12, "m2", "h12", "behind"))
    assert c.action is BatchMergeAction.REFRESH
    c = apply_refresh_readback(c, current(12, "m2", "h12r", "current"))
    assert c.action is BatchMergeAction.VALIDATE and c.current_head_sha == "h12r"


def test_head_or_main_movement_restarts_reacquisition():
    c = start_batch_execution(plan(11))
    c = apply_current_state(c, current(11, "m1", "h11"))
    c = apply_validation(c, admit(11, "m2", "h11"))
    assert c.action is BatchMergeAction.REACQUIRE


def test_expected_head_mismatch_never_reaches_readback():
    c = drive_to_merge(start_batch_execution(plan(11)), 11, "m1", "h11")
    c = record_merge_attempt(c, pull_request_number=11, expected_head_sha="moved", accepted=True)
    assert c.action is BatchMergeAction.REACQUIRE


def test_validation_red_pending_or_missing_skips_item_locally():
    for status in ("failed", "pending", "missing"):
        c = start_batch_execution(plan(11, 12))
        c = apply_current_state(c, current(11, "m1", "h11"))
        c = apply_validation(c, admit(11, "m1", "h11", validation=status))
        assert c.current_pull_request == 12
        assert c.results[-1].disposition is BatchItemDisposition.SKIPPED_ITEM_LOCAL


def test_missing_or_stale_merge_authority_never_merges():
    for status in ("missing", "stale", "blocked"):
        c = start_batch_execution(plan(11, 12))
        c = apply_current_state(c, current(11, "m1", "h11"))
        c = apply_validation(c, admit(11, "m1", "h11"))
        c = apply_merge_authorization(c, admit(11, "m1", "h11", authorization=status))
        assert c.current_pull_request == 12
        assert c.action is BatchMergeAction.REACQUIRE


def test_semantic_conflict_is_item_local_and_does_not_request_refresh():
    c = start_batch_execution(plan(11, 12))
    c = apply_current_state(c, current(11, "m1", "h11", "behind", semantic_conflict=True))
    assert c.current_pull_request == 12
    assert c.results[-1].reason_codes == ("semantic-conflict",)


def test_post_merge_readback_is_required_and_provider_failure_halts():
    c = drive_to_merge(start_batch_execution(plan(11, 12)), 11, "m1", "h11")
    c = record_merge_attempt(c, pull_request_number=11, expected_head_sha="h11", accepted=True)
    c = apply_merge_readback(c, MergeReadbackEvidence(11, "h11", True, "m2", provider_available=False))
    assert c.action is BatchMergeAction.HALT and c.halted


def test_already_terminal_item_is_idempotent():
    c = start_batch_execution(plan(11, 12))
    c = apply_current_state(c, CurrentPrEvidence(11, "m1", "h11", "merged", "current"))
    assert c.current_pull_request == 12
    assert c.results[-1].disposition is BatchItemDisposition.ALREADY_TERMINAL


def test_systemic_currentness_failure_halts_remaining_batch():
    c = start_batch_execution(plan(11, 12, 13))
    c = apply_current_state(c, current(11, "m1", "h11", provider_available=False))
    assert c.action is BatchMergeAction.HALT
    assert c.current_pull_request == 11


def test_no_background_or_auto_merge_actions_exist():
    assert {a.value for a in BatchMergeAction}.isdisjoint({"auto-merge", "poll", "retry", "queue"})
