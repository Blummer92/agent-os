from dataclasses import replace

import pytest

from scripts.agent_os_issue_acceptance.coding_command_center_handoff import (
    CodingCommandCenterEvidence,
    build_coding_command_center_handoff,
    render_coding_command_center_handoff,
    serialize_coding_command_center_handoff,
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
AUTH_ID = "approval:" + "b" * 64


def _authority(state: AuthorizationState) -> AuthorityProjection:
    return AuthorityProjection(
        state=state,
        evidence_id=AUTH_ID if state in {AuthorizationState.AUTHORIZED, AuthorizationState.STALE} else None,
    )


def _state(**overrides):
    values = dict(
        repository="Blummer92/agent-os",
        issue_number=1097,
        source_revision=SHA,
        observed_at="2026-08-26T21:00:00Z",
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


def _handoff(state=None, **overrides):
    evidence = CodingCommandCenterEvidence(
        operational_state=state or _state(),
        source_revision=SHA,
        **overrides,
    )
    return build_coding_command_center_handoff(evidence)


def test_ready_state_projects_without_creating_authority_or_side_effects():
    result = _handoff()
    assert result.repository == "Blummer92/agent-os"
    assert result.issue_number == 1097
    assert result.current_stage == "implementation"
    assert result.authority_created is False
    assert result.side_effects_performed is False
    assert result.notion_write_performed is False


def test_missing_optional_evidence_remains_explicitly_unavailable_in_rendering():
    rendered = render_coding_command_center_handoff(_handoff())
    assert "Route / escalation reason: unavailable" in rendered
    assert "validation=unavailable" in rendered
    assert "Handoff target: unavailable" in rendered


def test_single_primary_claim_preserves_pr_identity():
    claim = PrimaryIssueClaim(
        pull_request_number=1415,
        branch="agent/1097-coding-command-center-handoff",
        head_sha=SHA,
        state="draft",
    )
    result = _handoff(_state(primary_claims=(claim,)), observed_head_sha=SHA)
    assert result.pull_request_number == 1415
    assert result.observed_head_sha == SHA


def test_blocked_state_surfaces_canonical_blocker_without_reranking():
    state = _state(
        readiness=ReadinessState.BLOCKED,
        implementation_authorization=_authority(AuthorizationState.NOT_AUTHORIZED),
    )
    result = _handoff(state)
    assert result.primary_blocker in state.blocker_codes
    assert result.smallest_next_action == "clear the primary canonical blocker before continuing"
    assert "handoff.blocked" in result.reason_codes


def test_stale_state_fails_closed():
    result = _handoff(_state(freshness_state=FreshnessState.STALE))
    assert result.smallest_next_action.startswith("reacquire current canonical evidence")
    assert "handoff.fail-closed-currentness" in result.reason_codes


def test_pending_validation_does_not_synthesize_completion():
    result = _handoff(_state(validation_state=ValidationState.PENDING))
    assert result.smallest_next_action == "await current validation evidence"
    assert "complete" not in result.smallest_next_action


def test_serialization_is_deterministic_and_bounded():
    first = _handoff()
    second = _handoff()
    assert first == second
    assert serialize_coding_command_center_handoff(first) == serialize_coding_command_center_handoff(second)
    assert first.handoff_id == second.handoff_id


def test_source_revision_conflict_fails_closed():
    with pytest.raises(ValueError, match="source_revision conflicts"):
        CodingCommandCenterEvidence(
            operational_state=_state(),
            source_revision="c" * 40,
        )


def test_tampered_state_identity_is_rejected():
    state = _state()
    tampered = replace(state, state_id="issue-operational-state:" + "d" * 64)
    with pytest.raises(ValueError, match="operational state validation failed"):
        _handoff(tampered)


def test_rendering_preserves_required_visible_order():
    lines = render_coding_command_center_handoff(_handoff()).splitlines()
    assert lines[0].startswith("Current target:")
    assert lines[1].startswith("Smallest safe next action:")
    assert lines[2].startswith("Route / escalation reason:")
    assert lines[3].startswith("Validation or blocker evidence:")
    assert lines[4].startswith("Handoff target:")
