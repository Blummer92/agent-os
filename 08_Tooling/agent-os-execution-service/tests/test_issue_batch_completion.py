from __future__ import annotations

from agent_os_execution_service.issue_batch_completion import classify_issue_batch_completion

REPOSITORY = "Blummer92/agent-os"


def pr_lane(issue: int, pr: int) -> dict[str, object]:
    return {
        "issue_number": issue,
        "current_state": "open-ready",
        "repository_gap": "yes",
        "implementation_authorized": True,
        "pr_required": "yes",
        "pr_number": pr,
        "remaining_owner": "GitHub Service Agent",
        "branch_exists": True,
        "implementation_commit_count": 1,
        "draft_pr_exists": True,
        "canonical_pr_readback_verified": True,
        "capable_route_available": True,
        "subordinate_writes_only": False,
    }


def no_pr_lane(issue: int, reason: str = "external-only") -> dict[str, object]:
    return {
        "issue_number": issue,
        "current_state": "open-external-boundary",
        "repository_gap": "no",
        "implementation_authorized": False,
        "pr_required": "no",
        "pr_number": None,
        "no_pr_reason": reason,
        "canonical_no_pr_evidence_verified": True,
        "remaining_owner": "ChatGPT Orchestrator",
    }


def test_2600_1386_recurrence_requires_pr_or_explicit_external_only_proof() -> None:
    result = classify_issue_batch_completion(
        repository=REPOSITORY,
        issue_number=1241,
        lane_evidence=[pr_lane(2600, 2606), no_pr_lane(1386)],
    )
    assert result["terminal"] is True
    assert result["unfinished_issue_numbers"] == []
    assert result["lanes"][0]["pr_number"] == 2606
    assert result["lanes"][0]["terminal"] is True
    assert result["lanes"][1]["no_pr_reason"] == "external-only"
    assert result["lanes"][1]["terminal"] is True
    assert result["agent_os_continuation"]["terminal"] is True
    assert result["github_writes_authorized"] is False
    assert result["merge_authorized"] is False


def test_repository_ready_lane_without_canonical_pr_readback_keeps_batch_unfinished() -> None:
    lane = pr_lane(2600, 2606)
    lane["canonical_pr_readback_verified"] = False
    result = classify_issue_batch_completion(
        repository=REPOSITORY,
        issue_number=1241,
        lane_evidence=[lane, no_pr_lane(1386)],
    )
    assert result["terminal"] is False
    assert result["unfinished_issue_numbers"] == [2600]
    assert "canonical-pr-readback-not-proven" in result["lanes"][0]["reason_codes"]
    assert result["agent_os_continuation"]["action"] == "continue-incomplete-issue-lanes"


def test_external_lane_without_canonical_no_pr_evidence_is_not_terminal() -> None:
    lane = no_pr_lane(1386)
    lane["canonical_no_pr_evidence_verified"] = False
    result = classify_issue_batch_completion(
        repository=REPOSITORY,
        issue_number=1241,
        lane_evidence=[pr_lane(2600, 2606), lane],
    )
    assert result["terminal"] is False
    assert result["unfinished_issue_numbers"] == [1386]
    assert result["lanes"][1]["reason_codes"] == ["canonical-no-pr-evidence-not-proven"]


def test_authorized_repository_gap_cannot_be_hidden_as_no_pr_terminal() -> None:
    lane = no_pr_lane(2607, "authorization-blocked")
    lane["repository_gap"] = "yes"
    lane["implementation_authorized"] = True
    result = classify_issue_batch_completion(
        repository=REPOSITORY,
        issue_number=2607,
        lane_evidence=[lane],
    )
    assert result["terminal"] is False
    assert result["lanes"][0]["reason_codes"] == [
        "authorized-repository-gap-cannot-use-no-pr-terminal"
    ]


def test_unknown_lane_classification_cannot_complete_batch() -> None:
    lane = no_pr_lane(1386)
    lane["repository_gap"] = "unknown"
    lane["pr_required"] = "unknown"
    result = classify_issue_batch_completion(
        repository=REPOSITORY,
        issue_number=1241,
        lane_evidence=[lane],
    )
    assert result["terminal"] is False
    assert result["lanes"][0]["reason_codes"] == ["lane-terminal-classification-unknown"]


def test_duplicate_lane_numbers_are_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="unique"):
        classify_issue_batch_completion(
            repository=REPOSITORY,
            issue_number=1241,
            lane_evidence=[pr_lane(2600, 2606), no_pr_lane(2600)],
        )
