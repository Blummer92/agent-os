from dataclasses import replace

import pytest

from scripts.agent_os_issue_acceptance.coding_cockpit_view import (
    build_coding_cockpit_view,
    render_coding_cockpit_view,
)
from scripts.agent_os_issue_acceptance.coding_command_center_handoff import (
    CodingCommandCenterEvidence,
    build_coding_command_center_handoff,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueState,
    LifecycleStage,
    PrimaryIssueClaim,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)

SHA = "a" * 40
AUTH_ID = "approval:" + "c" * 64


def _authority(state):
    return AuthorityProjection(
        state=state,
        evidence_id=AUTH_ID if state in {AuthorizationState.AUTHORIZED, AuthorizationState.STALE} else None,
    )


def _state(**overrides):
    values = dict(
        repository="Blummer92/agent-os",
        issue_number=1097,
        source_revision=SHA,
        observed_at="2026-09-16T17:00:00Z",
        evidence_ids=(),
        source_state=SourceState.COMPLETE,
        issue_state=IssueState.OPEN,
        lifecycle_stage=LifecycleStage.IMPLEMENTATION,
        terminal_disposition=TerminalDisposition.NONE,
        readiness=ReadinessState.READY,
        implementation_authorization=_authority(AuthorizationState.AUTHORIZED),
        ready_for_review_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
        execution_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
        merge_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
        closure_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
        external_write_authorization=_authority(AuthorizationState.NOT_APPLICABLE),
        dependency_state=DependencyState.CLEAR,
        primary_claims=(),
        validation_state=ValidationState.NOT_RUN,
        freshness_state=FreshnessState.CURRENT,
        observed_labels=(),
    )
    values.update(overrides)
    return build_issue_operational_state(IssueOperationalEvidence(**values))


def _view(state):
    handoff = build_coding_command_center_handoff(
        CodingCommandCenterEvidence(
            operational_state=state,
            source_revision=SHA,
            validation_evidence_reference="check:aggregate" if state.validation_state is ValidationState.PASSED else None,
        )
    )
    return build_coding_cockpit_view(handoff, state)


def test_active_pr_view_exposes_identity_validation_and_freshness():
    claim = PrimaryIssueClaim(42, "agent/example", SHA, "ready")
    view = _view(_state(primary_claims=(claim,), validation_state=ValidationState.PASSED))
    assert view.pull_request_number == 42
    assert view.branch == "agent/example"
    assert view.exact_head_sha == SHA
    assert view.validation_state == "passed"
    assert view.freshness == "current"
    assert view.authority_created is False
    assert view.side_effects_performed is False


def test_blocked_and_manual_review_states_are_visible_without_authority_gain():
    blocked = _view(_state(readiness=ReadinessState.BLOCKED))
    assert blocked.state == "blocked"
    assert blocked.primary_blocker is not None
    assert blocked.manual_review_required is False

    decision = _view(_state(readiness=ReadinessState.NEEDS_DECISION))
    assert decision.state == "needs-decision"
    assert decision.manual_review_required is True


def test_stale_state_is_explicit_and_fail_closed():
    view = _view(_state(freshness_state=FreshnessState.STALE))
    assert view.state == "stale"
    assert view.freshness == "stale"
    assert view.manual_review_required is True
    assert view.smallest_next_action.startswith("reacquire current canonical evidence")


def test_idle_shape_keeps_missing_pr_and_head_explicitly_unavailable():
    rendered = render_coding_cockpit_view(_view(_state()))
    assert "PR unavailable" in rendered
    assert "unavailable | unavailable" in rendered
    assert "Authority: display-only; no authority created" in rendered


def test_identity_mismatch_is_rejected():
    state = _state()
    handoff = build_coding_command_center_handoff(CodingCommandCenterEvidence(operational_state=state, source_revision=SHA))
    with pytest.raises(ValueError, match="same canonical state"):
        build_coding_cockpit_view(replace(handoff, issue_number=999), state)


def test_identical_input_renders_deterministically():
    view = _view(_state(validation_state=ValidationState.FAILED))
    assert render_coding_cockpit_view(view) == render_coding_cockpit_view(view)
