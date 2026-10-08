from __future__ import annotations

import pytest

from scripts.agent_os_issue_labels.connected_issue_creation import DuplicateCandidateEvidence

from agent_os_execution_service.connected_issue_creation_facade import (
    create_connected_issue_for_host,
    plan_connected_issue_creation_for_host,
)


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


def candidate(issue_number: int) -> DuplicateCandidateEvidence:
    return DuplicateCandidateEvidence(
        issue_number=issue_number,
        state="open",
        objective_evidence="candidate objective inspected",
        causal_seam_evidence="candidate causal seam inspected",
        acceptance_evidence="candidate acceptance inspected",
        boundary_evidence="candidate boundary inspected",
    )


def distinct_kwargs() -> dict[str, object]:
    return {
        "duplicate_review_disposition": "NEW_DISTINCT_BUG",
        "candidate_enumeration_complete": True,
    }


def test_host_projection_reuses_canonical_connected_creation_labels() -> None:
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
        **distinct_kwargs(),
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
        **distinct_kwargs(),
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
        candidate_evidence=(candidate(2283),),
        candidate_enumeration_complete=True,
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
        candidate_evidence=(candidate(2283),),
        candidate_enumeration_complete=True,
    )
    admitted = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
        duplicate_review_disposition="FOCUSED_SUCCESSOR",
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283),),
        candidate_enumeration_complete=True,
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
            **distinct_kwargs(),
        )


def test_repository_identity_is_bounded() -> None:
    with pytest.raises(ValueError, match="owner/name"):
        plan_connected_issue_creation_for_host(
            repository="agent-os",
            issue_body=BODY,
            **distinct_kwargs(),
        )


def test_admitted_create_projects_nonterminal_readback_convergence_contract() -> None:
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
        **distinct_kwargs(),
    )
    assert result["create_contract"] == "canonical-labels-readback-convergence-required"
    assert result["create_response_terminal"] is False
    assert result["post_create_readback_required"] is True
    assert result["post_create_reconciliation_required_on_mismatch"] is True
    assert result["terminal_success_requires_label_convergence"] is True



def test_2905_ready_label_is_bound_into_required_post_create_readback():
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
        **distinct_kwargs(),
    )
    assert "status:ready" in result["required_managed_label_readback"]
    assert set(result["required_managed_label_readback"]) == set(result["proposed_labels"])
    assert result["missing_required_managed_label_action"] == "reconcile-via-1962-before-terminal"


def test_2905_blocked_create_has_no_post_create_label_obligation():
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
    )
    assert result["required_managed_label_readback"] == []
    assert result["missing_required_managed_label_action"] is None


def test_blocked_create_does_not_project_post_create_work() -> None:
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=BODY,
    )
    assert result["create_response_terminal"] is False
    assert result["post_create_readback_required"] is False
    assert result["post_create_reconciliation_required_on_mismatch"] is False
    assert result["terminal_success_requires_label_convergence"] is False


class _FakeCreateProvider:
    def __init__(self, initial_labels):
        self.labels = tuple(initial_labels)
        self.created_with = ()
        self.read_count = 0
        self.reconcile_count = 0

    def create(self, repository, title, body, labels):
        self.created_with = tuple(labels)
        return 3057

    def read_labels(self, repository, issue_number):
        self.read_count += 1
        return self.labels

    def reconcile(self, repository, issue_number):
        self.reconcile_count += 1
        self.labels = (
            "agent-os",
            "owner:github-service-agent",
            "status:ready",
            "type:bug",
        )
        return self.labels


def test_3027_zero_label_native_create_reconciles_before_terminal_success():
    provider = _FakeCreateProvider(())
    result = create_connected_issue_for_host(
        provider,
        repository="Blummer92/agent-os",
        title="BUG - zero labels",
        issue_body=BODY,
        **distinct_kwargs(),
    )
    assert set(provider.created_with) == set(result.required_managed_labels)
    assert provider.reconcile_count == 1
    assert provider.read_count == 2
    assert result.reconciliation_performed is True
    assert result.terminal_success is True


def test_3027_partial_label_native_create_reconciles_before_terminal_success():
    provider = _FakeCreateProvider(("agent-os", "type:bug"))
    result = create_connected_issue_for_host(
        provider,
        repository="Blummer92/agent-os",
        title="BUG - partial labels",
        issue_body=BODY,
        **distinct_kwargs(),
    )
    assert provider.reconcile_count == 1
    assert result.terminal_success is True


def test_3027_already_converged_create_is_idempotent():
    provider = _FakeCreateProvider(
        ("agent-os", "owner:github-service-agent", "status:ready", "type:bug")
    )
    result = create_connected_issue_for_host(
        provider,
        repository="Blummer92/agent-os",
        title="BUG - converged",
        issue_body=BODY,
        **distinct_kwargs(),
    )
    assert provider.reconcile_count == 0
    assert provider.read_count == 1
    assert result.reconciliation_performed is False
    assert result.terminal_success is True


def test_3027_reconciliation_mismatch_cannot_terminalize():
    class _NonConvergingProvider(_FakeCreateProvider):
        def reconcile(self, repository, issue_number):
            self.reconcile_count += 1
            self.labels = ("agent-os",)
            return self.labels

    provider = _NonConvergingProvider(())
    result = create_connected_issue_for_host(
        provider,
        repository="Blummer92/agent-os",
        title="BUG - still missing labels",
        issue_body=BODY,
        **distinct_kwargs(),
    )
    assert provider.reconcile_count == 1
    assert provider.read_count == 2
    assert result.terminal_success is False
    assert result.reason_codes == ("connected-create-label-convergence-not-proven",)


def test_3027_malformed_minimal_body_fails_before_native_create():
    provider = _FakeCreateProvider(())
    with pytest.raises(ValueError, match="canonical tiered metadata"):
        create_connected_issue_for_host(
            provider,
            repository="Blummer92/agent-os",
            title="BUG - malformed body",
            issue_body="## Summary\nMissing canonical classification.",
            **distinct_kwargs(),
        )
    assert provider.created_with == ()
    assert provider.read_count == 0
    assert provider.reconcile_count == 0


# Realistic body shaped like production host-created issues (bare key:value
# metadata lead block, #3407 shape; see #3092 root-cause investigation).
# The canonical planner must derive labels from it through the facade.
REALISTIC_BARE_KV_BODY = """tier:1-standard-implementation
owner:chatgpt-orchestrator
status:needs-decision
type:bug
Source of truth: GitHub
External-write boundary: no-external-write

## Prior scope, duplicate, and supersession review

Reviewed current open bug owners and found one distinct repair seam.

## Reproduction

Shared-file overlap was interpreted as combination permission.
"""


def test_host_projection_plans_labels_for_realistic_bare_kv_body() -> None:
    result = plan_connected_issue_creation_for_host(
        repository="Blummer92/agent-os",
        issue_body=REALISTIC_BARE_KV_BODY,
        **distinct_kwargs(),
    )
    assert set(result["proposed_labels"]) == {
        "agent-os",
        "owner:chatgpt-orchestrator",
        "status:needs-decision",
        "type:bug",
    }
    assert result["create_allowed"] is True
    assert result["terminal_success_requires_label_convergence"] is True
    assert result["post_create_readback_required"] is True
    assert result["side_effects_performed"] is False
