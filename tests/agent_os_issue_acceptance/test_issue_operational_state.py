from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scripts.agent_os_issue_acceptance.approval_records import (
    ApprovalApplicabilityResult,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    AdmissionStatus,
    LifecycleMutationAdmissionResult,
)
from scripts.agent_os_issue_acceptance.merge_authorization import (
    MergeAuthorizationApplicabilityResult,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    ClaimState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueOperationalState,
    IssueState,
    LifecycleStage,
    OperationalOutcome,
    PrimaryIssueClaim,
    PrimaryPrState,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
    deserialize_issue_operational_state,
    serialize_issue_operational_state,
)

SOURCE_SHA = "a" * 40
BASE_SHA = "b" * 40
MOVED_BASE_SHA = "c" * 40
EVIDENCE_ID = "issueplan-current-state:" + "1" * 64
APPROVAL_ID = "approval:" + "2" * 64
MERGE_ID = "merge-authorization:" + "3" * 64
LIFECYCLE_ID = "lifecycle-authorization:" + "4" * 64


def authority(
    state: AuthorizationState,
    evidence_id: str | None = None,
    *,
    bound_base_sha: str | None = None,
    observed_base_sha: str | None = None,
) -> AuthorityProjection:
    if evidence_id is None and state in {
        AuthorizationState.AUTHORIZED,
        AuthorizationState.STALE,
        AuthorizationState.NEEDS_DECISION,
    }:
        evidence_id = APPROVAL_ID
    return AuthorityProjection(
        state=state,
        evidence_id=evidence_id,
        bound_base_sha=bound_base_sha,
        observed_base_sha=observed_base_sha,
    )


def evidence(**changes: object) -> IssueOperationalEvidence:
    data: dict[str, object] = {
        "repository": "Blummer92/agent-os",
        "issue_number": 862,
        "source_revision": SOURCE_SHA,
        "observed_at": "2026-08-03T23:30:00Z",
        "evidence_ids": (EVIDENCE_ID, APPROVAL_ID),
        "source_state": SourceState.COMPLETE,
        "issue_state": IssueState.OPEN,
        "lifecycle_stage": LifecycleStage.IMPLEMENTATION,
        "terminal_disposition": TerminalDisposition.NONE,
        "readiness": ReadinessState.READY,
        "implementation_authorization": authority(AuthorizationState.AUTHORIZED),
        "ready_for_review_authorization": authority(
            AuthorizationState.NOT_AUTHORIZED
        ),
        "execution_authorization": authority(AuthorizationState.NOT_AUTHORIZED),
        "merge_authorization": authority(AuthorizationState.NOT_AUTHORIZED),
        "closure_authorization": authority(AuthorizationState.NOT_AUTHORIZED),
        "external_write_authorization": authority(
            AuthorizationState.NOT_AUTHORIZED
        ),
        "dependency_state": DependencyState.CLEAR,
        "primary_claims": (),
        "validation_state": ValidationState.NOT_RUN,
        "freshness_state": FreshnessState.CURRENT,
        "observed_labels": ("status:ready",),
    }
    data.update(changes)
    return IssueOperationalEvidence(**data)


def claim(
    number: int = 900,
    *,
    branch: str = "agent/862-issue-operational-state",
    state: str = "draft",
    head_sha: str = "d" * 40,
) -> PrimaryIssueClaim:
    return PrimaryIssueClaim(
        pull_request_number=number,
        branch=branch,
        head_sha=head_sha,
        state=state,
    )


def test_existing_authorization_contract_results_project_without_re_evaluation():
    approval = ApprovalApplicabilityResult(
        status="applicable",
        approval_id=APPROVAL_ID,
        approval_revision="approval-revision:" + "5" * 64,
        current_proposal_id="draft-task-proposal:" + "6" * 64,
        reason_codes=(),
        changed_bindings=(),
        approval_applicable=True,
    )
    merge = MergeAuthorizationApplicabilityResult(
        status="applicable",
        authorization_id=MERGE_ID,
        authorization_revision="merge-authorization-revision:" + "7" * 64,
        current_pull_request_evidence_id="pull-request-merge-evidence:" + "8" * 64,
        changed_bindings=(),
        reason_codes=(),
        merge_authorized=True,
    )
    lifecycle = LifecycleMutationAdmissionResult(
        requested_mutation="mark-ready",
        admitted=True,
        status=AdmissionStatus.ADMITTED,
        reason_codes=(),
        details=(),
        authorization_id=LIFECYCLE_ID,
        snapshot_id="lifecycle-state-snapshot:" + "9" * 64,
    )

    approval_projection = AuthorityProjection.from_approval_applicability(approval)
    merge_projection = (
        AuthorityProjection.from_merge_authorization_applicability(merge)
    )
    lifecycle_projection = AuthorityProjection.from_lifecycle_admission(lifecycle)

    assert approval_projection.state is AuthorizationState.AUTHORIZED
    assert approval_projection.evidence_id == approval.approval_revision
    assert merge_projection.state is AuthorizationState.AUTHORIZED
    assert merge_projection.evidence_id == merge.authorization_revision
    assert lifecycle_projection.state is AuthorizationState.AUTHORIZED
    assert lifecycle_projection.evidence_id == lifecycle.result_id


