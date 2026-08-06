from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.agent_os_issue_acceptance.executor_route import ExecutorRoute
from scripts.agent_os_issue_acceptance.post_pr_state_audit import (
    POST_PR_STATE_AUDIT_SCHEMA_NAME,
    POST_PR_STATE_AUDIT_SCHEMA_VERSION,
    CandidateRankTier,
    NextIssueCandidateEvidence,
    PostPrStateAuditEvidence,
    PostPrStateAuditResult,
    RecommendationOutcome,
    RepositoryHealth,
    SubsystemMaturity,
    TerminalPrState,
    evaluate_post_pr_state_audit,
    format_post_pr_state_audit,
)

SHA = "a" * 40


def candidate(**changes: object) -> NextIssueCandidateEvidence:
    baseline = NextIssueCandidateEvidence(
        issue_number=910,
        subsystem="executor-orchestration",
        rank_tier=CandidateRankTier.DEPENDENCY_UNBLOCKED,
    )
    return replace(baseline, **changes)


def evidence(**changes: object) -> PostPrStateAuditEvidence:
    baseline = PostPrStateAuditEvidence(
        repository="Blummer92/agent-os",
        pull_request_number=909,
        terminal_state=TerminalPrState.MERGED,
        head_sha=SHA,
        checks_verified=True,
        unresolved_threads=False,
        landed_capability="deterministic executor-route selection",
        subsystem="executor-orchestration",
        subsystem_maturity=SubsystemMaturity.PROGRESSING,
        candidates=(candidate(),),
        files_changed=("executor_route.py",),
        tests_run=("pytest focused",),
        docs_updated=("executor-route-contract.md",),
        unresolved_blockers=(),
        handoff_recommendation="Continue with the next dependency issue.",
        remaining_risks=("stale capability evidence",),
    )
    return replace(baseline, **changes)


def test_merged_with_verified_checks_and_unblocked_dependency() -> None:
    result = evaluate_post_pr_state_audit(evidence())
    assert result.outcome is RecommendationOutcome.NEXT_ISSUE
    assert result.repository_health is RepositoryHealth.HEALTHY
    assert result.recommended_issue == 910
    assert "state.merged" in result.reason_codes
    assert "candidate.selected" in result.reason_codes


def test_merged_healthy_repo_with_incomplete_subsystem_maturity() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(subsystem_maturity=SubsystemMaturity.EARLY)
    )
    assert result.repository_health is RepositoryHealth.HEALTHY
    assert result.subsystem_maturity is SubsystemMaturity.EARLY
    assert result.subsystem_maturity is not SubsystemMaturity.COMPLETE


def test_review_complete_routes_to_human_decision() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(
            terminal_state=TerminalPrState.REVIEW_COMPLETE,
            landed_capability="",
        )
    )
    assert result.outcome is RecommendationOutcome.HUMAN_DECISION
    assert result.recommended_issue is None
    assert "state.review-complete" in result.reason_codes


def test_blocked_with_actionable_blocker() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(
            terminal_state=TerminalPrState.BLOCKED,
            landed_capability="partial scaffolding",
            controlling_blocker_issue=855,
            controlling_blocker_actionable=True,
        )
    )
    assert result.outcome is RecommendationOutcome.NEXT_ISSUE
    assert result.recommended_issue == 855
    assert "blocker.present" in result.reason_codes


def test_blocked_with_no_actionable_blocker() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(
            terminal_state=TerminalPrState.BLOCKED,
            landed_capability="partial scaffolding",
        )
    )
    assert result.outcome is RecommendationOutcome.HUMAN_DECISION
    assert result.recommended_issue is None
    assert "blocker.none" in result.reason_codes


def test_blocked_with_non_actionable_blocker() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(
            terminal_state=TerminalPrState.BLOCKED,
            landed_capability="partial scaffolding",
            controlling_blocker_issue=855,
            controlling_blocker_actionable=False,
        )
    )
    assert result.outcome is RecommendationOutcome.HUMAN_DECISION
    assert result.recommended_issue is None
    assert "blocker.not-actionable" in result.reason_codes


def test_closed_unmerged_with_verified_replacement() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(
            terminal_state=TerminalPrState.CLOSED_UNMERGED,
            landed_capability="",
            replacement_issue=920,
            replacement_verified=True,
        )
    )
    assert result.outcome is RecommendationOutcome.NEXT_ISSUE
    assert result.recommended_issue == 920
    assert "replacement.verified" in result.reason_codes


