from dataclasses import replace

from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorizationState,
    IssueState,
    LifecycleStage,
    OperationalOutcome,
    PrimaryIssueClaim,
    build_issue_operational_state,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    EnvironmentCapabilityEvidence,
    EnvironmentCapabilityState,
    RequestedMode,
    evaluate_operating_mode_decision,
)
from scripts.agent_os_issue_acceptance.recoverable_reconciliation import (
    normalize_recoverable_reconciliation,
)

from tests.agent_os_issue_acceptance.test_operating_mode import authority, evidence


def _merged_open_state(**changes):
    base = evidence(
        lifecycle_stage=LifecycleStage.MERGED,
        issue_state=IssueState.OPEN,
        primary_claims=(
            PrimaryIssueClaim(
                pull_request_number=999,
                branch="agent/issue-901",
                head_sha="d" * 40,
                state="merged",
            ),
        ),
        closure_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
    )
    if changes:
        base = replace(base, **changes)
    return build_issue_operational_state(base)


def _environment():
    return EnvironmentCapabilityEvidence(
        local_execution_state=EnvironmentCapabilityState.VERIFIED,
        push_state=EnvironmentCapabilityState.VERIFIED,
        evidence_id="environment-capability:" + "2" * 64,
    )


def test_merged_open_drift_is_reason_not_blocker():
    normalized = normalize_recoverable_reconciliation(_merged_open_state())
    assert normalized.reconciliation_required is True
    assert "reconciliation.merged-pr-open-issue" in normalized.reason_codes
    assert "reconciliation.merged-pr-open-issue" not in normalized.blocker_codes
    assert normalized.outcome is OperationalOutcome.READY
    assert normalized.lifecycle_stage is LifecycleStage.MERGED


def test_operating_mode_does_not_rewind_recoverable_merged_state():
    normalized = normalize_recoverable_reconciliation(_merged_open_state())
    decision = evaluate_operating_mode_decision(normalized, RequestedMode.RELEASE.value, _environment())
    assert decision.highest_completed_stage is LifecycleStage.MERGED
    assert decision.maximum_permitted_stage is LifecycleStage.MERGED
    assert decision.next_permitted_action == "none"
    assert "authorization.closure-not-authorized" in decision.blocker_codes


def test_reclassification_does_not_create_closure_authority():
    normalized = normalize_recoverable_reconciliation(_merged_open_state())
    assert normalized.closure_authorization.state is AuthorizationState.NOT_AUTHORIZED


def test_genuine_blocker_survives_reconciliation_normalization():
    state = _merged_open_state(
        dependency_state=__import__(
            "scripts.agent_os_issue_acceptance.issue_operational_state",
            fromlist=["DependencyState"],
        ).DependencyState.BLOCKED
    )
    normalized = normalize_recoverable_reconciliation(state)
    assert "dependency.blocked" in normalized.blocker_codes
    assert normalized.outcome is not OperationalOutcome.READY


def test_authority_projections_survive_blocker_normalization():
    """Clearing blockers must not clear authority.

    Normalization drops the recoverable drift code and the `authorization.*`
    codes that `evaluate_operating_mode_decision` re-derives for itself. The
    AuthorityProjection fields it derives them *from* stay untouched, so no
    authority is granted by the reclassification (#2152 non-goal: "no new
    authority").
    """
    state = _merged_open_state()
    normalized = normalize_recoverable_reconciliation(state)

    assert normalized.blocker_codes == ()
    for field in (
        "implementation_authorization",
        "ready_for_review_authorization",
        "execution_authorization",
        "merge_authorization",
        "closure_authorization",
        "external_write_authorization",
    ):
        assert getattr(normalized, field) == getattr(state, field), field

    # The dropped authorization codes come back from the evaluator, not from a
    # stored blocker list, so fail-closed behaviour is preserved end to end.
    decision = evaluate_operating_mode_decision(
        normalized, RequestedMode.RELEASE.value, _environment()
    )
    assert "authorization.closure-not-authorized" in decision.blocker_codes
    assert decision.next_permitted_action == "none"


def test_non_authority_blocker_still_dominates_alongside_authorization_codes():
    """Only re-derived authorization codes are ignored by the dominance check."""
    state = _merged_open_state(
        dependency_state=__import__(
            "scripts.agent_os_issue_acceptance.issue_operational_state",
            fromlist=["DependencyState"],
        ).DependencyState.BLOCKED
    )
    assert any(code.startswith("authorization.") for code in state.blocker_codes)

    normalized = normalize_recoverable_reconciliation(state)

    assert "dependency.blocked" in normalized.blocker_codes
    assert "reconciliation.merged-pr-open-issue" not in normalized.blocker_codes
    assert normalized.outcome is not OperationalOutcome.READY
