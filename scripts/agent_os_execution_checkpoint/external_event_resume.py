from __future__ import annotations

from dataclasses import dataclass

from .models import CheckpointStage


@dataclass(frozen=True, slots=True)
class ExternalEventResumeDecision:
    classification: str
    current_stage: CheckpointStage
    next_stage: CheckpointStage | None
    reason_codes: tuple[str, ...]
    merge_authorized: bool = False
    issue_closure_authorized: bool = False
    external_writes_authorized: bool = False


def classify_external_event_resume(*, current_stage: CheckpointStage, merge_proven: bool = False, issue_closed_proven: bool = False) -> ExternalEventResumeDecision:
    if current_stage in {CheckpointStage.DRAFT_PR_OPENED, CheckpointStage.CI_PASSED, CheckpointStage.REVIEW_COMPLETE}:
        if not merge_proven:
            return ExternalEventResumeDecision("awaiting-external-event", current_stage, None, ("awaiting-pr-merge",))
        return ExternalEventResumeDecision("resumable-on-event", current_stage, CheckpointStage.MERGED, ("canonical-merge-proven",))
    if current_stage is CheckpointStage.MERGED:
        if not issue_closed_proven:
            return ExternalEventResumeDecision("resumable-post-merge", current_stage, None, ("post-merge-reconciliation-required",))
        return ExternalEventResumeDecision("resumable-on-event", current_stage, CheckpointStage.ISSUE_CLOSED, ("canonical-issue-closure-proven",))
    if current_stage is CheckpointStage.ISSUE_CLOSED:
        return ExternalEventResumeDecision("terminal", current_stage, None, ("issue-closure-already-proven",))
    return ExternalEventResumeDecision("not-applicable", current_stage, None, ())