def test_closed_unmerged_with_no_supported_replacement() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(terminal_state=TerminalPrState.CLOSED_UNMERGED, landed_capability="")
    )
    assert result.outcome is RecommendationOutcome.HUMAN_DECISION
    assert "replacement.missing" in result.reason_codes


def test_ambiguous_tie_produces_one_preferred_and_one_alternate() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(
            candidates=(
                candidate(issue_number=910, rank_tier=CandidateRankTier.DEPENDENCY_UNBLOCKED),
                candidate(issue_number=911, rank_tier=CandidateRankTier.DEPENDENCY_UNBLOCKED),
            )
        )
    )
    assert result.outcome is RecommendationOutcome.NEXT_ISSUE
    assert result.recommended_issue == 910
    assert result.alternate_issue == 911
    assert "candidate.alternate" in result.reason_codes


def test_tie_exceeding_permitted_alternate_fails_closed() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(
            candidates=(
                candidate(issue_number=910, rank_tier=CandidateRankTier.DEPENDENCY_UNBLOCKED),
                candidate(issue_number=911, rank_tier=CandidateRankTier.DEPENDENCY_UNBLOCKED),
                candidate(issue_number=912, rank_tier=CandidateRankTier.DEPENDENCY_UNBLOCKED),
            )
        )
    )
    assert result.outcome is RecommendationOutcome.HUMAN_DECISION
    assert "candidate.tie-exceeds-alternate" in result.reason_codes


def test_incomplete_evidence_fails_closed() -> None:
    result = evaluate_post_pr_state_audit(evidence(landed_capability=""))
    assert result.outcome is RecommendationOutcome.HUMAN_DECISION
    assert "evidence.incomplete" in result.reason_codes


def test_conflicting_evidence_fails_closed() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(
            terminal_state=TerminalPrState.CLOSED_UNMERGED,
            landed_capability="something landed",
        )
    )
    assert result.outcome is RecommendationOutcome.HUMAN_DECISION
    assert "evidence.conflicting" in result.reason_codes


def test_rejects_closed_blocked_stale_claimed_unauthorized_superseded_candidates() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(
            candidates=(
                candidate(issue_number=901, is_closed=True),
                candidate(issue_number=902, is_blocked=True),
                candidate(issue_number=903, is_stale=True),
                candidate(issue_number=904, is_claimed=True),
                candidate(issue_number=905, is_authorized=False),
                candidate(issue_number=906, is_superseded=True),
                candidate(
                    issue_number=907,
                    rank_tier=CandidateRankTier.DEPENDENCY_UNBLOCKED,
                    has_required_evidence=False,
                ),
                candidate(issue_number=910, rank_tier=CandidateRankTier.SAME_SUBSYSTEM_SEQUENCE),
            )
        )
    )
    assert result.outcome is RecommendationOutcome.NEXT_ISSUE
    assert result.recommended_issue == 910


def test_deterministic_output_for_independently_constructed_equal_evidence() -> None:
    first = evaluate_post_pr_state_audit(evidence())
    second = evaluate_post_pr_state_audit(evidence())
    assert first == second
    assert first.audit_id == second.audit_id
    assert first.audit_id.startswith("post-pr-state-audit:")


def test_stable_audit_id_and_reason_code_ordering() -> None:
    result = evaluate_post_pr_state_audit(evidence())
    assert result.reason_codes == tuple(sorted(result.reason_codes))
    assert result.audit_id.startswith("post-pr-state-audit:")


def test_ordinary_formatter_output_is_twelve_to_eighteen_lines() -> None:
    result = evaluate_post_pr_state_audit(evidence())
    rendered = format_post_pr_state_audit(result)
    assert 12 <= len(rendered.splitlines()) <= 18


def test_required_governance_footer_completeness() -> None:
    result = evaluate_post_pr_state_audit(evidence())
    rendered = format_post_pr_state_audit(result)
    for prefix in ("Files:", "Tests:", "Docs:", "Unresolved:", "Handoff:", "Risks:"):
        assert prefix in rendered
    for populated_value in (
        "executor_route.py",
        "pytest focused",
        "executor-route-contract.md",
        "Continue with the next dependency issue.",
        "stale capability evidence",
    ):
        assert populated_value in rendered
    assert result.files_changed == ("executor_route.py",)
    assert result.tests_run == ("pytest focused",)
    assert result.docs_updated == ("executor-route-contract.md",)
    assert result.handoff_recommendation == "Continue with the next dependency issue."
    assert result.remaining_risks == ("stale capability evidence",)


