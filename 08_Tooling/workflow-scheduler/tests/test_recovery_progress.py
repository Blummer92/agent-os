from __future__ import annotations

from workflow_scheduler.execution.continuation import (
    CONTINUATION_SCHEMA_VERSION,
    ContinuationDecision,
    ContinuationDisposition,
)
from workflow_scheduler.execution.recovery_progress import (
    RecoveryProgressDisposition,
    RecoverySemanticEvidence,
    classify_recovery_progress,
)

SHA_A = "a" * 40
SHA_B = "b" * 40


def _continuation(**overrides) -> ContinuationDecision:
    values = dict(
        schema_version=CONTINUATION_SCHEMA_VERSION,
        disposition=ContinuationDisposition.NEEDS_DECISION,
        repository="Blummer92/agent-os",
        issue_number=1200,
        branch="agent/1200-recovery-loop-detection",
        observed_base_sha=SHA_A,
        observed_head_sha=SHA_A,
        current_base_sha=SHA_A,
        current_head_sha=SHA_A,
        invocation_id="invocation-1200",
        execution_id="execution-1200",
        candidate_identity="candidate:1200",
        checkpoint_lineage_identity="checkpoint:1200",
        authorization_identity="authorization:1200",
        executor_identity="governed-runner",
        scope_identity="scope:1200",
        resume_plan_id="resume-plan:1200",
        resume_point="focused-tests-passed",
        lease_identity="lease:1200",
        lease_holder_identity=None,
        lease_generation=3,
        reason_codes=("lease.ambiguous",),
        recommended_action="manual recovery",
    )
    values.update(overrides)
    return ContinuationDecision(**values)


def _semantic(**overrides) -> RecoverySemanticEvidence:
    values = dict(
        continuation=_continuation(),
        recovery_action="reacquire-current-evidence",
        effective_blocker="lease.ambiguous",
        route_decision_id="route:same",
        environment_evidence_id="environment:same",
    )
    values.update(overrides)
    return RecoverySemanticEvidence(**values)


def test_initial_observation_is_non_authorizing() -> None:
    result = classify_recovery_progress(_semantic())
    assert result.disposition is RecoveryProgressDisposition.INITIAL
    assert result.progress_made is False
    assert result.retry_authorized is False
    assert result.lease_takeover_authorized is False
    assert result.branch_refresh_authorized is False


def test_equivalent_recovery_is_not_false_progress() -> None:
    prior = _semantic()
    current = _semantic()
    result = classify_recovery_progress(current, prior=prior)
    assert result.disposition is RecoveryProgressDisposition.EQUIVALENT
    assert result.progress_made is False
    assert "recovery.no-semantic-progress" in result.reason_codes
    assert result.transition_fingerprint is not None


def test_repeated_equivalent_transition_stalls_without_arbitrary_retry_count() -> None:
    prior = _semantic()
    current = _semantic()
    first = classify_recovery_progress(current, prior=prior)
    stalled = classify_recovery_progress(
        current,
        prior=prior,
        prior_transition_fingerprint=first.transition_fingerprint,
    )
    assert stalled.disposition is RecoveryProgressDisposition.RECOVERY_STALLED
    assert stalled.progress_made is False
    assert "recovery.repeated-equivalent-transition" in stalled.reason_codes
    assert "human decision" in stalled.recommended_action
    assert stalled.retry_authorized is False


def test_new_effective_blocker_is_semantic_progress() -> None:
    prior = _semantic()
    current = _semantic(effective_blocker="dependency.source-unavailable")
    result = classify_recovery_progress(current, prior=prior)
    assert result.disposition is RecoveryProgressDisposition.PROGRESSED
    assert result.progress_made is True


def test_route_change_to_new_capability_state_is_progress() -> None:
    prior = _semantic(route_decision_id="route:incapable")
    current = _semantic(route_decision_id="route:capable")
    result = classify_recovery_progress(current, prior=prior)
    assert result.disposition is RecoveryProgressDisposition.PROGRESSED


def test_new_validation_evidence_is_progress_when_semantically_bound() -> None:
    prior = _semantic(validation_evidence_id="validation:pending")
    current = _semantic(validation_evidence_id="validation:passed-current-head")
    result = classify_recovery_progress(current, prior=prior)
    assert result.disposition is RecoveryProgressDisposition.PROGRESSED


def test_mechanical_sha_churn_alone_is_not_progress() -> None:
    prior = _semantic()
    moved = _continuation(
        observed_base_sha=SHA_B,
        observed_head_sha=SHA_B,
        current_base_sha=SHA_B,
        current_head_sha=SHA_B,
    )
    current = _semantic(continuation=moved)
    assert current.semantic_fingerprint == prior.semantic_fingerprint
    result = classify_recovery_progress(current, prior=prior)
    assert result.disposition is RecoveryProgressDisposition.EQUIVALENT
    assert result.progress_made is False


def test_regenerated_continuation_decision_id_alone_is_not_progress() -> None:
    prior = _semantic()
    regenerated = _continuation(recommended_action="same recovery, differently rendered")
    assert regenerated.decision_id != prior.continuation.decision_id
    current = _semantic(continuation=regenerated)
    assert current.semantic_fingerprint == prior.semantic_fingerprint


def test_ambiguous_orphaned_lease_repetition_stalls_without_takeover() -> None:
    prior = _semantic(effective_blocker="lease.ambiguous")
    current = _semantic(effective_blocker="lease.ambiguous")
    first = classify_recovery_progress(current, prior=prior)
    result = classify_recovery_progress(
        current,
        prior=prior,
        prior_transition_fingerprint=first.transition_fingerprint,
    )
    assert result.disposition is RecoveryProgressDisposition.RECOVERY_STALLED
    assert result.lease_takeover_authorized is False


def test_changed_lease_generation_is_progress_only_when_semantic_lease_state_moves() -> None:
    prior = _semantic()
    released = _continuation(
        disposition=ContinuationDisposition.RESUMABLE_EXISTING_WORK,
        lease_generation=4,
        reason_codes=("existing.resumable", "lease.no-active-conflict"),
        recommended_action="continue",
    )
    current = _semantic(
        continuation=released,
        effective_blocker="none",
        recovery_action="resume",
    )
    result = classify_recovery_progress(current, prior=prior)
    assert result.disposition is RecoveryProgressDisposition.PROGRESSED


def test_semantic_identity_inputs_are_deterministic_and_bounded() -> None:
    first = _semantic(additional_semantic_identities=("dependency:1", "review:0"))
    second = _semantic(additional_semantic_identities=("dependency:1", "review:0"))
    assert first.semantic_fingerprint == second.semantic_fingerprint


def test_unsorted_additional_identities_fail_closed() -> None:
    try:
        _semantic(additional_semantic_identities=("z", "a"))
    except ValueError as exc:
        assert "sorted and unique" in str(exc)
    else:
        raise AssertionError("expected unsorted semantic identities to fail closed")
