from __future__ import annotations

import json

import pytest

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
from scripts.agent_os_issue_acceptance.operating_mode import (
    OPERATING_MODE_DECISION_SCHEMA_NAME,
    OPERATING_MODE_DECISION_SCHEMA_VERSION,
    AgentOperatingModeDecision,
    EnvironmentCapabilityEvidence,
    EnvironmentCapabilityState,
    OperatingModeOutcome,
    RequestedMode,
    deserialize_agent_operating_mode_decision,
    evaluate_operating_mode_decision,
    serialize_agent_operating_mode_decision,
)

SOURCE_SHA = "a" * 40
BASE_SHA = "b" * 40
MOVED_BASE_SHA = "c" * 40
APPROVAL_ID = "approval:" + "1" * 64
ENV_EVIDENCE_ID = "environment-capability:" + "2" * 64


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
        "issue_number": 901,
        "source_revision": SOURCE_SHA,
        "observed_at": "2026-08-04T12:00:00Z",
        "evidence_ids": (APPROVAL_ID,),
        "source_state": SourceState.COMPLETE,
        "issue_state": IssueState.OPEN,
        "lifecycle_stage": LifecycleStage.PLANNING,
        "terminal_disposition": TerminalDisposition.NONE,
        "readiness": ReadinessState.READY,
        "implementation_authorization": authority(AuthorizationState.AUTHORIZED),
        "ready_for_review_authorization": authority(AuthorizationState.AUTHORIZED),
        "execution_authorization": authority(AuthorizationState.NOT_AUTHORIZED),
        "merge_authorization": authority(AuthorizationState.AUTHORIZED),
        "closure_authorization": authority(AuthorizationState.AUTHORIZED),
        "external_write_authorization": authority(AuthorizationState.NOT_AUTHORIZED),
        "dependency_state": DependencyState.CLEAR,
        "primary_claims": (),
        "validation_state": ValidationState.NOT_RUN,
        "freshness_state": FreshnessState.CURRENT,
        "observed_labels": ("status:ready",),
    }
    data.update(changes)
    return IssueOperationalEvidence(**data)


def state(**changes: object):
    return build_issue_operational_state(evidence(**changes))


def environment(**changes: object) -> EnvironmentCapabilityEvidence:
    data: dict[str, object] = {
        "local_execution_state": EnvironmentCapabilityState.VERIFIED,
        "push_state": EnvironmentCapabilityState.VERIFIED,
        "evidence_id": ENV_EVIDENCE_ID,
        "bound_source_revision": None,
        "observed_source_revision": None,
    }
    data.update(changes)
    return EnvironmentCapabilityEvidence(**data)


# --- explicit mode requests -------------------------------------------------


def test_explicit_planning_mode():
    decision = evaluate_operating_mode_decision(state(), "planning", environment())
    assert decision.requested_mode is RequestedMode.PLANNING
    assert decision.effective_mode is RequestedMode.PLANNING
    assert decision.outcome is OperatingModeOutcome.PLANNED
    assert decision.maximum_permitted_stage is LifecycleStage.PLANNING
    assert decision.side_effects_performed is False


def test_explicit_build_mode():
    decision = evaluate_operating_mode_decision(
        state(lifecycle_stage=LifecycleStage.PLANNING), "build", environment()
    )
    assert decision.outcome is OperatingModeOutcome.BUILT
    assert decision.maximum_permitted_stage is LifecycleStage.IMPLEMENTATION
    assert decision.next_permitted_action == "push-and-open-draft-pr"


def test_explicit_draft_pr_mode():
    decision = evaluate_operating_mode_decision(
        state(lifecycle_stage=LifecycleStage.IMPLEMENTATION), "draft-pr", environment()
    )
    assert decision.outcome is OperatingModeOutcome.DRAFT_PR_OPENED
    assert decision.maximum_permitted_stage is LifecycleStage.DRAFT_PR