def test_executor_route_is_reused_without_granting_authority() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(candidates=(candidate(executor_route=ExecutorRoute.GOVERNED_RUNNER),))
    )
    assert result.recommended_executor_route is ExecutorRoute.GOVERNED_RUNNER
    assert not hasattr(result, "execution_authorized")
    assert result.side_effects_performed is False


def test_no_eligible_candidates_fails_closed() -> None:
    result = evaluate_post_pr_state_audit(
        evidence(candidates=(candidate(is_blocked=True),))
    )
    assert result.outcome is RecommendationOutcome.HUMAN_DECISION
    assert "candidate.none-eligible" in result.reason_codes


def result_kwargs(**changes: object) -> dict[str, object]:
    baseline: dict[str, object] = dict(
        schema_name=POST_PR_STATE_AUDIT_SCHEMA_NAME,
        schema_version=POST_PR_STATE_AUDIT_SCHEMA_VERSION,
        repository="Blummer92/agent-os",
        pull_request_number=909,
        terminal_state=TerminalPrState.MERGED,
        repository_health=RepositoryHealth.HEALTHY,
        subsystem="executor-orchestration",
        subsystem_maturity=SubsystemMaturity.PROGRESSING,
        landed_capability="deterministic executor-route selection",
        outcome=RecommendationOutcome.NEXT_ISSUE,
        recommended_issue=910,
        alternate_issue=None,
        recommended_executor_route=None,
        rationale="PR #909 merged, unblocking #910.",
        next_action="Open #910.",
        files_changed=(),
        tests_run=(),
        docs_updated=(),
        unresolved_blockers=(),
        handoff_recommendation="",
        remaining_risks=(),
        reason_codes=("state.merged", "candidate.selected"),
    )
    baseline.update(changes)
    return baseline


def test_direct_construction_rejects_duplicate_recommended_and_alternate_issue() -> None:
    with pytest.raises(ValueError):
        PostPrStateAuditResult(
            **result_kwargs(
                alternate_issue=910,
                reason_codes=("state.merged", "candidate.selected", "candidate.alternate"),
            )
        )


def test_direct_construction_requires_human_decision_for_review_complete() -> None:
    with pytest.raises(ValueError):
        PostPrStateAuditResult(
            **result_kwargs(
                terminal_state=TerminalPrState.REVIEW_COMPLETE,
                reason_codes=("state.review-complete", "candidate.selected"),
            )
        )


def test_direct_construction_rejects_alternate_issue_for_blocked() -> None:
    with pytest.raises(ValueError):
        PostPrStateAuditResult(
            **result_kwargs(
                terminal_state=TerminalPrState.BLOCKED,
                recommended_issue=855,
                alternate_issue=856,
                rationale="PR #909 stopped blocked; the controlling blocker #855 is actionable.",
                next_action="Open #855.",
                reason_codes=("state.blocked", "blocker.present"),
            )
        )


def test_direct_construction_rejects_alternate_issue_for_closed_unmerged() -> None:
    with pytest.raises(ValueError):
        PostPrStateAuditResult(
            **result_kwargs(
                terminal_state=TerminalPrState.CLOSED_UNMERGED,
                recommended_issue=920,
                alternate_issue=921,
                rationale="PR #909 closed without merging; verified replacement #920 supersedes it.",
                next_action="Open #920.",
                reason_codes=("state.closed-unmerged", "replacement.verified"),
            )
        )


def test_direct_construction_preserves_valid_merged_result_with_tied_alternate() -> None:
    result = PostPrStateAuditResult(
        **result_kwargs(
            alternate_issue=911,
            reason_codes=("state.merged", "candidate.selected", "candidate.alternate"),
        )
    )
    assert result.recommended_issue == 910
    assert result.alternate_issue == 911


def test_direct_construction_preserves_existing_outcome_consistency_rules() -> None:
    with pytest.raises(ValueError):
        PostPrStateAuditResult(
            **result_kwargs(
                outcome=RecommendationOutcome.HUMAN_DECISION,
                reason_codes=("state.merged", "candidate.none-eligible"),
            )
        )
    with pytest.raises(ValueError):
        PostPrStateAuditResult(
            **result_kwargs(
                recommended_issue=None,
                alternate_issue=None,
                reason_codes=("state.merged", "candidate.none-eligible"),
            )
        )
