from __future__ import annotations

import pytest

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
)
from scripts.agent_os_issue_acceptance.ready_for_review_compatibility import (
    reconcile_ready_for_review,
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


def test_ready_for_review_consumer_rejects_old_review_before_reconciliation() -> None:
    decision = evaluate_ready_for_review_compatibility(
        expected=_expected(),
        records=(
            _record("validation:current", "validation", head_sha="b" * 40),
            _record("review:old", "review", head_sha="c" * 40),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.REACQUIRE_REQUIRED
    with pytest.raises(RuntimeError, match="reacquire=review"):
        reconcile_ready_for_review(
            _reconciliation_input(), compatibility_decision=decision
        )


def test_ready_for_review_consumer_rejects_authorization_drift() -> None:
    decision = evaluate_ready_for_review_compatibility(
        expected=_expected(),
        records=(
            _record(
                "authorization:old",
                "authorization",
                authorization_id="authorization:old",
            ),
        ),
    )
    assert decision.outcome is CompatibilityOutcome.NEEDS_DECISION
    with pytest.raises(RuntimeError, match="needs-decision"):
        reconcile_ready_for_review(
            _reconciliation_input(), compatibility_decision=decision
        )


def test_compatible_ready_for_review_decision_reuses_existing_reconciliation() -> None:
    decision = evaluate_ready_for_review_compatibility(
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
    result = reconcile_ready_for_review(
        _reconciliation_input(), compatibility_decision=decision
    )
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
