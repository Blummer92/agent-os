from __future__ import annotations

import pytest

from agent_os_execution_service.connected_issue_creation_facade import plan_connected_issue_creation_for_host


BODY = """### Issue tier

tier:1-standard-implementation

### Primary owner

owner:github-service-agent

### Readiness candidate

status:ready

### Work type

type:bug

### Source of truth

GitHub

### External write boundary

no-external-write

### Prior scope, duplicate, and supersession review

Reviewed current open bug owners and found one distinct repair seam.
"""


def test_host_projection_reuses_canonical_connected_creation_labels() -> None:
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
        duplicate_review_disposition="NEW_DISTINCT_BUG",
    )
    assert set(result["proposed_labels"]) == {
        "agent-os",
        "owner:github-service-agent",
        "status:ready",
        "type:bug",
    }
    assert result["create_allowed"] is True
    assert result["next_operation"] == "create-then-canonical-readback-and-converge"
    assert result["reconciliation_owner"] == "#1962"


def test_host_projection_never_creates_authority() -> None:
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
        duplicate_review_disposition="NEW_DISTINCT_BUG",
    )
    assert result["implementation_authorized"] is False
    assert result["merge_authorized"] is False
    assert result["closure_authorized"] is False
    assert result["external_write_authorized"] is False
    assert result["side_effects_performed"] is False


def test_missing_duplicate_review_disposition_blocks_create() -> None:
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
    )
    assert result["create_allowed"] is False
    assert result["duplicate_review_disposition"] == "MANUAL_REVIEW"
    assert result["next_operation"] == "manual-review-duplicate-admission-required"


def test_recurrence_returns_canonical_owner_without_create() -> None:
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
        duplicate_review_disposition="RECURRENCE_EXISTING_OWNER",
        canonical_issue_number=2283,
    )
    assert result["create_allowed"] is False
    assert result["canonical_issue_number"] == 2283
    assert result["next_operation"] == "append-recurrence-evidence-to-canonical-issue"


def test_focused_successor_requires_explicit_distinct_seam() -> None:
    blocked = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
        duplicate_review_disposition="FOCUSED_SUCCESSOR",
        canonical_issue_number=2283,
    )
    admitted = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
        duplicate_review_disposition="FOCUSED_SUCCESSOR",
        canonical_issue_number=2283,
        distinct_repair_seam=True,
    )
    assert blocked["create_allowed"] is False
    assert blocked["duplicate_review_disposition"] == "MANUAL_REVIEW"
    assert admitted["create_allowed"] is True
    assert admitted["duplicate_review_disposition"] == "FOCUSED_SUCCESSOR"


def test_missing_canonical_metadata_fails_closed() -> None:
    with pytest.raises(ValueError, match="canonical tiered metadata"):
        plan_connected_issue_creation_for_host(
            repository="Blummer92/agent-os",
            issue_body="Source of truth: GitHub",
            duplicate_review_disposition="NEW_DISTINCT_BUG",
        )


def test_repository_identity_is_bounded() -> None:
    with pytest.raises(ValueError, match="owner/name"):
        plan_connected_issue_creation_for_host(
            repository="agent-os",
            issue_body=BODY,
            duplicate_review_disposition="NEW_DISTINCT_BUG",
        )


def test_admitted_create_projects_nonterminal_readback_convergence_contract() -> None:
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
        duplicate_review_disposition="NEW_DISTINCT_BUG",
    )
    assert result["create_contract"] == "canonical-labels-readback-convergence-required"
    assert result["create_response_terminal"] is False
    assert result["post_create_readback_required"] is True
    assert result["post_create_reconciliation_required_on_mismatch"] is True
    assert result["terminal_success_requires_label_convergence"] is True


def test_blocked_create_does_not_project_post_create_work() -> None:
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
    )
    assert result["create_response_terminal"] is False
    assert result["post_create_readback_required"] is False
    assert result["post_create_reconciliation_required_on_mismatch"] is False
    assert result["terminal_success_requires_label_convergence"] is False