def test_needs_decision_projection_can_preserve_missing_authorization_evidence():
    result = ApprovalApplicabilityResult(
        status="needs-decision",
        approval_id=None,
        approval_revision=None,
        current_proposal_id=None,
        reason_codes=("projection.incomplete",),
        changed_bindings=(),
        approval_applicable=False,
    )

    projection = AuthorityProjection.from_approval_applicability(result)

    assert projection.state is AuthorizationState.NEEDS_DECISION
    assert projection.evidence_id is None


def test_fully_ready_does_not_infer_merge_authorization():
    state = build_issue_operational_state(evidence())

    assert state.outcome is OperationalOutcome.READY
    assert state.implementation_authorization.state is AuthorizationState.AUTHORIZED
    assert state.merge_authorization.state is AuthorizationState.NOT_AUTHORIZED
    assert "authorization.merge-not-authorized" in state.blocker_codes
    assert state.side_effects_performed is False


def test_implementation_authorized_does_not_infer_execution_authorization():
    state = build_issue_operational_state(evidence())

    assert state.implementation_authorization.state is AuthorizationState.AUTHORIZED
    assert state.execution_authorization.state is AuthorizationState.NOT_AUTHORIZED
    assert "authorization.execution-not-authorized" in state.reason_codes
    assert state.outcome is OperationalOutcome.READY


def test_closed_issue_wins_over_stale_ready_label():
    state = build_issue_operational_state(
        evidence(
            issue_state=IssueState.CLOSED,
            lifecycle_stage=LifecycleStage.CLOSED,
            terminal_disposition=TerminalDisposition.COMPLETED,
            readiness=ReadinessState.TERMINAL,
        )
    )

    assert state.outcome is OperationalOutcome.TERMINAL
    assert state.reconciliation_required is True
    assert "reconciliation.closed-with-ready-label" in state.reason_codes
    assert state.readiness is ReadinessState.TERMINAL


def test_exact_sha_drift_downgrades_authorization_and_state():
    state = build_issue_operational_state(
        evidence(
            implementation_authorization=authority(
                AuthorizationState.AUTHORIZED,
                bound_base_sha=BASE_SHA,
                observed_base_sha=MOVED_BASE_SHA,
            )
        )
    )

    assert state.outcome is OperationalOutcome.STALE
    assert state.implementation_authorization.state is AuthorizationState.STALE
    assert "authorization.implementation-stale" in state.reason_codes


@pytest.mark.parametrize(
    ("source_state", "outcome", "reason"),
    [
        (SourceState.PARTIAL, OperationalOutcome.NEEDS_DECISION, "source.partial"),
        (SourceState.MISSING, OperationalOutcome.NEEDS_DECISION, "source.missing"),
        (SourceState.UNSUPPORTED, OperationalOutcome.INVALID, "source.unsupported"),
        (
            SourceState.CONFLICTING,
            OperationalOutcome.CONFLICTING,
            "source.conflicting",
        ),
    ],
)
def test_incomplete_or_unsupported_source_fails_closed(source_state, outcome, reason):
    state = build_issue_operational_state(evidence(source_state=source_state))

    assert state.outcome is outcome
    assert reason in state.blocker_codes


def test_competing_primary_claims_are_conflicting():
    state = build_issue_operational_state(
        evidence(
            primary_claims=(
                claim(900),
                claim(901, branch="agent/862-second-claim", head_sha="e" * 40),
            )
        )
    )

    assert state.outcome is OperationalOutcome.CONFLICTING
    assert state.claim_state is ClaimState.CONFLICTING
    assert state.primary_pr_state is PrimaryPrState.CONFLICTING
    assert state.active_branch is None
    assert state.primary_pr_numbers == (900, 901)
    assert "claim.multiple-primary" in state.reason_codes


