from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.agent_os_candidate_packet.executable_lane_selection import (
    EXECUTABLE_LANE_SELECTION_SCHEMA_NAME,
    EXECUTABLE_LANE_SELECTION_SCHEMA_VERSION,
    ExecutableLaneSelection,
    Queue,
    QueueClassification,
    RankEvidence,
)
from scripts.agent_os_candidate_packet.post_pr_lane_plan import (
    ConflictFinding,
    LanePlanOutcome,
    PostPrLanePlan,
    deserialize_post_pr_lane_plan,
    plan_post_pr_lane,
    serialize_post_pr_lane_plan,
)
from scripts.agent_os_issue_acceptance.executor_route import ExecutorRoute
from scripts.agent_os_issue_acceptance.post_pr_state_audit import (
    POST_PR_STATE_AUDIT_SCHEMA_NAME,
    POST_PR_STATE_AUDIT_SCHEMA_VERSION,
    PostPrStateAuditResult,
    RecommendationOutcome,
    RepositoryHealth,
    SubsystemMaturity,
    TerminalPrState,
)

STATE_ID = "issue-operational-state:" + "1" * 64
MODE_ID = "agent-operating-mode-decision:" + "2" * 64


def selection(*, selected=(910,), deferred=(), queues=None, lane_count=1):
    supplied = tuple(sorted(selected + deferred))
    queues = queues or {issue: Queue.READY_FOR_IMPLEMENTATION for issue in supplied}
    return ExecutableLaneSelection(
        schema_name=EXECUTABLE_LANE_SELECTION_SCHEMA_NAME,
        schema_version=EXECUTABLE_LANE_SELECTION_SCHEMA_VERSION,
        campaign_id="test-campaign",
        requested_lane_count=lane_count,
        substitution_allowed=True,
        supplied_issue_numbers=supplied,
        source_operational_state_ids=(STATE_ID,),
        source_operating_mode_decision_ids=(MODE_ID,),
        queue_classifications=tuple(QueueClassification(issue, queues[issue], (f"queue.{queues[issue].value}",)) for issue in supplied),
        selected_lanes=selected,
        deferred_candidates=deferred,
        replacement_records=(),
        rank_evidence=tuple(RankEvidence(issue, rank, 1, None, 0) for rank, issue in enumerate(supplied, 1)),
        duplicate_claim_findings=(),
        reason_codes=tuple(sorted({f"queue.{queues[issue].value}" for issue in supplied})),
    )


def audit(*, recommended=910, alternate=None, outcome=RecommendationOutcome.NEXT_ISSUE, terminal=TerminalPrState.MERGED, route=ExecutorRoute.CHATGPT_CONNECTOR):
    return PostPrStateAuditResult(
        schema_name=POST_PR_STATE_AUDIT_SCHEMA_NAME,
        schema_version=POST_PR_STATE_AUDIT_SCHEMA_VERSION,
        repository="Blummer92/agent-os",
        pull_request_number=909,
        terminal_state=terminal,
        repository_health=RepositoryHealth.HEALTHY,
        subsystem="queue-planning",
        subsystem_maturity=SubsystemMaturity.PROGRESSING,
        landed_capability="test capability",
        outcome=outcome,
        recommended_issue=recommended,
        alternate_issue=alternate,
        recommended_executor_route=route if recommended is not None else None,
        rationale="bounded test rationale",
        next_action="Open next issue." if recommended is not None else "Escalate to human_decision.",
        files_changed=(), tests_run=(), docs_updated=(), unresolved_blockers=(),
        handoff_recommendation="Continue with canonical evidence.", remaining_risks=(),
        reason_codes=("health.healthy", "state.merged", "outcome.next-issue") if outcome is RecommendationOutcome.NEXT_ISSUE else ("health.healthy", "state.merged", "outcome.human-decision"),
    )


def test_recommendation_already_selected_preserves_selector_primary():
    plan = plan_post_pr_lane(selection(selected=(910, 911), lane_count=2), audit(recommended=911))
    assert plan.outcome is LanePlanOutcome.LANE_PLAN
    assert plan.selected_lane_issue_numbers == (910, 911)
    assert plan.primary_next_issue == 910
    assert plan.recommended_executor_route is None


def test_primary_recommendation_preserves_executor_route():
    plan = plan_post_pr_lane(selection(), audit())
    assert plan.primary_next_issue == 910
    assert plan.recommended_executor_route is ExecutorRoute.CHATGPT_CONNECTOR

@pytest.mark.parametrize("queue,reason", [
    (Queue.WAITING_FOR_AUTHORIZATION, "conflict.recommendation-waiting-authorization"),
    (Queue.WAITING_FOR_DEPENDENCY, "conflict.recommendation-waiting-dependency"),
    (Queue.TERMINAL, "conflict.recommendation-terminal"),
    (Queue.INVALID, "conflict.recommendation-invalid"),
])
def test_non_executable_recommendations_fail_closed(queue, reason):
    plan = plan_post_pr_lane(selection(selected=(910,), deferred=(911,), queues={910: Queue.READY_FOR_IMPLEMENTATION, 911: queue}), audit(recommended=911))
    assert plan.outcome is LanePlanOutcome.HUMAN_DECISION
    assert reason in plan.reason_codes
    assert plan.recommended_executor_route is ExecutorRoute.HUMAN_DECISION


def test_absent_recommendation_fails_closed():
    plan = plan_post_pr_lane(selection(), audit(recommended=999))
    assert plan.outcome is LanePlanOutcome.HUMAN_DECISION
    assert "conflict.recommendation-absent" in plan.reason_codes


