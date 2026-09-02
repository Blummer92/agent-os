from __future__ import annotations

from scripts.agent_os_issue_acceptance.evidence_compatibility import (
    CompatibilityEvidenceRecord,
    CompatibilityOutcome,
    ExpectedGeneration,
    evaluate_execution_dispatch_compatibility,
    evaluate_ready_for_review_compatibility,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueState,
    LifecycleStage,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)
from scripts.agent_os_issue_acceptance.lifecycle_reconciliation import (
    LifecycleReconciliationInput,
    ReconciliationOutcome,
    reconcile_lifecycle,
)

SOURCE = "a" * 40
EVIDENCE = "issueplan-current-state:" + "2" * 64
APPROVAL = "approval:" + "1" * 64


def _expected(**overrides: str) -> ExpectedGeneration:
    values = {
        "repository": "Blummer92/agent-os",
        "issue_identity": "issue:1201",
        "authorization_id": "authorization:current",
        "scope_id": "scope:current",
        "head_sha": "b" * 40,
        "environment_id": "environment:current",
        "lifecycle_snapshot_id": "lifecycle:current",
    }
    values.update(overrides)
    return ExpectedGeneration(bindings=tuple(values.items()))


def _record(evidence_id: str, owner: str, **bindings: str) -> CompatibilityEvidenceRecord:
    return CompatibilityEvidenceRecord(
        evidence_id=evidence_id,
        owner=owner,
        bindings=tuple(bindings.items()),
    )


def _authority(state: AuthorizationState) -> AuthorityProjection:
    return AuthorityProjection(
        state=state,
        evidence_id=(
            APPROVAL
            if state in {AuthorizationState.AUTHORIZED, AuthorizationState.STALE}
            else None
        ),
    )


def _reconciliation_input() -> LifecycleReconciliationInput:
    state = build_issue_operational_state(
        IssueOperationalEvidence(
            repository="Blummer92/agent-os",
            issue_number=1201,
            source_revision=SOURCE,
            observed_at="2026-08-23T21:40:00Z",
            evidence_ids=(EVIDENCE,),
            source_state=SourceState.COMPLETE,
            issue_state=IssueState.OPEN,
            lifecycle_stage=LifecycleStage.REVIEW,
            terminal_disposition=TerminalDisposition.NONE,
            readiness=ReadinessState.READY,
            implementation_authorization=_authority(AuthorizationState.AUTHORIZED),
            ready_for_review_authorization=_authority(AuthorizationState.AUTHORIZED),
            execution_authorization=_authority(AuthorizationState.NOT_AUTHORIZED),
            merge_authorization=_authority(AuthorizationState.NOT_AUTHORIZED),
            closure_authorization=_authority(AuthorizationState.NOT_AUTHORIZED),
            external_write_authorization=_authority(AuthorizationState.NOT_AUTHORIZED),
            dependency_state=DependencyState.CLEAR,
            primary_claims=(),
            validation_state=ValidationState.PASSED,
            freshness_state=FreshnessState.CURRENT,
            observed_labels=("status:ready",),
        )
    )
    return LifecycleReconciliationInput(
        repository="Blummer92/agent-os",
        issue_number=1201,
        operational_state=state,
    )


def test_decision_retains_current_expected_bindings_for_consumer_diagnostics() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=_expected(),
        records=(
            _record(
                "runtime:current",
                "runtime",
                repository="Blummer92/agent-os",
                head_sha="b" * 40,
            ),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.COMPATIBLE
    assert dict(decision.expected_bindings)["head_sha"] == "b" * 40
    assert decision.authority_created is False
    assert decision.side_effects_performed is False


def test_ready_for_review_invariants_use_canonical_compatibility_and_reconciliation() -> None:
    stale = evaluate_ready_for_review_compatibility(
        expected=_expected(),
        records=(
            _record("validation:current", "validation", head_sha="b" * 40),
            _record("review:old", "review", head_sha="c" * 40),
        ),
    )
    assert stale.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    assert stale.reacquire_owners == ("review",)

    authorization_drift = evaluate_ready_for_review_compatibility(
        expected=_expected(),
        records=(
            _record(
                "authorization:old",
                "authorization",
                authorization_id="authorization:old",
            ),
        ),
    )
    assert authorization_drift.outcome is CompatibilityOutcome.NEEDS_DECISION

    current = evaluate_ready_for_review_compatibility(
        expected=_expected(),
        records=(
            _record(
                "review:current",
                "review",
                repository="Blummer92/agent-os",
                head_sha="b" * 40,
                lifecycle_snapshot_id="lifecycle:current",
            ),
        ),
    )
    assert current.outcome is CompatibilityOutcome.COMPATIBLE
    result = reconcile_lifecycle(_reconciliation_input())
    assert result.outcome is ReconciliationOutcome.CONSISTENT
    assert result.merge_authorization is AuthorizationState.NOT_AUTHORIZED
    assert result.side_effects_performed is False


def test_execution_dispatch_diagnostic_names_smallest_owner() -> None:
    decision = evaluate_execution_dispatch_compatibility(
        expected=_expected(),
        records=(
            _record(
                "environment:old",
                "environment",
                environment_id="environment:old",
            ),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    assert decision.reacquire_owners == ("environment",)