def test_conflicting_state_requires_at_least_two_primary_pr_numbers():
    valid = build_issue_operational_state(
        evidence(
            primary_claims=(
                claim(900),
                claim(901, branch="agent/862-second-claim", head_sha="e" * 40),
            )
        )
    )

    with pytest.raises(ValueError, match="at least two primary PR numbers"):
        replace(valid, primary_pr_numbers=(), state_id="")
    with pytest.raises(ValueError, match="at least two primary PR numbers"):
        replace(valid, primary_pr_numbers=(900,), state_id="")


def test_valid_conflicting_state_round_trips_without_identity_drift():
    state = build_issue_operational_state(
        evidence(
            primary_claims=(
                claim(900),
                claim(901, branch="agent/862-second-claim", head_sha="e" * 40),
            )
        )
    )
    serialized = serialize_issue_operational_state(state)
    restored = deserialize_issue_operational_state(serialized)

    assert restored == state
    assert restored.state_id == state.state_id
    assert serialize_issue_operational_state(restored) == serialized


def test_serialized_conflicting_state_with_too_few_primary_pr_numbers_fails_closed():
    state = build_issue_operational_state(
        evidence(
            primary_claims=(
                claim(900),
                claim(901, branch="agent/862-second-claim", head_sha="e" * 40),
            )
        )
    )

    payload = state.to_dict()
    payload["primary_pr_numbers"] = []
    payload["state_id"] = ""
    with pytest.raises(ValueError, match="at least two primary PR numbers"):
        deserialize_issue_operational_state(json.dumps(payload))

    payload = state.to_dict()
    payload["primary_pr_numbers"] = [900]
    payload["state_id"] = ""
    with pytest.raises(ValueError, match="at least two primary PR numbers"):
        deserialize_issue_operational_state(json.dumps(payload))


def test_merged_primary_claim_with_open_issue_requires_reconciliation():
    state = build_issue_operational_state(
        evidence(primary_claims=(claim(state="merged"),))
    )

    assert state.outcome is OperationalOutcome.NEEDS_DECISION
    assert state.reconciliation_required is True
    assert state.primary_pr_state is PrimaryPrState.MERGED
    assert "reconciliation.merged-pr-open-issue" in state.blocker_codes


def test_merged_lifecycle_stage_with_open_issue_requires_reconciliation():
    state = build_issue_operational_state(
        evidence(
            lifecycle_stage=LifecycleStage.MERGED,
            primary_claims=(),
        )
    )

    assert state.outcome is OperationalOutcome.NEEDS_DECISION
    assert state.reconciliation_required is True
    assert state.claim_state is ClaimState.NONE
    assert state.primary_pr_state is PrimaryPrState.NONE
    assert "reconciliation.merged-pr-open-issue" in state.blocker_codes


def test_blocked_dependency_blocks_implementation():
    state = build_issue_operational_state(
        evidence(dependency_state=DependencyState.BLOCKED)
    )

    assert state.outcome is OperationalOutcome.BLOCKED
    assert "dependency.blocked" in state.blocker_codes


def test_single_primary_claim_is_preserved_without_creating_authority():
    state = build_issue_operational_state(evidence(primary_claims=(claim(),)))

    assert state.claim_state is ClaimState.SINGLE
    assert state.active_branch == "agent/862-issue-operational-state"
    assert state.primary_pr_numbers == (900,)
    assert state.implementation_authorization.state is AuthorizationState.AUTHORIZED
    assert state.merge_authorization.state is AuthorizationState.NOT_AUTHORIZED