def test_explicit_review_mode():
    decision = evaluate_operating_mode_decision(
        state(lifecycle_stage=LifecycleStage.DRAFT_PR), "review", environment()
    )
    assert decision.outcome is OperatingModeOutcome.REVIEW_COMPLETE
    assert decision.maximum_permitted_stage is LifecycleStage.REVIEW


def test_explicit_release_mode():
    decision = evaluate_operating_mode_decision(
        state(lifecycle_stage=LifecycleStage.REVIEW), "release", environment()
    )
    assert decision.outcome is OperatingModeOutcome.RELEASED
    assert decision.maximum_permitted_stage is LifecycleStage.CLOSED
    assert decision.next_permitted_action == "none"
    assert decision.prohibited_actions == ()


# --- authorization and environment gating -----------------------------------


def test_release_without_merge_authorization():
    decision = evaluate_operating_mode_decision(
        state(
            lifecycle_stage=LifecycleStage.REVIEW,
            merge_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
        ),
        "release",
        environment(),
    )
    assert decision.outcome is OperatingModeOutcome.REVIEW_COMPLETE
    assert decision.maximum_permitted_stage is LifecycleStage.REVIEW
    assert "authorization.merge-not-authorized" in decision.blocker_codes
    assert decision.required_human_authorizations == ("merge",)


def test_release_without_closure_authorization():
    decision = evaluate_operating_mode_decision(
        state(
            lifecycle_stage=LifecycleStage.REVIEW,
            closure_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
        ),
        "release",
        environment(),
    )
    assert decision.outcome is OperatingModeOutcome.RELEASED
    assert decision.maximum_permitted_stage is LifecycleStage.MERGED
    assert "authorization.closure-not-authorized" in decision.blocker_codes
    assert decision.required_human_authorizations == ("closure",)


def test_draft_pr_without_push_capability():
    decision = evaluate_operating_mode_decision(
        state(lifecycle_stage=LifecycleStage.IMPLEMENTATION),
        "draft-pr",
        environment(push_state=EnvironmentCapabilityState.NOT_VERIFIED),
    )
    assert decision.outcome is OperatingModeOutcome.BUILT
    assert decision.maximum_permitted_stage is LifecycleStage.IMPLEMENTATION
    assert "environment.push-not-verified" in decision.blocker_codes
    assert decision.required_environment_capabilities == ("push",)


def test_review_without_ready_for_review_authorization():
    decision = evaluate_operating_mode_decision(
        state(
            lifecycle_stage=LifecycleStage.DRAFT_PR,
            ready_for_review_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
        ),
        "review",
        environment(),
    )
    assert decision.outcome is OperatingModeOutcome.DRAFT_PR_OPENED
    assert decision.maximum_permitted_stage is LifecycleStage.DRAFT_PR
    assert "authorization.ready-for-review-not-authorized" in decision.blocker_codes


# --- issue-state gating ------------------------------------------------------


def test_build_for_blocked_state():
    decision = evaluate_operating_mode_decision(
        state(readiness=ReadinessState.BLOCKED), "build", environment()
    )
    assert decision.outcome is OperatingModeOutcome.BLOCKED
    assert decision.maximum_permitted_stage is LifecycleStage.PLANNING
    assert "state.blocked" in decision.blocker_codes


def test_build_for_terminal_state():
    decision = evaluate_operating_mode_decision(
        state(
            issue_state=IssueState.CLOSED,
            lifecycle_stage=LifecycleStage.CLOSED,
            terminal_disposition=TerminalDisposition.COMPLETED,
        ),
        "build",
        environment(),
    )
    assert decision.outcome is OperatingModeOutcome.BLOCKED
    assert "state.terminal" in decision.blocker_codes


# --- mode defaulting and compatibility phrases -------------------------------