def test_lower_precedence_deferred_recommendation_cannot_reorder():
    plan = plan_post_pr_lane(selection(selected=(910,), deferred=(911,), queues={910: Queue.READY_FOR_IMPLEMENTATION, 911: Queue.READY_FOR_IMPLEMENTATION}), audit(recommended=911))
    assert plan.outcome is LanePlanOutcome.HUMAN_DECISION
    assert "conflict.recommendation-lower-precedence" in plan.reason_codes


def test_supported_alternate_is_retained_without_reordering():
    plan = plan_post_pr_lane(selection(selected=(910, 911), lane_count=2), audit(recommended=910, alternate=911))
    assert plan.primary_next_issue == 910
    assert plan.alternate_issue == 911


def test_unsupported_alternate_fails_closed():
    plan = plan_post_pr_lane(selection(selected=(910,), deferred=(911,), queues={910: Queue.READY_FOR_IMPLEMENTATION, 911: Queue.READY_FOR_IMPLEMENTATION}), audit(recommended=910, alternate=911))
    assert plan.outcome is LanePlanOutcome.HUMAN_DECISION
    assert "conflict.alternate-unsupported" in plan.reason_codes


def test_human_decision_audit_causes_no_promotion():
    result = audit(recommended=None, outcome=RecommendationOutcome.HUMAN_DECISION, route=None)
    plan = plan_post_pr_lane(selection(), result)
    assert plan.outcome is LanePlanOutcome.HUMAN_DECISION
    assert plan.primary_next_issue is None


def test_review_complete_remains_human_gated():
    result = replace(audit(recommended=None, outcome=RecommendationOutcome.HUMAN_DECISION, route=None), terminal_pr_state=TerminalPrState.REVIEW_COMPLETE) if False else None
    base = audit(recommended=None, outcome=RecommendationOutcome.HUMAN_DECISION, route=None)
    review = PostPrStateAuditResult(
        schema_name=base.schema_name, schema_version=base.schema_version, repository=base.repository,
        pull_request_number=base.pull_request_number, terminal_state=TerminalPrState.REVIEW_COMPLETE,
        repository_health=base.repository_health, subsystem=base.subsystem, subsystem_maturity=base.subsystem_maturity,
        landed_capability="", outcome=RecommendationOutcome.HUMAN_DECISION, recommended_issue=None, alternate_issue=None,
        recommended_executor_route=None, rationale="review complete", next_action="Escalate to human_decision.",
        files_changed=(), tests_run=(), docs_updated=(), unresolved_blockers=(), handoff_recommendation="human review", remaining_risks=(),
        reason_codes=("health.healthy", "state.review-complete", "outcome.human-decision"),
    )
    assert plan_post_pr_lane(selection(), review).outcome is LanePlanOutcome.HUMAN_DECISION


def test_round_trip_is_byte_stable_and_authority_false():
    plan = plan_post_pr_lane(selection(), audit())
    encoded = serialize_post_pr_lane_plan(plan)
    rebuilt = deserialize_post_pr_lane_plan(encoded)
    assert rebuilt == plan
    assert serialize_post_pr_lane_plan(rebuilt) == encoded
    assert rebuilt.execution_authorized is False
    assert rebuilt.side_effects_performed is False
    assert rebuilt.scheduler_invoked is False


def test_conflict_findings_are_canonicalized_before_identity():
    base = plan_post_pr_lane(selection(), audit())
    first = ConflictFinding("conflict.recommendation-absent", 999)
    second = ConflictFinding("conflict.alternate-unsupported", 998)
    left = replace(base, conflict_findings=(first, second, first), plan_id="")
    right = replace(base, conflict_findings=(second, first), plan_id="")
    assert left.conflict_findings == right.conflict_findings
    assert left.plan_id == right.plan_id


@pytest.mark.parametrize("tampered_id", ["", "post-pr-lane-plan:" + "f" * 64])
def test_deserialization_rejects_empty_or_tampered_plan_id(tampered_id):
    payload = plan_post_pr_lane(selection(), audit()).to_dict()
    payload["plan_id"] = tampered_id
    with pytest.raises(ValueError, match="plan_id"):
        PostPrLanePlan.from_dict(payload)


def test_unknown_fields_and_authority_true_are_rejected():
    payload = plan_post_pr_lane(selection(), audit()).to_dict()
    payload["unknown"] = True
    with pytest.raises(ValueError):
        PostPrLanePlan.from_dict(payload)
    payload.pop("unknown")
    payload["execution_authorized"] = True
    with pytest.raises(ValueError):
        PostPrLanePlan.from_dict(payload)


def test_tampered_source_identity_fails_closed():
    source = selection()
    object.__setattr__(source, "selection_id", "executable-lane-selection:" + "f" * 64)
    with pytest.raises(ValueError, match="source identity"):
        plan_post_pr_lane(source, audit())

@pytest.mark.parametrize("lanes", [(910,), (910, 911), (910, 911, 912)])
def test_lane_counts_one_through_three(lanes):
    plan = plan_post_pr_lane(selection(selected=lanes, lane_count=len(lanes)), audit(recommended=lanes[0]))
    assert plan.selected_lane_issue_numbers == lanes


def test_adapter_has_no_io_dependency(monkeypatch):
    import builtins
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("I/O forbidden")))
    assert plan_post_pr_lane(selection(), audit()).primary_next_issue == 910