def test_deterministic_order_digest_and_round_trip():
    first = build_issue_operational_state(
        evidence(evidence_ids=(APPROVAL_ID, EVIDENCE_ID))
    )
    second = build_issue_operational_state(evidence())

    assert first == second
    assert first.state_id == second.state_id
    serialized = serialize_issue_operational_state(first)
    restored = deserialize_issue_operational_state(serialized)
    assert restored == first
    assert serialize_issue_operational_state(restored) == serialized
    assert serialized == json.dumps(
        first.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def test_tampered_state_id_is_rejected():
    state = build_issue_operational_state(evidence())
    with pytest.raises(ValueError, match="state_id"):
        replace(state, state_id="issue-operational-state:" + "0" * 64)

    payload = state.to_dict()
    payload["issue_number"] = 999
    with pytest.raises(ValueError, match="state_id"):
        deserialize_issue_operational_state(json.dumps(payload))


def test_unknown_top_level_and_nested_fields_are_rejected():
    state = build_issue_operational_state(evidence())
    payload = state.to_dict()
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="unknown fields"):
        deserialize_issue_operational_state(json.dumps(payload))

    payload = state.to_dict()
    payload["merge_authorization"]["unexpected"] = True
    with pytest.raises(ValueError, match="unknown fields"):
        deserialize_issue_operational_state(json.dumps(payload))


def test_unsupported_schema_and_enum_values_are_rejected():
    state = build_issue_operational_state(evidence())
    payload = state.to_dict()
    payload["schema_version"] = "2.0"
    with pytest.raises(ValueError, match="unsupported"):
        deserialize_issue_operational_state(json.dumps(payload))

    payload = state.to_dict()
    payload["outcome"] = "maybe"
    with pytest.raises(ValueError, match="outcome"):
        deserialize_issue_operational_state(json.dumps(payload))


def test_malformed_serialized_payloads_are_rejected():
    with pytest.raises(ValueError, match="valid JSON"):
        deserialize_issue_operational_state("{")
    with pytest.raises(TypeError, match="JSON object"):
        deserialize_issue_operational_state("[]")
    with pytest.raises(TypeError, match="built-in string"):
        deserialize_issue_operational_state(b"{}")


def test_authority_dimensions_remain_separate():
    state = build_issue_operational_state(
        evidence(
            ready_for_review_authorization=authority(
                AuthorizationState.AUTHORIZED, LIFECYCLE_ID
            ),
            merge_authorization=authority(AuthorizationState.AUTHORIZED, MERGE_ID),
            closure_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
        )
    )

    assert state.ready_for_review_authorization.state is AuthorizationState.AUTHORIZED
    assert state.merge_authorization.state is AuthorizationState.AUTHORIZED
    assert state.closure_authorization.state is AuthorizationState.NOT_AUTHORIZED
    assert "authorization.closure-not-authorized" in state.blocker_codes
    assert "status" not in state.to_dict()


def test_validation_and_freshness_fail_closed():
    failed = build_issue_operational_state(
        evidence(validation_state=ValidationState.FAILED)
    )
    stale = build_issue_operational_state(
        evidence(freshness_state=FreshnessState.STALE)
    )

    assert failed.outcome is OperationalOutcome.BLOCKED
    assert "validation.failed" in failed.reason_codes
    assert stale.outcome is OperationalOutcome.STALE
    assert "source.stale" in stale.reason_codes


def test_input_collections_are_strict_and_bounded():
    with pytest.raises(TypeError, match="exact tuple"):
        evidence(evidence_ids=[EVIDENCE_ID])
    with pytest.raises(ValueError, match="duplicates"):
        evidence(evidence_ids=(EVIDENCE_ID, EVIDENCE_ID))
    with pytest.raises(ValueError, match="duplicate pull request"):
        evidence(primary_claims=(claim(), claim()))


def test_no_builder_generates_time_or_performs_side_effects():
    supplied = evidence(observed_at="2026-01-02T03:04:05Z")
    state = build_issue_operational_state(supplied)

    assert state.observed_at == "2026-01-02T03:04:05Z"
    assert state.side_effects_performed is False
    assert state.to_dict()["side_effects_performed"] is False



def test_non_gating_stale_authority_makes_operational_state_stale():
    state = build_issue_operational_state(
        evidence(
            closure_authorization=authority(AuthorizationState.STALE),
        )
    )

    assert state.outcome is OperationalOutcome.STALE
    assert (
        state.implementation_authorization.state
        is AuthorizationState.AUTHORIZED
    )
    assert state.closure_authorization.state is AuthorizationState.STALE
    assert "authorization.closure-stale" in state.reason_codes


def test_excessively_nested_serialized_payload_fails_with_value_error(monkeypatch):
    def raise_recursion_error(_serialized):
        raise RecursionError("too deeply nested")

    monkeypatch.setattr(
        "scripts.agent_os_issue_acceptance.issue_operational_state.json.loads",
        raise_recursion_error,
    )

    with pytest.raises(ValueError, match="nested too deeply"):
        deserialize_issue_operational_state("{}")