def test_missing_mode_defaults_to_planning():
    decision = evaluate_operating_mode_decision(state(), None, environment())
    assert decision.requested_mode is RequestedMode.PLANNING
    assert decision.outcome is OperatingModeOutcome.PLANNED
    assert "mode.missing" in decision.blocker_codes


def test_ambiguous_mode_defaults_to_planning():
    decision = evaluate_operating_mode_decision(state(), "banana", environment())
    assert decision.requested_mode is RequestedMode.PLANNING
    assert decision.outcome is OperatingModeOutcome.PLANNED
    assert "mode.unrecognized" in decision.blocker_codes


@pytest.mark.parametrize("phrase", ["complete", "finish", "do everything"])
def test_compatibility_phrases_never_imply_release(phrase):
    decision = evaluate_operating_mode_decision(
        state(lifecycle_stage=LifecycleStage.MERGED), phrase, environment()
    )
    assert decision.requested_mode is RequestedMode.PLANNING
    assert decision.effective_mode is RequestedMode.PLANNING
    assert decision.outcome is OperatingModeOutcome.PLANNED
    assert decision.maximum_permitted_stage is LifecycleStage.PLANNING
    assert "compatibility.legacy-phrase-ignored" in decision.blocker_codes


# --- multi-issue campaign independence ---------------------------------------


def test_independent_effective_modes_in_multi_issue_campaign():
    ready_decision = evaluate_operating_mode_decision(
        state(lifecycle_stage=LifecycleStage.PLANNING), "build", environment()
    )
    blocked_decision = evaluate_operating_mode_decision(
        state(readiness=ReadinessState.BLOCKED), "build", environment()
    )
    assert ready_decision.outcome is OperatingModeOutcome.BUILT
    assert blocked_decision.outcome is OperatingModeOutcome.BLOCKED
    assert ready_decision.requested_mode is blocked_decision.requested_mode


# --- fail-closed evidence handling -------------------------------------------


def test_stale_issue_operational_state_evidence():
    decision = evaluate_operating_mode_decision(
        state(freshness_state=FreshnessState.STALE), "build", environment()
    )
    assert decision.outcome is OperatingModeOutcome.BLOCKED
    assert "state.stale" in decision.blocker_codes


def test_stale_authorization_evidence():
    decision = evaluate_operating_mode_decision(
        state(
            merge_authorization=authority(
                AuthorizationState.AUTHORIZED,
                bound_base_sha=BASE_SHA,
                observed_base_sha=MOVED_BASE_SHA,
            )
        ),
        "build",
        environment(),
    )
    assert decision.outcome is OperatingModeOutcome.BLOCKED
    assert "state.stale" in decision.blocker_codes


def test_stale_environment_evidence():
    decision = evaluate_operating_mode_decision(
        state(lifecycle_stage=LifecycleStage.PLANNING),
        "build",
        environment(bound_source_revision=BASE_SHA, observed_source_revision=MOVED_BASE_SHA),
    )
    assert decision.outcome is OperatingModeOutcome.BLOCKED
    assert "environment.local-execution-stale" in decision.blocker_codes


def test_contradictory_environment_evidence_fails_closed():
    with pytest.raises(ValueError):
        EnvironmentCapabilityEvidence(
            local_execution_state=EnvironmentCapabilityState.VERIFIED,
            push_state=EnvironmentCapabilityState.NOT_VERIFIED,
            evidence_id=None,
        )


def test_non_operational_state_input_fails_closed():
    with pytest.raises(TypeError):
        evaluate_operating_mode_decision(object(), "planning", environment())


def test_non_environment_evidence_input_fails_closed():
    with pytest.raises(TypeError):
        evaluate_operating_mode_decision(state(), "planning", object())


# --- serialization, identity, and round trip ---------------------------------


def test_malformed_payload_fails_closed():
    with pytest.raises(ValueError):
        deserialize_agent_operating_mode_decision("not json")


