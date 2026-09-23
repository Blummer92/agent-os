from scripts.agent_os_execution_checkpoint.external_event_resume import classify_external_event_resume
from scripts.agent_os_execution_checkpoint.models import CheckpointStage


def test_draft_pr_lineage_is_parked_not_blocked_while_waiting_for_merge():
    decision = classify_external_event_resume(current_stage=CheckpointStage.DRAFT_PR_OPENED)
    assert decision.classification == "awaiting-external-event"
    assert decision.reason_codes == ("awaiting-pr-merge",)


def test_proven_merge_resumes_to_existing_merged_stage_without_granting_authority():
    decision = classify_external_event_resume(current_stage=CheckpointStage.REVIEW_COMPLETE, merge_proven=True)
    assert decision.classification == "resumable-on-event"
    assert decision.next_stage is CheckpointStage.MERGED
    assert decision.merge_authorized is False
    assert decision.issue_closure_authorized is False


def test_proven_closure_advances_only_from_merged_stage():
    decision = classify_external_event_resume(current_stage=CheckpointStage.MERGED, issue_closed_proven=True)
    assert decision.next_stage is CheckpointStage.ISSUE_CLOSED
    assert decision.external_writes_authorized is False


def test_unproven_terminal_events_never_advance_stage():
    assert classify_external_event_resume(current_stage=CheckpointStage.REVIEW_COMPLETE).next_stage is None
    assert classify_external_event_resume(current_stage=CheckpointStage.MERGED).next_stage is None
