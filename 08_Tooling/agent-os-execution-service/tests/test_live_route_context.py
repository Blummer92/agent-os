from __future__ import annotations

from dataclasses import dataclass

import pytest

from agent_os_execution_service.live_route_context import (
    ExactSourceLineage,
    LiveRouteContextError,
    StructuredPullRequest,
    verify_exact_lineage,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import LifecycleStage


SHA = "a" * 40
OTHER = "b" * 40


def lineage(**changes) -> ExactSourceLineage:
    values = dict(
        source_capsule_id="pre-publication-evidence:" + "1" * 64,
        repository="Blummer92/agent-os",
        issue_number=1239,
        branch="agent/1239-live",
        source_sha=SHA,
        tested_sha=SHA,
    )
    values.update(changes)
    return ExactSourceLineage(**values)


@dataclass
class Reader:
    head: str = SHA
    prs: tuple[StructuredPullRequest, ...] = ()

    def current_branch_head(self, repository: str, branch: str) -> str:
        return self.head

    def pull_requests_for_head(
        self, repository: str, branch: str
    ) -> tuple[StructuredPullRequest, ...]:
        return self.prs


def pr(*, draft=True, merged=False, state="open", head=SHA, branch="agent/1239-live"):
    return StructuredPullRequest(
        number=2000,
        branch=branch,
        head_sha=head,
        draft=draft,
        merged=merged,
        state=state,
    )


def test_no_pr_is_truthful_implementation_lineage() -> None:
    result = verify_exact_lineage(lineage(), reader=Reader(), issue_open=True)
    assert result.lifecycle_stage is LifecycleStage.IMPLEMENTATION
    assert result.primary_claims == ()
    assert result.current_head_sha == SHA


def test_draft_pr_projects_existing_claim_and_draft_stage() -> None:
    result = verify_exact_lineage(
        lineage(), reader=Reader(prs=(pr(),)), issue_open=True
    )
    assert result.lifecycle_stage is LifecycleStage.DRAFT_PR
    assert result.primary_claim is not None
    assert result.primary_claim.state == "draft"
    assert result.primary_claim.branch == "agent/1239-live"
    assert result.primary_claim.head_sha == SHA


def test_ready_pr_projects_review_stage() -> None:
    result = verify_exact_lineage(
        lineage(), reader=Reader(prs=(pr(draft=False),)), issue_open=True
    )
    assert result.lifecycle_stage is LifecycleStage.REVIEW
    assert result.primary_claim.state == "ready"


def test_merged_pr_projects_merged_stage() -> None:
    result = verify_exact_lineage(
        lineage(), reader=Reader(prs=(pr(draft=False, merged=True, state="closed"),)), issue_open=True
    )
    assert result.lifecycle_stage is LifecycleStage.MERGED
    assert result.primary_claim.state == "merged"


def test_closed_issue_projects_closed_only_for_nonconflicting_lineage() -> None:
    result = verify_exact_lineage(
        lineage(), reader=Reader(prs=(pr(draft=False, merged=True, state="closed"),)), issue_open=False
    )
    assert result.lifecycle_stage is LifecycleStage.CLOSED


def test_head_drift_fails_closed() -> None:
    with pytest.raises(LiveRouteContextError, match="source-lineage-stale"):
        verify_exact_lineage(lineage(), reader=Reader(head=OTHER), issue_open=True)


def test_tested_source_drift_fails_closed() -> None:
    with pytest.raises(LiveRouteContextError, match="source-lineage-stale"):
        verify_exact_lineage(
            lineage(tested_sha=OTHER), reader=Reader(), issue_open=True
        )


def test_multiple_matching_prs_fail_closed() -> None:
    second = StructuredPullRequest(
        number=2001,
        branch="agent/1239-live",
        head_sha=SHA,
        draft=True,
        merged=False,
        state="open",
    )
    with pytest.raises(LiveRouteContextError, match="source-lineage-ambiguous"):
        verify_exact_lineage(
            lineage(), reader=Reader(prs=(pr(), second)), issue_open=True
        )


def test_cross_lineage_pr_is_not_promoted_to_claim() -> None:
    result = verify_exact_lineage(
        lineage(),
        reader=Reader(prs=(pr(branch="agent/other"),)),
        issue_open=True,
    )
    assert result.primary_claims == ()
    assert result.lifecycle_stage is LifecycleStage.IMPLEMENTATION


def test_closed_issue_with_unmerged_pr_fails_closed() -> None:
    with pytest.raises(LiveRouteContextError, match="closed-issue-lineage-conflict"):
        verify_exact_lineage(
            lineage(), reader=Reader(prs=(pr(),)), issue_open=False
        )