def test_unknown_field_fails_closed():
    decision = evaluate_operating_mode_decision(state(), "planning", environment())
    payload = json.loads(serialize_agent_operating_mode_decision(decision))
    payload["unexpected"] = True
    with pytest.raises(ValueError):
        deserialize_agent_operating_mode_decision(json.dumps(payload))


def test_unsupported_version_fails_closed():
    decision = evaluate_operating_mode_decision(state(), "planning", environment())
    payload = json.loads(serialize_agent_operating_mode_decision(decision))
    payload["schema_version"] = "9.9"
    with pytest.raises(ValueError):
        deserialize_agent_operating_mode_decision(json.dumps(payload))


def test_tampered_semantic_identity_fails_closed():
    decision = evaluate_operating_mode_decision(state(), "planning", environment())
    payload = json.loads(serialize_agent_operating_mode_decision(decision))
    payload["decision_id"] = "operating-mode-decision:" + "0" * 64
    with pytest.raises(ValueError):
        deserialize_agent_operating_mode_decision(json.dumps(payload))


def test_deterministic_reason_and_blocker_ordering():
    first = evaluate_operating_mode_decision(
        state(
            lifecycle_stage=LifecycleStage.REVIEW,
            merge_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
        ),
        "release",
        environment(),
    )
    second = evaluate_operating_mode_decision(
        state(
            lifecycle_stage=LifecycleStage.REVIEW,
            merge_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
        ),
        "release",
        environment(),
    )
    assert first.reason_codes == second.reason_codes
    assert first.reason_codes == tuple(sorted(first.reason_codes))
    assert first.blocker_codes == tuple(sorted(first.blocker_codes))


def test_deterministic_prohibited_action_ordering():
    decision = evaluate_operating_mode_decision(state(), "planning", environment())
    assert decision.prohibited_actions == tuple(sorted(decision.prohibited_actions))
    assert decision.prohibited_actions == (
        "build",
        "close-issue",
        "flip-ready-for-review",
        "merge",
        "push-and-open-draft-pr",
    )


def test_byte_stable_round_trip():
    decision = evaluate_operating_mode_decision(
        state(lifecycle_stage=LifecycleStage.MERGED), "release", environment()
    )
    serialized_once = serialize_agent_operating_mode_decision(decision)
    restored = deserialize_agent_operating_mode_decision(serialized_once)
    serialized_twice = serialize_agent_operating_mode_decision(restored)
    assert serialized_once == serialized_twice


# --- authority preservation and side effects ---------------------------------


def test_authority_never_broadened():
    operational_state = state(merge_authorization=authority(AuthorizationState.NOT_AUTHORIZED))
    decision = evaluate_operating_mode_decision(operational_state, "release", environment())
    assert decision.merge_authorization.state is AuthorizationState.NOT_AUTHORIZED
    assert decision.merge_authorization == operational_state.merge_authorization.effective()


@pytest.mark.parametrize(
    "mode",
    ["planning", "build", "draft-pr", "review", "release", None, "banana"],
)
def test_side_effects_never_performed(mode):
    decision = evaluate_operating_mode_decision(
        state(lifecycle_stage=LifecycleStage.MERGED), mode, environment()
    )
    assert decision.side_effects_performed is False


def test_schema_name_and_version():
    decision = evaluate_operating_mode_decision(state(), "planning", environment())
    assert decision.schema_name == OPERATING_MODE_DECISION_SCHEMA_NAME
    assert decision.schema_version == OPERATING_MODE_DECISION_SCHEMA_VERSION
    assert decision.schema_name == "agent-os-operating-mode-decision"
    assert decision.schema_version == "1.0"


def test_decision_id_is_content_addressed():
    first = evaluate_operating_mode_decision(state(), "planning", environment())
    second = evaluate_operating_mode_decision(state(), "planning", environment())
    assert first.decision_id == second.decision_id
    third = evaluate_operating_mode_decision(
        state(lifecycle_stage=LifecycleStage.MERGED), "release", environment()
    )
    assert third.decision_id != first.decision_id
