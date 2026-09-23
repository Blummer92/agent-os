from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueState,
    LifecycleStage,
    OperationalOutcome,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)


def _authority():
    return AuthorityProjection(state=AuthorizationState.NOT_APPLICABLE)


def _evidence(**overrides):
    base = dict(
        repository="Blummer92/agent-os",
        issue_number=2154,
        source_revision="a" * 40,
        observed_at="2026-09-09T12:00:00Z",
        evidence_ids=(),
        source_state=SourceState.COMPLETE,
        issue_state=IssueState.OPEN,
        lifecycle_stage=LifecycleStage.PLANNING,
        terminal_disposition=TerminalDisposition.COMPLETED,
        readiness=ReadinessState.TERMINAL,
        implementation_authorization=_authority(),
        ready_for_review_authorization=_authority(),
        execution_authorization=_authority(),
        merge_authorization=_authority(),
        closure_authorization=_authority(),
        external_write_authorization=_authority(),
        dependency_state=DependencyState.CLEAR,
        primary_claims=(),
        validation_state=ValidationState.NOT_RUN,
        freshness_state=FreshnessState.CURRENT,
    )
    base.update(overrides)
    return IssueOperationalEvidence(**base)


def test_completed_investigation_is_terminal_without_requiring_implementation_stage():
    state = build_issue_operational_state(_evidence())
    assert state.outcome is OperationalOutcome.TERMINAL
    assert state.terminal_disposition is TerminalDisposition.COMPLETED
    assert state.lifecycle_stage is LifecycleStage.PLANNING
    assert "lifecycle.terminal-disposition" in state.reason_codes


def test_investigation_without_final_disposition_is_not_terminal():
    state = build_issue_operational_state(
        _evidence(
            terminal_disposition=TerminalDisposition.NONE,
            readiness=ReadinessState.READY,
            implementation_authorization=AuthorityProjection(
                state=AuthorizationState.NOT_AUTHORIZED
            ),
        )
    )
    assert state.outcome is OperationalOutcome.BLOCKED
    assert "lifecycle.terminal-disposition" not in state.reason_codes
